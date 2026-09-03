from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path

from .config import BridgeConfig
from .extractor import HermesLLMExtractor, RuleBasedExtractor
from .markdown import ObsidianMemoryWriter
from .processor import BusinessMemoryProcessor
from .storage import BridgeStore


def _today() -> str:
    return datetime.now().astimezone().date().isoformat()


def run_pending(*, use_llm: bool | None = None, dry_run: bool = False, retention_days: int = 14):
    config = BridgeConfig.from_env()
    config.ensure_paths()
    store = BridgeStore(config.state_db)
    writer = ObsidianMemoryWriter(config.obsidian_vault)
    if use_llm is None:
        use_llm = os.getenv("OBSIDIAN_MEMORY_USE_LLM", "1").lower() not in {"0", "false", "no"}
    extractor = HermesLLMExtractor() if use_llm else RuleBasedExtractor()
    return BusinessMemoryProcessor(store, writer, extractor).process_pending(
        today=_today(),
        dry_run=dry_run,
        retention_days=retention_days,
    )


def process_pending(*, use_llm: bool | None = None, dry_run: bool = False, retention_days: int = 14) -> int:
    result = run_pending(use_llm=use_llm, dry_run=dry_run, retention_days=retention_days)
    if result.changed_files:
        prefix = "Будет обновлено файлов" if dry_run else "Обновлено файлов"
        print(f"{prefix}: {len(result.changed_files)}")
        for path in result.changed_files:
            print(Path(path))
    else:
        print("Новых полезных фактов не найдено.")
    return 0


def main(argv: list[str] | None = None) -> int:
    # This standalone helper can be invoked before ``hermes_bootstrap`` has
    # configured UTF-8 stdio on Windows. Keep argparse's own help text on the
    # active console code page; note contents themselves remain UTF-8.
    parser = argparse.ArgumentParser(description="Telegram Business -> Obsidian memory bridge")
    sub = parser.add_subparsers(dest="command", required=True)
    p_process = sub.add_parser("process", help="Process buffered Telegram Business messages into Obsidian memory")
    p_process.add_argument("--no-llm", action="store_true", help="Use the deterministic fallback extractor")
    p_process.add_argument("--dry-run", action="store_true", help="Preview candidate files without writing notes or marking messages processed")
    p_process.add_argument("--retention-days", type=int, default=14, help="Delete processed raw buffer rows older than this many days")
    args = parser.parse_args(argv)
    if args.command == "process":
        return process_pending(use_llm=not args.no_llm, dry_run=args.dry_run, retention_days=args.retention_days)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
