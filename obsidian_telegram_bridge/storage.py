from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Iterable


@dataclass(frozen=True)
class BusinessMessage:
    id: int
    business_connection_id: str
    chat_id: int
    message_id: int
    sender_id: int | None
    sender_name: str | None
    chat_title: str | None
    direction: str
    text: str
    created_at: str
    processed_at: str | None = None
    importance_status: str = "pending"
    is_edited: bool = False
    deleted_at: str | None = None


class BridgeStore:
    """SQLite buffer for Telegram Business messages before memory extraction."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_business_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    business_connection_id TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    sender_id INTEGER,
                    sender_name TEXT,
                    chat_title TEXT,
                    direction TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    processed_at TEXT,
                    importance_status TEXT NOT NULL DEFAULT 'pending',
                    is_edited INTEGER NOT NULL DEFAULT 0,
                    deleted_at TEXT,
                    UNIQUE(business_connection_id, chat_id, message_id)
                )
                """
            )
            self._ensure_column(conn, "chat_title", "TEXT")
            self._ensure_column(conn, "importance_status", "TEXT NOT NULL DEFAULT 'pending'")
            self._ensure_column(conn, "is_edited", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "deleted_at", "TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tbm_pending ON telegram_business_messages(processed_at, chat_id, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tbm_deleted ON telegram_business_messages(deleted_at)"
            )

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, column: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(telegram_business_messages)")}
        if column not in columns:
            conn.execute(f"ALTER TABLE telegram_business_messages ADD COLUMN {column} {definition}")

    def add_business_message(
        self,
        *,
        business_connection_id: str,
        chat_id: int,
        message_id: int,
        sender_id: int | None,
        sender_name: str | None,
        chat_title: str | None = None,
        direction: str,
        text: str,
        created_at: str,
        is_edited: bool = False,
        importance_status: str = "pending",
    ) -> int:
        text = (text or "").strip()
        if not text:
            raise ValueError("text is required")
        importance_status = (importance_status or "pending").strip() or "pending"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO telegram_business_messages (
                    business_connection_id, chat_id, message_id, sender_id,
                    sender_name, chat_title, direction, text, created_at,
                    importance_status, is_edited
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    business_connection_id,
                    chat_id,
                    message_id,
                    sender_id,
                    sender_name,
                    chat_title,
                    direction,
                    text,
                    created_at,
                    importance_status,
                    1 if is_edited else 0,
                ),
            )
            if is_edited:
                conn.execute(
                    """
                    UPDATE telegram_business_messages
                    SET sender_id = ?, sender_name = ?, chat_title = ?, direction = ?,
                        text = ?, created_at = ?, is_edited = 1,
                        importance_status = CASE
                            WHEN importance_status = 'deleted' THEN importance_status
                            ELSE ?
                        END
                    WHERE business_connection_id = ? AND chat_id = ? AND message_id = ?
                    """,
                    (
                        sender_id,
                        sender_name,
                        chat_title,
                        direction,
                        text,
                        created_at,
                        importance_status,
                        business_connection_id,
                        chat_id,
                        message_id,
                    ),
                )
            row = conn.execute(
                """
                SELECT id FROM telegram_business_messages
                WHERE business_connection_id = ? AND chat_id = ? AND message_id = ?
                """,
                (business_connection_id, chat_id, message_id),
            ).fetchone()
            return int(row["id"])

    def mark_deleted_business_messages(
        self,
        *,
        business_connection_id: str,
        chat_id: int,
        message_ids: Iterable[int],
        deleted_at: str = "CURRENT_TIMESTAMP",
    ) -> int:
        ids = [int(message_id) for message_id in message_ids]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            if deleted_at == "CURRENT_TIMESTAMP":
                cursor = conn.execute(
                    f"""
                    UPDATE telegram_business_messages
                    SET deleted_at = CURRENT_TIMESTAMP, importance_status = 'deleted'
                    WHERE business_connection_id = ? AND chat_id = ? AND message_id IN ({placeholders})
                    """,
                    [business_connection_id, chat_id, *ids],
                )
            else:
                cursor = conn.execute(
                    f"""
                    UPDATE telegram_business_messages
                    SET deleted_at = ?, importance_status = 'deleted'
                    WHERE business_connection_id = ? AND chat_id = ? AND message_id IN ({placeholders})
                    """,
                    [deleted_at, business_connection_id, chat_id, *ids],
                )
            return int(cursor.rowcount or 0)

    def pending_messages(self, *, limit: int = 500) -> list[BusinessMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM telegram_business_messages
                WHERE processed_at IS NULL
                ORDER BY chat_id, created_at, id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def mark_processed(self, ids: Iterable[int], *, processed_at: str | None = None) -> None:
        ids = list(ids)
        if not ids:
            return
        processed_at = processed_at or "CURRENT_TIMESTAMP"
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            if processed_at == "CURRENT_TIMESTAMP":
                conn.execute(
                    f"UPDATE telegram_business_messages SET processed_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
                    ids,
                )
            else:
                conn.execute(
                    f"UPDATE telegram_business_messages SET processed_at = ? WHERE id IN ({placeholders})",
                    [processed_at, *ids],
                )

    def purge_processed_older_than(self, *, days: int = 14, now: str | None = None) -> int:
        if days <= 0:
            return 0
        if now:
            try:
                now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
            except ValueError:
                now_dt = datetime.now(timezone.utc)
        else:
            now_dt = datetime.now(timezone.utc)
        cutoff = (now_dt - timedelta(days=days)).replace(tzinfo=None).isoformat(timespec="seconds")
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM telegram_business_messages WHERE processed_at IS NOT NULL AND processed_at < ?",
                (cutoff,),
            )
            return int(cursor.rowcount or 0)

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> BusinessMessage:
        return BusinessMessage(
            id=int(row["id"]),
            business_connection_id=str(row["business_connection_id"]),
            chat_id=int(row["chat_id"]),
            message_id=int(row["message_id"]),
            sender_id=int(row["sender_id"]) if row["sender_id"] is not None else None,
            sender_name=row["sender_name"],
            chat_title=row["chat_title"],
            direction=str(row["direction"]),
            text=str(row["text"]),
            created_at=str(row["created_at"]),
            processed_at=row["processed_at"],
            importance_status=str(row["importance_status"] or "pending"),
            is_edited=bool(row["is_edited"]),
            deleted_at=row["deleted_at"],
        )
