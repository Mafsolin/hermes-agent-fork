from __future__ import annotations

import json
import os
import re
from typing import Any

from .storage import BusinessMessage


class RuleBasedExtractor:
    """Safe fallback extractor for obvious agreements/tasks when no LLM is configured."""

    AGREEMENT_RE = re.compile(r"\b(договорил|договорились|созвон|встреч|завтра|сегодня|дедлайн|обещал|обещала|пришлю|скину)\b", re.IGNORECASE)

    def __call__(self, messages: list[BusinessMessage]) -> dict[str, Any]:
        important = [m for m in messages if self.AGREEMENT_RE.search(m.text)]
        if not important:
            return {}
        people = {}
        updates = []
        for msg in important:
            if msg.sender_name and msg.sender_name.lower() not in {"артём", "artem", "afsol"}:
                people.setdefault(msg.sender_name, []).append(msg.text)
            updates.append(f"{msg.sender_name or 'Собеседник'}: {msg.text}")
        return {
            "people": [
                {"name": name, "facts": facts}
                for name, facts in sorted(people.items())
            ],
            "projects": [],
            "agreements": [
                {
                    "title": "Важная договорённость из диалога",
                    "date": important[-1].created_at[:10],
                    "participants": sorted({m.sender_name for m in important if m.sender_name}),
                    "summary": "\n".join(updates),
                }
            ],
            "tasks": [],
            "places": [],
            "review": [],
        }


DEFAULT_MEMORY_MODEL = "gpt-5.3-codex-spark"


class HermesLLMExtractor:
    """LLM extractor that returns structured memory JSON for Artem's Obsidian memory."""

    def __init__(self, *, model: str | None = None):
        self.model = (model or os.getenv("OBSIDIAN_MEMORY_LLM_MODEL") or DEFAULT_MEMORY_MODEL).strip()

    def __call__(self, messages: list[BusinessMessage]) -> dict[str, Any]:
        from run_agent import AIAgent

        transcript = "\n".join(
            f"[{m.created_at}] {m.sender_name or m.sender_id or 'unknown'} ({m.direction}): {m.text}"
            for m in messages
        )
        prompt = f"""
Ты извлекаешь память для Obsidian-хранилища «Память Артёма».
Сохраняй только то, что полезно самому Артёму вспомнить позже.
Не сохраняй инструкции для ассистента, болтовню, эмоции без практической пользы и лишние приватные детали.
Верни только JSON без Markdown в формате:
{{
  "people": [{{"name": "Имя", "facts": ["факт"]}}],
  "projects": [{{"name": "Проект", "updates": ["обновление"]}}],
  "agreements": [{{"title": "Название", "date": "YYYY-MM-DD или YYYY-MM-DD HH:MM", "participants": ["Имя"], "summary": "суть"}}],
  "tasks": [{{"title": "Задача", "date": "YYYY-MM-DD", "summary": "что сделать", "status": "todo"}}],
  "places": [{{"name": "Место", "facts": ["факт"]}}],
  "review": [{{"title": "Сомнительный факт", "summary": "что проверить"}}]
}}
Поле review используй только для сомнительных вещей, которые нельзя сразу класть в основную память.
Если ничего важного нет, верни пустые списки во всех ключах.

Диалог:
{transcript}
""".strip()
        kwargs = {"max_iterations": 3, "enabled_toolsets": [], "skip_memory": True}
        if self.model:
            kwargs["model"] = self.model
        agent = AIAgent(**kwargs)
        response = agent.chat(prompt)
        return self._parse_json(response)

    @staticmethod
    def _parse_json(response: str) -> dict[str, Any]:
        text = response.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            text = match.group(0)
        data = json.loads(text)
        return normalize_memory_items(data)


def normalize_memory_items(data: dict[str, Any]) -> dict[str, list[Any]]:
    """Return the strict memory extraction schema with list values only."""
    return {
        "people": data.get("people") if isinstance(data.get("people"), list) else [],
        "projects": data.get("projects") if isinstance(data.get("projects"), list) else [],
        "agreements": data.get("agreements") if isinstance(data.get("agreements"), list) else [],
        "tasks": data.get("tasks") if isinstance(data.get("tasks"), list) else [],
        "places": data.get("places") if isinstance(data.get("places"), list) else [],
        "review": data.get("review") if isinstance(data.get("review"), list) else [],
    }
