"""Publish one Telegram video+caption without accidental duplicate retries."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Awaitable, Callable, Mapping


Sender = Callable[[str, Path, str], Awaitable[Mapping[str, object]]]


def _fingerprint(chat_id: str, video_path: Path, caption: str) -> str:
    digest = hashlib.sha256()
    digest.update(str(chat_id).encode("utf-8"))
    digest.update(b"\0")
    digest.update(caption.encode("utf-8"))
    digest.update(b"\0")
    with video_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect(store_path: Path) -> sqlite3.Connection:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(store_path, timeout=30)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_publications (
            fingerprint TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            message_id TEXT,
            error TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    return connection


async def publish_once(
    chat_id: str,
    video_path: str | Path,
    caption: str,
    *,
    store_path: str | Path,
    sender: Sender,
    allow_duplicate: bool = False,
) -> dict:
    """Send once and remember the result before a caller can retry.

    An interrupted/ambiguous send stays ``uncertain``.  A later invocation
    refuses to repeat it automatically because Telegram's Bot API has no
    idempotency key and the first upload may already have been published.
    """
    video = Path(video_path)
    if not video.is_file():
        return {"ok": False, "status": "invalid", "error": "video file not found"}
    key = _fingerprint(str(chat_id), video, caption)
    if allow_duplicate:
        key = f"{key}:{uuid.uuid4().hex}"

    now = time.time()
    connection = _connect(Path(store_path))
    try:
        cursor = connection.execute(
            "INSERT OR IGNORE INTO telegram_publications "
            "(fingerprint,status,created_at,updated_at) VALUES (?, 'pending', ?, ?)",
            (key, now, now),
        )
        connection.commit()
        owns_send = cursor.rowcount == 1
        if not owns_send:
            row = connection.execute(
                "SELECT status,message_id,error FROM telegram_publications "
                "WHERE fingerprint=?",
                (key,),
            ).fetchone()
            status, message_id, error = row if row else ("uncertain", None, None)
            if status == "sent" and message_id is not None:
                value = int(message_id) if str(message_id).isdigit() else message_id
                return {"ok": True, "message_id": value, "deduplicated": True}
            return {
                "ok": False,
                "status": "uncertain",
                "deduplicated": True,
                "error": error or "matching publication is pending or had an uncertain result",
            }

        try:
            result = dict(await sender(str(chat_id), video, caption))
            message_id = result.get("message_id")
            if message_id is None:
                raise RuntimeError("Telegram returned no message_id after send")
        except Exception as exc:
            safe_error = f"{type(exc).__name__}: {exc}"[:500]
            connection.execute(
                "UPDATE telegram_publications SET status='uncertain', error=?, updated_at=? "
                "WHERE fingerprint=?",
                (safe_error, time.time(), key),
            )
            connection.commit()
            return {"ok": False, "status": "uncertain", "error": safe_error}

        connection.execute(
            "UPDATE telegram_publications SET status='sent', message_id=?, error=NULL, "
            "updated_at=? WHERE fingerprint=?",
            (str(message_id), time.time(), key),
        )
        connection.commit()
        value = int(message_id) if str(message_id).isdigit() else message_id
        return {"ok": True, "message_id": value, "deduplicated": False}
    finally:
        connection.close()


def _load_telegram_token(env_path: Path) -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if token:
        return token
    if env_path.is_file():
        for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                return line.split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")


def _telegram_sender(token: str) -> Sender:
    async def send(chat_id: str, video_path: Path, caption: str) -> Mapping[str, object]:
        from telegram import Bot

        bot = Bot(token=token)
        with video_path.open("rb") as video:
            message = await bot.send_video(
                chat_id=chat_id,
                video=video,
                caption=caption,
                read_timeout=180,
                write_timeout=180,
                connect_timeout=30,
                pool_timeout=30,
            )
        return {"message_id": message.message_id, "chat_id": message.chat_id}

    return send


def main() -> int:
    hermes_home = Path(os.environ.get("HERMES_HOME", "/home/afsol/.hermes"))
    parser = argparse.ArgumentParser()
    parser.add_argument("--chat-id", required=True)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--caption-file", required=True, type=Path)
    parser.add_argument(
        "--store",
        type=Path,
        default=hermes_home / "state" / "telegram-publications.sqlite3",
    )
    parser.add_argument(
        "--allow-duplicate",
        action="store_true",
        help="Deliberately bypass duplicate protection for this invocation",
    )
    args = parser.parse_args()
    try:
        caption = args.caption_file.read_text(encoding="utf-8")
        token = _load_telegram_token(hermes_home / ".env")
        result = asyncio.run(
            publish_once(
                args.chat_id,
                args.video,
                caption,
                store_path=args.store,
                sender=_telegram_sender(token),
                allow_duplicate=args.allow_duplicate,
            )
        )
    except Exception as exc:
        result = {"ok": False, "status": "invalid", "error": f"{type(exc).__name__}: {exc}"[:500]}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
