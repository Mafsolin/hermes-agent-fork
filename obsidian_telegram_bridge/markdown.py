from __future__ import annotations

from pathlib import Path
import re
from typing import Any


_SAFE_CHARS_RE = re.compile(r"[\\/:*?\"<>|]+")


def _safe_name(value: str, fallback: str = "Без названия") -> str:
    value = _SAFE_CHARS_RE.sub(" ", (value or "").strip())
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value or fallback


def _frontmatter(title: str, page_type: str, tags: list[str], today: str, source: str) -> str:
    tags_text = ", ".join(tags)
    return (
        "---\n"
        f"title: {title}\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"type: {page_type}\n"
        f"tags: [{tags_text}]\n"
        f"sources: [{source}]\n"
        "---\n\n"
    )


class ObsidianMemoryWriter:
    """Writes user-facing Telegram memory items into a Russian Obsidian vault."""

    def __init__(self, vault_path: str | Path):
        self.vault_path = Path(vault_path).expanduser().resolve()
        self.vault_path.mkdir(parents=True, exist_ok=True)

    def preview_memory_items(self, items: dict[str, Any], *, source: str, today: str) -> list[Path]:
        """Return candidate files that would be touched without writing them."""
        paths: list[Path] = []
        for person in items.get("people") or []:
            facts = [str(x).strip() for x in (person.get("facts") or []) if str(x).strip()]
            if facts:
                name = _safe_name(str(person.get("name") or ""), "Неизвестный человек")
                paths.append(self.vault_path / "Люди" / f"{name}.md")
        for project in items.get("projects") or []:
            updates = [str(x).strip() for x in (project.get("updates") or []) if str(x).strip()]
            if updates:
                name = _safe_name(str(project.get("name") or ""), "Безымянный проект")
                paths.append(self.vault_path / "Проекты" / f"{name}.md")
        for agreement in items.get("agreements") or []:
            title = _safe_name(str(agreement.get("title") or "Договорённость"), "Договорённость")
            raw_date = str(agreement.get("date") or today).strip() or today
            date = _safe_name(raw_date[:10], today)
            if str(agreement.get("summary") or "").strip() or agreement.get("participants"):
                paths.append(self.vault_path / "Договорённости" / f"{date} — {title}.md")
        for task in items.get("tasks") or []:
            title = _safe_name(str(task.get("title") or "Задача"), "Задача")
            raw_date = str(task.get("date") or today).strip() or today
            date = _safe_name(raw_date[:10], today)
            if self._item_bullets(task, preferred_keys=("summary", "details", "status")):
                paths.append(self.vault_path / "Tasks" / f"{date} — {title}.md")
        for place in items.get("places") or []:
            facts = [str(x).strip() for x in (place.get("facts") or []) if str(x).strip()]
            if facts:
                name = _safe_name(str(place.get("name") or ""), "Безымянное место")
                paths.append(self.vault_path / "Места" / f"{name}.md")
        if items.get("review"):
            paths.append(self.vault_path / "На разбор" / f"{today} Telegram Business.md")
        return paths

    def apply_memory_items(self, items: dict[str, Any], *, source: str, today: str) -> list[Path]:
        changed: list[Path] = []
        for person in items.get("people") or []:
            name = _safe_name(str(person.get("name") or ""), "Неизвестный человек")
            facts = [str(x).strip() for x in (person.get("facts") or []) if str(x).strip()]
            if facts:
                self._append_if_changed(changed, self._append_section(
                    self.vault_path / "Люди" / f"{name}.md",
                    title=name,
                    page_type="entity",
                    tags=["person"],
                    today=today,
                    source=source,
                    heading=today,
                    bullets=facts,
                    links=["[[Индекс памяти]]"],
                ))

        for project in items.get("projects") or []:
            name = _safe_name(str(project.get("name") or ""), "Безымянный проект")
            updates = [str(x).strip() for x in (project.get("updates") or []) if str(x).strip()]
            if updates:
                self._append_if_changed(changed, self._append_section(
                    self.vault_path / "Проекты" / f"{name}.md",
                    title=name,
                    page_type="entity",
                    tags=["project"],
                    today=today,
                    source=source,
                    heading=today,
                    bullets=updates,
                    links=["[[Индекс памяти]]"],
                ))

        for agreement in items.get("agreements") or []:
            title = _safe_name(str(agreement.get("title") or "Договорённость"), "Договорённость")
            raw_date = str(agreement.get("date") or today).strip() or today
            date = _safe_name(raw_date[:10], today)
            summary = str(agreement.get("summary") or "").strip()
            participants = [str(x).strip() for x in (agreement.get("participants") or []) if str(x).strip()]
            bullets = []
            if summary:
                bullets.append(summary)
            if participants:
                bullets.append("Участники: " + ", ".join(participants))
            if bullets:
                self._append_if_changed(changed, self._append_section(
                    self.vault_path / "Договорённости" / f"{date} — {title}.md",
                    title=title,
                    page_type="summary",
                    tags=["agreement"],
                    today=today,
                    source=source,
                    heading="Суть",
                    bullets=bullets,
                    links=["[[Индекс памяти]]"],
                ))

        for task in items.get("tasks") or []:
            title = _safe_name(str(task.get("title") or "Задача"), "Задача")
            raw_date = str(task.get("date") or today).strip() or today
            date = _safe_name(raw_date[:10], today)
            bullets = self._item_bullets(task, preferred_keys=("summary", "details", "status"))
            if bullets:
                self._append_if_changed(changed, self._append_section(
                    self.vault_path / "Tasks" / f"{date} — {title}.md",
                    title=title,
                    page_type="task",
                    tags=["task"],
                    today=today,
                    source=source,
                    heading="Суть",
                    bullets=bullets,
                    links=["[[Индекс памяти]]"],
                ))

        for place in items.get("places") or []:
            name = _safe_name(str(place.get("name") or ""), "Безымянное место")
            facts = [str(x).strip() for x in (place.get("facts") or []) if str(x).strip()]
            if facts:
                self._append_if_changed(changed, self._append_section(
                    self.vault_path / "Места" / f"{name}.md",
                    title=name,
                    page_type="place",
                    tags=["place"],
                    today=today,
                    source=source,
                    heading=today,
                    bullets=facts,
                    links=["[[Индекс памяти]]"],
                ))

        review_items = items.get("review") or []
        if review_items:
            self._append_if_changed(changed, self._append_review(review_items, source=source, today=today))

        if changed:
            self._refresh_index(today=today)
            self._append_log(today=today, changed=changed)
        return changed

    @staticmethod
    def _append_if_changed(changed: list[Path], path: Path | None) -> None:
        if path is not None:
            changed.append(path)

    @staticmethod
    def _item_bullets(item: dict[str, Any], *, preferred_keys: tuple[str, ...]) -> list[str]:
        bullets: list[str] = []
        for key in preferred_keys:
            value = item.get(key)
            if isinstance(value, list):
                bullets.extend(str(part).strip() for part in value if str(part).strip())
            elif str(value or "").strip():
                label = {
                    "status": "Статус",
                    "details": "Детали",
                }.get(key)
                text = str(value).strip()
                bullets.append(f"{label}: {text}" if label else text)
        return bullets

    def _append_section(
        self,
        path: Path,
        *,
        title: str,
        page_type: str,
        tags: list[str],
        today: str,
        source: str,
        heading: str,
        bullets: list[str],
        links: list[str],
    ) -> Path | None:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if not existing:
            existing = _frontmatter(title, page_type, tags, today, source) + f"# {title}\n\n"
            if links:
                existing += "## Связи\n" + "\n".join(f"- {link}" for link in links) + "\n\n"
        block_lines = [f"## {heading}"] + [f"- {bullet}" for bullet in bullets]
        block = "\n".join(block_lines) + "\n"
        if block not in existing:
            existing = existing.rstrip() + "\n\n" + block
            path.write_text(existing, encoding="utf-8")
            return path
        return None

    def _append_review(self, review_items: list[dict[str, Any]], *, source: str, today: str) -> Path | None:
        path = self.vault_path / "На разбор" / f"{today} Telegram Business.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        title = f"На разбор — Telegram Business — {today}"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if not existing:
            existing = _frontmatter(title, "review", ["review", "telegram-business"], today, source) + f"# {title}\n\n"
        blocks: list[str] = []
        for item in review_items:
            item_title = _safe_name(str(item.get("title") or "Возможно важно"), "Возможно важно")
            bullets = self._item_bullets(item, preferred_keys=("summary", "details", "reason"))
            if not bullets:
                continue
            blocks.append("\n".join([f"## {item_title}", *[f"- {bullet}" for bullet in bullets]]) + "\n")
        if not blocks:
            return None
        changed = False
        text = existing.rstrip()
        for block in blocks:
            if block.strip() not in text:
                text += "\n\n" + block.rstrip()
                changed = True
        if changed:
            path.write_text(text.rstrip() + "\n", encoding="utf-8")
            return path
        return None

    def _refresh_index(self, *, today: str) -> None:
        entries: dict[str, list[str]] = {}
        for folder in ("Люди", "Проекты", "Договорённости", "Tasks", "Места", "На разбор", "Сервер", "Понятия", "Сущности"):
            folder_path = self.vault_path / folder
            if not folder_path.exists():
                continue
            pages = sorted(p for p in folder_path.glob("*.md") if p.is_file())
            if pages:
                entries[folder] = [f"- [[{p.stem}|{p.stem}]]" for p in pages]

        lines = [
            "---",
            "title: Индекс памяти",
            f"created: {today}",
            f"updated: {today}",
            "type: summary",
            "tags: [memory, obsidian]",
            "sources: [conversation, Telegram Business]",
            "---",
            "",
            "# Индекс памяти",
            "",
            f"> Обновлено: {today}",
            "",
        ]
        for folder, folder_entries in entries.items():
            lines.extend([f"## {folder}", *folder_entries, ""])
        lines.extend(["## Навигация", "- [[Схема памяти]]", "- [[Журнал изменений]]", ""])
        (self.vault_path / "Индекс памяти.md").write_text("\n".join(lines), encoding="utf-8")

    def _append_log(self, *, today: str, changed: list[Path]) -> None:
        path = self.vault_path / "Журнал изменений.md"
        if path.exists():
            text = path.read_text(encoding="utf-8").rstrip()
        else:
            text = _frontmatter("Журнал изменений", "summary", ["memory", "log"], today, "conversation") + "# Журнал изменений\n"
        if not changed:
            return
        rels = sorted({p.relative_to(self.vault_path).as_posix() for p in changed})
        block = "\n\n" + f"## [{today}] ingest | Telegram Business\n" + "\n".join(f"- Обновлено: {rel}" for rel in rels)
        if block.strip() not in text:
            path.write_text(text + block + "\n", encoding="utf-8")
