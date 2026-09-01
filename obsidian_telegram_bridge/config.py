from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class BridgeConfig:
    telegram_token: str
    obsidian_vault: Path
    notes_dir: Path
    state_db: Path
    allowed_user_ids: frozenset[int] | None = None
    bot_username: str | None = None
    create_missing_notes_dir: bool = True

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        vault = Path(os.getenv("OBSIDIAN_VAULT_PATH", "~/Documents/Obsidian Vault/Память Артема")).expanduser().resolve()
        notes_dir_name = os.getenv("OBSIDIAN_NOTES_DIR", "Понятия")
        notes_dir = (vault / notes_dir_name).resolve()
        state_db = Path(os.getenv("OBSIDIAN_BRIDGE_DB", str(vault / ".telegram_business_memory.sqlite3"))).expanduser().resolve()
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

        allowed_raw = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").strip()
        allowed: frozenset[int] | None = None
        if allowed_raw:
            allowed = frozenset(int(x.strip()) for x in allowed_raw.split(",") if x.strip())

        return cls(
            telegram_token=token,
            obsidian_vault=vault,
            notes_dir=notes_dir,
            state_db=state_db,
            allowed_user_ids=allowed,
            bot_username=os.getenv("TELEGRAM_BOT_USERNAME") or None,
            create_missing_notes_dir=os.getenv("OBSIDIAN_CREATE_NOTES_DIR", "1").lower() not in {"0", "false", "no"},
        )

    def ensure_paths(self) -> None:
        self.obsidian_vault.mkdir(parents=True, exist_ok=True)
        if self.create_missing_notes_dir:
            self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.state_db.parent.mkdir(parents=True, exist_ok=True)
