from __future__ import annotations

import json
from pathlib import Path

from obsidian_telegram_bridge.extractor import HermesLLMExtractor
from obsidian_telegram_bridge.markdown import ObsidianMemoryWriter
from obsidian_telegram_bridge.processor import BusinessMemoryProcessor
from obsidian_telegram_bridge.storage import BridgeStore


def test_llm_extractor_defaults_to_spark_model(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_MEMORY_LLM_MODEL", raising=False)
    extractor = HermesLLMExtractor()
    assert extractor.model == "gpt-5.3-codex-spark"


def test_bridge_store_deduplicates_and_marks_business_messages_processed(tmp_path):
    store = BridgeStore(tmp_path / "bridge.sqlite3")

    first_id = store.add_business_message(
        business_connection_id="bc-1",
        chat_id=123,
        message_id=10,
        sender_id=1,
        sender_name="Артём",
        direction="outgoing",
        text="Давай завтра в 15:00 созвонимся по сайту",
        created_at="2026-04-28T10:00:00+03:00",
        chat_title="Иван",
    )
    duplicate_id = store.add_business_message(
        business_connection_id="bc-1",
        chat_id=123,
        message_id=10,
        sender_id=1,
        sender_name="Артём",
        direction="outgoing",
        text="Давай завтра в 15:00 созвонимся по сайту",
        created_at="2026-04-28T10:00:00+03:00",
        chat_title="Иван",
    )

    assert duplicate_id == first_id
    pending = store.pending_messages(limit=10)
    assert len(pending) == 1
    assert pending[0].text == "Давай завтра в 15:00 созвонимся по сайту"
    assert pending[0].chat_title == "Иван"
    assert pending[0].importance_status == "pending"

    store.mark_processed([first_id])
    assert store.pending_messages(limit=10) == []


def test_bridge_store_tracks_edited_deleted_and_retention(tmp_path):
    store = BridgeStore(tmp_path / "bridge.sqlite3")
    msg_id = store.add_business_message(
        business_connection_id="bc-1",
        chat_id=123,
        message_id=10,
        sender_id=1,
        sender_name="Артём",
        direction="outgoing",
        text="Первый текст",
        created_at="2026-04-28T10:00:00+03:00",
        chat_title="Иван",
    )

    edited_id = store.add_business_message(
        business_connection_id="bc-1",
        chat_id=123,
        message_id=10,
        sender_id=1,
        sender_name="Артём",
        direction="outgoing",
        text="Исправленный текст",
        created_at="2026-04-28T10:00:00+03:00",
        chat_title="Иван",
        is_edited=True,
    )

    assert edited_id == msg_id
    pending = store.pending_messages(limit=10)
    assert pending[0].text == "Исправленный текст"
    assert pending[0].is_edited is True

    assert store.mark_deleted_business_messages(
        business_connection_id="bc-1",
        chat_id=123,
        message_ids=[10],
        deleted_at="2026-04-28T11:00:00+03:00",
    ) == 1
    deleted = store.pending_messages(limit=10)[0]
    assert deleted.deleted_at == "2026-04-28T11:00:00+03:00"
    assert deleted.importance_status == "deleted"

    store.mark_processed([msg_id], processed_at="2026-04-01T00:00:00")
    assert store.purge_processed_older_than(days=14, now="2026-04-28T00:00:00") == 1
    assert store.pending_messages(limit=10) == []


def test_obsidian_memory_writer_creates_russian_user_facing_notes(tmp_path):
    writer = ObsidianMemoryWriter(tmp_path)

    changed = writer.apply_memory_items(
        {
            "people": [
                {"name": "Иван", "facts": ["Иван занимается макетом сайта."]},
            ],
            "projects": [
                {"name": "Сайт для друзей", "updates": ["Нужно обсудить макет с Иваном."]},
            ],
            "agreements": [
                {
                    "title": "Созвон с Иваном по сайту",
                    "date": "2026-04-29 15:00",
                    "participants": ["Артём", "Иван"],
                    "summary": "Обсудить макет сайта.",
                }
            ],
            "tasks": [
                {"title": "Проверить макет сайта", "summary": "Артёму нужно посмотреть макет от Ивана."},
            ],
            "places": [
                {"name": "Офис Ивана", "facts": ["Встреча по проекту проходит в офисе Ивана."]},
            ],
            "review": [
                {"title": "Возможно важно про пятницу", "summary": "Иван упомянул поездку в Москву в пятницу."},
            ],
        },
        source="Telegram Business",
        today="2026-04-28",
    )

    assert tmp_path.joinpath("Люди", "Иван.md").exists()
    assert tmp_path.joinpath("Проекты", "Сайт для друзей.md").exists()
    assert tmp_path.joinpath("Договорённости", "2026-04-29 — Созвон с Иваном по сайту.md").exists()
    assert tmp_path.joinpath("Tasks", "2026-04-28 — Проверить макет сайта.md").exists()
    assert tmp_path.joinpath("Места", "Офис Ивана.md").exists()
    assert tmp_path.joinpath("На разбор", "2026-04-28 Telegram Business.md").exists()
    assert tmp_path.joinpath("Индекс памяти.md").exists()
    assert tmp_path.joinpath("Журнал изменений.md").exists()
    assert all("Трифена" not in path.name for path in changed)
    assert "Иван занимается макетом сайта" in tmp_path.joinpath("Люди", "Иван.md").read_text(encoding="utf-8")

    changed_again = writer.apply_memory_items(
        {
            "people": [{"name": "Иван", "facts": ["Иван занимается макетом сайта."]}],
            "projects": [],
            "agreements": [],
            "tasks": [],
            "places": [],
            "review": [],
        },
        source="Telegram Business",
        today="2026-04-28",
    )
    assert tmp_path.joinpath("Люди", "Иван.md").read_text(encoding="utf-8").count("Иван занимается макетом сайта") == 1
    assert changed_again == []


def test_business_memory_processor_groups_messages_extracts_writes_and_marks_processed(tmp_path):
    store = BridgeStore(tmp_path / "bridge.sqlite3")
    vault = tmp_path / "vault"
    writer = ObsidianMemoryWriter(vault)

    first = store.add_business_message(
        business_connection_id="bc-1",
        chat_id=777,
        message_id=1,
        sender_id=10,
        sender_name="Иван",
        direction="incoming",
        text="Я сегодня вечером пришлю макет сайта",
        created_at="2026-04-28T10:00:00+03:00",
        chat_title="Иван",
    )
    second = store.add_business_message(
        business_connection_id="bc-1",
        chat_id=777,
        message_id=2,
        sender_id=20,
        sender_name="Артём",
        direction="outgoing",
        text="Ок, завтра в 15:00 созвонимся",
        created_at="2026-04-28T10:01:00+03:00",
        chat_title="Иван",
    )

    seen_batches = []

    def fake_extractor(messages):
        seen_batches.append(messages)
        return {
            "people": [{"name": "Иван", "facts": ["Иван обещал прислать макет сайта вечером."]}],
            "projects": [{"name": "Сайт", "updates": ["Запланирован созвон завтра в 15:00."]}],
            "agreements": [],
        }

    result = BusinessMemoryProcessor(store, writer, fake_extractor).process_pending(today="2026-04-28")

    assert result.processed_message_ids == [first, second]
    assert len(seen_batches) == 1
    assert [m.text for m in seen_batches[0]] == [
        "Я сегодня вечером пришлю макет сайта",
        "Ок, завтра в 15:00 созвонимся",
    ]
    assert store.pending_messages(limit=10) == []
    assert vault.joinpath("Люди", "Иван.md").exists()
    assert result.changed_files


def test_business_memory_processor_keeps_messages_pending_when_writer_fails(tmp_path):
    store = BridgeStore(tmp_path / "bridge.sqlite3")
    msg_id = store.add_business_message(
        business_connection_id="bc-1",
        chat_id=777,
        message_id=1,
        sender_id=10,
        sender_name="Иван",
        direction="incoming",
        text="Я сегодня вечером пришлю макет сайта",
        created_at="2026-04-28T10:00:00+03:00",
        chat_title="Иван",
    )

    class FailingWriter:
        def apply_memory_items(self, *_args, **_kwargs):
            raise RuntimeError("disk is unavailable")

    def fake_extractor(_messages):
        return {"people": [{"name": "Иван", "facts": ["Иван обещал прислать макет."]}]}

    processor = BusinessMemoryProcessor(store, FailingWriter(), fake_extractor)

    try:
        processor.process_pending(today="2026-04-28")
    except RuntimeError as exc:
        assert "disk is unavailable" in str(exc)
    else:
        raise AssertionError("expected writer failure")

    assert [m.id for m in store.pending_messages(limit=10)] == [msg_id]
