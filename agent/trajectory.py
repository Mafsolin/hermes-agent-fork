"""Trajectory saving utilities and static helpers.

_convert_to_trajectory_format stays as an AIAgent method (batch_runner.py
calls agent._convert_to_trajectory_format). Only the static helpers and
the file-write logic live here.
"""

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def convert_scratchpad_to_think(content: str) -> str:
    """Convert <REASONING_SCRATCHPAD> tags to <think> tags."""
    if not content or "<REASONING_SCRATCHPAD>" not in content:
        return content
    return content.replace("<REASONING_SCRATCHPAD>", "<think>").replace("</REASONING_SCRATCHPAD>", "</think>")


def has_incomplete_scratchpad(content: str) -> bool:
    """Check if content has an opening <REASONING_SCRATCHPAD> without a closing tag."""
    if not content:
        return False
    return "<REASONING_SCRATCHPAD>" in content and "</REASONING_SCRATCHPAD>" not in content


def _trace_tool_arguments(tool_call: Dict[str, Any]) -> Dict[str, Any]:
    """Decode a tool call's arguments without making malformed traces fatal."""
    function = tool_call.get("function") if isinstance(tool_call, dict) else None
    raw = function.get("arguments") if isinstance(function, dict) else None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _trace_tool_results(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        call_id = str(message.get("tool_call_id") or "").strip()
        if not call_id:
            continue
        content = message.get("content")
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except (TypeError, ValueError):
                pass
        results[call_id] = _sanitize_trace_value(content)
    return results


def _sanitize_trace_value(value: Any, *, depth: int = 0) -> Any:
    """Keep manifests useful while bounding accidental sensitive output."""
    if depth > 4:
        return "<truncated>"
    if isinstance(value, str):
        # Avoid importing the broader redaction stack at module import time.
        try:
            from agent.redact import redact_sensitive_text

            value = redact_sensitive_text(value)
        except Exception:
            pass
        return value[:8000]
    if isinstance(value, dict):
        return {
            str(key): _sanitize_trace_value(item, depth=depth + 1)
            for key, item in list(value.items())[:80]
        }
    if isinstance(value, list):
        return [_sanitize_trace_value(item, depth=depth + 1) for item in value[:80]]
    if isinstance(value, tuple):
        return [_sanitize_trace_value(item, depth=depth + 1) for item in value[:80]]
    return value


def build_turn_trace_manifest(
    messages: List[Dict[str, Any]],
    *,
    turn_start_index: int = 0,
    session_id: str = "",
    model: str = "",
    provider: str = "",
    platform: str = "",
    api_calls: int = 0,
    completed: bool = False,
) -> Dict[str, Any]:
    """Build a small, profile-local summary of one completed agent turn.

    The manifest deliberately stores tool names and bounded results rather than
    the full conversation. Tool arguments are inspected transiently to classify
    memory writes and delegations, so API keys or large prompt payloads do not
    get copied into the trace file.
    """
    start = max(0, min(int(turn_start_index), len(messages)))
    turn_messages = [message for message in messages[start:] if isinstance(message, dict)]
    results = _trace_tool_results(turn_messages)
    tool_calls: List[Dict[str, Any]] = []
    memory_writes: List[Dict[str, Any]] = []
    delegations: List[Dict[str, Any]] = []

    for message in turn_messages:
        if message.get("role") != "assistant":
            continue
        raw_calls = message.get("tool_calls") or []
        if not isinstance(raw_calls, list):
            continue
        for raw_call in raw_calls:
            if not isinstance(raw_call, dict):
                continue
            function = raw_call.get("function") or {}
            name = str(function.get("name") or raw_call.get("name") or "tool")
            call_id = str(raw_call.get("id") or "").strip()
            row: Dict[str, Any] = {"id": call_id, "name": name}
            if call_id in results:
                row["result"] = results[call_id]
            tool_calls.append(row)

            arguments = _trace_tool_arguments(raw_call)
            if name == "memory" and arguments.get("action"):
                memory_writes.append({
                    "tool_call_id": call_id,
                    "action": str(arguments.get("action")),
                    "target": str(arguments.get("target") or "memory"),
                })
            elif name == "delegate_task":
                toolsets = arguments.get("toolsets")
                delegations.append({
                    "tool_call_id": call_id,
                    "mode": str(arguments.get("mode") or "single"),
                    "toolsets": list(toolsets) if isinstance(toolsets, list) else [],
                })

    return {
        "schema_version": 1,
        "session_id": str(session_id or ""),
        "model": str(model or ""),
        "provider": str(provider or ""),
        "platform": str(platform or ""),
        "api_calls": int(api_calls or 0),
        "completed": bool(completed),
        "turn": {
            "start_index": start,
            "message_count": len(turn_messages),
            "completed": bool(completed),
        },
        "tool_calls": tool_calls,
        "memory_writes": memory_writes,
        "delegations": delegations,
    }


def save_turn_trace_manifest(manifest: Dict[str, Any], output_dir: str | Path) -> Path:
    """Atomically write a bounded turn manifest and return its path."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    session = str(manifest.get("session_id") or "unknown")
    session = re.sub(r"[^A-Za-z0-9._-]+", "_", session).strip("._-") or "unknown"
    session = session[:80]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = directory / f"turn_trace_{session}_{stamp}.json"
    temp_path = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    try:
        with temp_path.open("w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
    return path


def save_trajectory(trajectory: List[Dict[str, Any]], model: str,
                    completed: bool, filename: str = None):
    """Append a trajectory entry to a JSONL file.

    Args:
        trajectory: The ShareGPT-format conversation list.
        model: Model name for metadata.
        completed: Whether the conversation completed successfully.
        filename: Override output filename. Defaults to trajectory_samples.jsonl
                  or failed_trajectories.jsonl based on ``completed``.
    """
    if filename is None:
        filename = "trajectory_samples.jsonl" if completed else "failed_trajectories.jsonl"

    entry = {
        "conversations": trajectory,
        "timestamp": datetime.now().isoformat(),
        "model": model,
        "completed": completed,
    }

    try:
        with open(filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info("Trajectory saved to %s", filename)
    except Exception as e:
        logger.warning("Failed to save trajectory: %s", e)
