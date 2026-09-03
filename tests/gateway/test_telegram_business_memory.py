import asyncio
from types import SimpleNamespace

from gateway.config import Platform, PlatformConfig


class FakeBusinessStore:
    def __init__(self):
        self.messages = []
        self.deleted = []

    def add_business_message(self, **kwargs):
        self.messages.append(kwargs)
        return len(self.messages)

    def mark_deleted_business_messages(self, **kwargs):
        self.deleted.append(kwargs)
        return len(kwargs.get("message_ids") or [])


def _make_adapter(*, owner_ids="732084541", auto_reply_user_ids=None):
    from gateway.platforms.telegram import TelegramAdapter

    adapter = object.__new__(TelegramAdapter)
    adapter.platform = Platform.TELEGRAM
    adapter.config = PlatformConfig(enabled=True, token="***", extra={})
    adapter._business_memory_store = FakeBusinessStore()
    adapter._business_owner_ids_override = owner_ids
    if auto_reply_user_ids is not None:
        adapter._business_auto_reply_user_ids_override = auto_reply_user_ids
    return adapter


def _business_message(*, text="Давай завтра созвонимся", sender_id=732084541, message_id=10):
    return SimpleNamespace(
        text=text,
        caption=None,
        business_connection_id="bc-1",
        message_id=message_id,
        date=SimpleNamespace(isoformat=lambda: "2026-04-28T10:00:00+03:00"),
        chat=SimpleNamespace(id=123, title="Иван"),
        from_user=SimpleNamespace(id=sender_id, full_name="Артём" if sender_id == 732084541 else "Иван", username=None),
    )


def test_business_message_is_buffered_with_direction_and_chat_title():
    adapter = _make_adapter(owner_ids="732084541")
    update = SimpleNamespace(business_message=_business_message(sender_id=999), edited_business_message=None)

    asyncio.run(adapter._handle_business_update(update, None))

    assert len(adapter._business_memory_store.messages) == 1
    stored = adapter._business_memory_store.messages[0]
    assert stored["business_connection_id"] == "bc-1"
    assert stored["chat_id"] == 123
    assert stored["sender_name"] == "Иван"
    assert stored["direction"] == "incoming"
    assert stored["chat_title"] == "Иван"
    assert stored["is_edited"] is False


def test_edited_business_message_is_buffered_as_edited_outgoing_message():
    adapter = _make_adapter(owner_ids="732084541")
    update = SimpleNamespace(
        business_message=None,
        edited_business_message=_business_message(text="Исправил: завтра в 15:00", sender_id=732084541),
    )

    asyncio.run(adapter._handle_business_update(update, None))

    stored = adapter._business_memory_store.messages[0]
    assert stored["direction"] == "outgoing"
    assert stored["is_edited"] is True
    assert stored["text"] == "Исправил: завтра в 15:00"


def test_empty_business_message_is_ignored():
    adapter = _make_adapter()
    update = SimpleNamespace(business_message=_business_message(text="   "), edited_business_message=None)

    asyncio.run(adapter._handle_business_update(update, None))

    assert adapter._business_memory_store.messages == []


def test_business_auto_reply_disabled_by_default_does_not_call_agent(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BUSINESS_AUTO_REPLY_ENABLED", raising=False)
    monkeypatch.setenv("TELEGRAM_BUSINESS_AUTO_REPLY_USER_IDS", "999")
    adapter = _make_adapter()
    calls = []

    async def fake_handle_message(event):
        calls.append(event)

    adapter.handle_message = fake_handle_message
    update = SimpleNamespace(business_message=_business_message(sender_id=999), edited_business_message=None)

    asyncio.run(adapter._handle_business_update(update, None))

    assert len(adapter._business_memory_store.messages) == 1
    assert calls == []


def test_incoming_business_message_auto_replies_when_master_switch_enabled(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BUSINESS_AUTO_REPLY_ENABLED", "true")
    monkeypatch.delenv("TELEGRAM_BUSINESS_AUTO_REPLY_USER_IDS", raising=False)
    adapter = _make_adapter()
    calls = []

    async def fake_handle_message(event):
        calls.append(event)

    adapter.handle_message = fake_handle_message
    update = SimpleNamespace(business_message=_business_message(sender_id=999), edited_business_message=None)

    asyncio.run(adapter._handle_business_update(update, None))

    assert len(adapter._business_memory_store.messages) == 1
    assert len(calls) == 1
    event = calls[0]
    assert event.text == "Давай завтра созвонимся"
    assert event.internal is True
    assert event.source.business_connection_id == "bc-1"
    assert event.source.chat_id == "123"
    assert event.source.user_id == "999"


def test_business_auto_reply_allowlist_blocks_other_users(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BUSINESS_AUTO_REPLY_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BUSINESS_AUTO_REPLY_USER_IDS", "888")
    adapter = _make_adapter()
    calls = []

    async def fake_handle_message(event):
        calls.append(event)

    adapter.handle_message = fake_handle_message
    update = SimpleNamespace(business_message=_business_message(sender_id=999), edited_business_message=None)

    asyncio.run(adapter._handle_business_update(update, None))

    assert len(adapter._business_memory_store.messages) == 1
    assert calls == []


def test_session_source_roundtrip_preserves_business_connection_id():
    from gateway.config import Platform
    from gateway.session import SessionSource

    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="123",
        user_id="999",
        business_connection_id="bc-1",
    )

    restored = SessionSource.from_dict(source.to_dict())

    assert restored.business_connection_id == "bc-1"


def test_gateway_runner_reply_metadata_includes_business_connection_id():
    from gateway.config import Platform
    from gateway.run import GatewayRunner
    from gateway.session import SessionSource

    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="123",
        thread_id="topic-1",
        business_connection_id="bc-1",
    )

    assert GatewayRunner._reply_metadata_for_source(source) == {
        "thread_id": "topic-1",
        "business_connection_id": "bc-1",
    }
    assert GatewayRunner._reply_metadata_for_source(source, thread_id="override") == {
        "thread_id": "override",
        "business_connection_id": "bc-1",
    }


def test_business_send_metadata_uses_business_api_and_disables_drafts():
    from plugins.platforms.telegram.adapter import TelegramAdapter

    metadata = {"business_connection_id": "bc-1"}
    assert TelegramAdapter._thread_kwargs_for_send("123", None, metadata) == {
        "message_thread_id": None,
        "business_connection_id": "bc-1",
    }

    adapter = object.__new__(TelegramAdapter)
    adapter._bot = SimpleNamespace(send_message_draft=object())
    assert adapter.supports_draft_streaming("dm", metadata) is False
    assert adapter._thread_kwargs_for_draft("123", metadata) == {}


def test_deleted_business_messages_mark_existing_rows_deleted():
    adapter = _make_adapter()
    deleted = SimpleNamespace(
        business_connection_id="bc-1",
        chat=SimpleNamespace(id=123),
        message_ids=[10, 11],
    )
    update = SimpleNamespace(
        business_message=None,
        edited_business_message=None,
        deleted_business_messages=deleted,
    )

    asyncio.run(adapter._handle_business_update(update, None))

    assert adapter._business_memory_store.deleted == [
        {
            "business_connection_id": "bc-1",
            "chat_id": 123,
            "message_ids": [10, 11],
            "deleted_at": "CURRENT_TIMESTAMP",
        }
    ]
