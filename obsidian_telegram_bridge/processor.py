from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby
from typing import Callable, Any

from .markdown import ObsidianMemoryWriter
from .storage import BridgeStore, BusinessMessage

Extractor = Callable[[list[BusinessMessage]], dict[str, Any]]


@dataclass(frozen=True)
class ProcessResult:
    processed_message_ids: list[int]
    changed_files: list[object]


class BusinessMemoryProcessor:
    """Processes buffered Telegram Business messages into Obsidian memory notes."""

    def __init__(self, store: BridgeStore, writer: ObsidianMemoryWriter, extractor: Extractor):
        self.store = store
        self.writer = writer
        self.extractor = extractor

    def process_pending(self, *, today: str, limit: int = 500, dry_run: bool = False, retention_days: int = 14) -> ProcessResult:
        pending = self.store.pending_messages(limit=limit)
        if not pending:
            return ProcessResult(processed_message_ids=[], changed_files=[])

        processed_ids: list[int] = []
        changed_files: list[object] = []
        pending_sorted = sorted(pending, key=lambda m: (m.chat_id, m.created_at, m.id))
        for _chat_id, group in groupby(pending_sorted, key=lambda m: m.chat_id):
            messages = list(group)
            active_messages = [m for m in messages if m.importance_status != "deleted"]
            memory_items = self.extractor(active_messages) if active_messages else {}
            if memory_items:
                if dry_run:
                    changed_files.extend(self.writer.preview_memory_items(memory_items, source="Telegram Business", today=today))
                else:
                    changed_files.extend(
                        self.writer.apply_memory_items(memory_items, source="Telegram Business", today=today)
                    )
            processed_ids.extend(m.id for m in messages)

        if not dry_run:
            self.store.mark_processed(processed_ids)
            self.store.purge_processed_older_than(days=retention_days)
        return ProcessResult(processed_message_ids=processed_ids, changed_files=changed_files)
