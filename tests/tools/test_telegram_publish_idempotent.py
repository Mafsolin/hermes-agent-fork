import asyncio


from tools.telegram_publish_idempotent import publish_once


def test_repeated_publish_returns_original_message_without_sending_twice(tmp_path):
    calls = []

    async def sender(chat_id, video_path, caption):
        calls.append((chat_id, video_path, caption))
        return {"message_id": 4, "chat_id": chat_id}

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video bytes")
    store = tmp_path / "publish.sqlite3"

    first = asyncio.run(
        publish_once("@channel", video, "caption", store_path=store, sender=sender)
    )
    second = asyncio.run(
        publish_once("@channel", video, "caption", store_path=store, sender=sender)
    )

    assert first == {"ok": True, "message_id": 4, "deduplicated": False}
    assert second == {"ok": True, "message_id": 4, "deduplicated": True}
    assert len(calls) == 1


def test_uncertain_send_is_not_retried_automatically(tmp_path):
    calls = 0

    async def uncertain_sender(chat_id, video_path, caption):
        nonlocal calls
        calls += 1
        raise TimeoutError("connection closed after upload")

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video bytes")
    store = tmp_path / "publish.sqlite3"

    first = asyncio.run(
        publish_once("@channel", video, "caption", store_path=store, sender=uncertain_sender)
    )
    second = asyncio.run(
        publish_once("@channel", video, "caption", store_path=store, sender=uncertain_sender)
    )

    assert first["ok"] is False
    assert first["status"] == "uncertain"
    assert second["ok"] is False
    assert second["status"] == "uncertain"
    assert second["deduplicated"] is True
    assert calls == 1
