"""Tests for lightweight per-turn trace manifests."""

import json

from agent.trajectory import build_turn_trace_manifest, save_turn_trace_manifest


def test_turn_trace_manifest_extracts_tool_memory_and_delegation_events():
    messages = [
        {"role": "user", "content": "before"},
        {"role": "user", "content": "current turn"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "memory",
                        "arguments": json.dumps({"action": "add", "target": "memory", "content": "Tool recipe: use X"}),
                    },
                },
                {
                    "id": "call_2",
                    "function": {
                        "name": "delegate_task",
                        "arguments": json.dumps({"goal": "inspect repo", "toolsets": ["terminal"]}),
                    },
                },
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"success": true}'},
        {"role": "tool", "tool_call_id": "call_2", "content": '[{"summary": "done"}]'},
        {"role": "assistant", "content": "done"},
    ]

    manifest = build_turn_trace_manifest(
        messages,
        turn_start_index=1,
        session_id="sess-1",
        model="model-a",
        provider="provider-a",
        platform="telegram",
        api_calls=2,
        completed=True,
    )

    assert manifest["schema_version"] == 1
    assert manifest["session_id"] == "sess-1"
    assert manifest["turn"]["message_count"] == 5
    assert [call["name"] for call in manifest["tool_calls"]] == ["memory", "delegate_task"]
    assert manifest["tool_calls"][0]["result"]["success"] is True
    assert manifest["memory_writes"] == [
        {"tool_call_id": "call_1", "action": "add", "target": "memory"}
    ]
    assert manifest["delegations"] == [
        {"tool_call_id": "call_2", "mode": "single", "toolsets": ["terminal"]}
    ]


def test_save_turn_trace_manifest_writes_json_file(tmp_path):
    manifest = {"schema_version": 1, "session_id": "sess-1", "tool_calls": []}

    path = save_turn_trace_manifest(manifest, tmp_path)

    assert path.name.startswith("turn_trace_sess-1_")
    assert path.suffix == ".json"
    assert json.loads(path.read_text(encoding="utf-8")) == manifest
