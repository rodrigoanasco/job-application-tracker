from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import AppConfig
from .email_client import (
    ImapEmailClient,
    email_record_from_bytes,
    email_record_from_text,
    filter_relevant_emails,
)
from .extractor import JobUpdateExtractor
from .state import TrackerState
from .storage import ExcelTracker


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        return init_project()
    if args.command == "sync":
        return sync(args)
    if args.command == "analyze-file":
        return analyze_file(args)

    parser.print_help()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local-first job application tracker.")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="Create .env from .env.example and initialize the workbook.")

    sync_parser = subparsers.add_parser("sync", help="Read recent mailbox updates into Excel.")
    sync_parser.add_argument("--env", default=".env", help="Path to the env file. Default: .env")
    sync_parser.add_argument("--since", help="Only read emails since YYYY-MM-DD.")
    sync_parser.add_argument("--limit", type=int, help="Maximum emails to fetch from IMAP.")
    sync_parser.add_argument("--dry-run", action="store_true", help="Analyze without writing Excel or state.")
    sync_parser.add_argument("--no-ollama", action="store_true", help="Use deterministic local rules only.")
    sync_parser.add_argument("--include-all", action="store_true", help="Analyze all fetched emails, not just keyword matches.")

    file_parser = subparsers.add_parser("analyze-file", help="Analyze a local .eml or text file.")
    file_parser.add_argument("path", help="Path to .eml or .txt file.")
    file_parser.add_argument("--env", default=".env", help="Path to the env file. Default: .env")
    file_parser.add_argument("--subject", default="Local sample", help="Subject to use for plain text files.")
    file_parser.add_argument("--write", action="store_true", help="Write extracted updates to the Excel workbook.")
    file_parser.add_argument("--no-ollama", action="store_true", help="Use deterministic local rules only.")

    return parser


def init_project() -> int:
    env_path = Path(".env")
    if not env_path.exists():
        shutil.copyfile(".env.example", env_path)
        print("Created .env from .env.example.")
    else:
        print(".env already exists; leaving it untouched.")

    config = AppConfig.load(env_path)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    ExcelTracker(config.output_excel).ensure_exists()
    print(f"Initialized workbook: {config.output_excel}")
    return 0


def sync(args: argparse.Namespace) -> int:
    config = AppConfig.load(args.env)
    if args.no_ollama:
        config = _with_ollama_disabled(config)

    state = TrackerState.load(config.state_file)
    since = _since_datetime(args.since, state, config.lookback_days)
    limit = args.limit if args.limit is not None else config.max_emails

    print(f"Fetching emails since {since.date().isoformat()} from {config.imap_mailbox}...")
    emails = ImapEmailClient(config).fetch_since(since, limit=limit)
    new_emails = [email for email in emails if not state.is_processed(email.message_id)]
    relevant_emails = (
        new_emails
        if args.include_all
        else filter_relevant_emails(new_emails, config.email_keywords, config.email_exclude_keywords)
    )

    print(f"Fetched {len(emails)} emails, {len(new_emails)} new, {len(relevant_emails)} selected for analysis.")
    _print_selected_preview(relevant_emails)

    extractor = JobUpdateExtractor(config)
    updates = []
    selected_ids = {email.message_id for email in relevant_emails}
    for email in relevant_emails:
        extracted = extractor.extract(email)
        updates.extend(extracted)
        print(f"- {email.date.date().isoformat()} | {email.subject[:80]} | {len(extracted)} update(s)")

    if args.dry_run:
        _print_updates(updates)
        print("Dry run complete. Excel and state were not changed.")
        return 0

    added = ExcelTracker(config.output_excel).update(updates)
    for email in new_emails:
        if email.message_id in selected_ids or not args.include_all:
            state.mark_processed(email.message_id)
    state.mark_synced_now()
    state.save(config.state_file)

    print(f"Added {added} new event(s) to {config.output_excel}.")
    print(f"Saved sync state to {config.state_file}.")
    return 0


def analyze_file(args: argparse.Namespace) -> int:
    config = AppConfig.load(args.env)
    if args.no_ollama:
        config = _with_ollama_disabled(config)

    path = Path(args.path)
    if path.suffix.lower() == ".eml":
        email = email_record_from_bytes(path.read_bytes())
    else:
        email = email_record_from_text(path.read_text(encoding="utf-8"), subject=args.subject)

    updates = JobUpdateExtractor(config).extract(email)
    _print_updates(updates)

    if args.write:
        added = ExcelTracker(config.output_excel).update(updates)
        print(f"Added {added} new event(s) to {config.output_excel}.")
    return 0


def _since_datetime(raw_since: str | None, state: TrackerState, lookback_days: int) -> datetime:
    if raw_since:
        return datetime.fromisoformat(raw_since).replace(tzinfo=timezone.utc)
    if state.last_sync_utc:
        return state.last_sync_utc
    return datetime.now(timezone.utc) - timedelta(days=lookback_days)


def _with_ollama_disabled(config: AppConfig) -> AppConfig:
    values = config.__dict__.copy()
    values["use_ollama"] = False
    return AppConfig(**values)


def _print_selected_preview(emails) -> None:
    if not emails:
        return

    print("Selected email preview:")
    for email in emails[:10]:
        print(f"  - {email.date.date().isoformat()} | {email.subject[:100]}")
    if len(emails) > 10:
        print(f"  ... {len(emails) - 10} more")


def _print_updates(updates) -> None:
    if not updates:
        print("No job application updates detected.")
        return

    for update in updates:
        event_date = update.event_date or update.source_date.date()
        print(
            f"{event_date.isoformat()} | {update.company} | {update.role} | "
            f"{update.status} | confidence={update.confidence:.2f}"
        )
        if update.notes:
            print(f"  {update.notes}")


if __name__ == "__main__":
    raise SystemExit(main())
