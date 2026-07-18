#!/usr/bin/env python3
"""
main.py
-------
CLI entry point for the CMS Anesthesiology Data Automation project.

Usage:
    python main.py init-db     Create/verify the SQLite schema only
    python main.py list        Show files discovered on the CMS page (no download)
    python main.py check       Compare discovered files against what's already in SQLite
    python main.py sync        Run the full pipeline once: download, parse, insert, email
    python main.py schedule    Run continuously using the in-process scheduler (cron preferred)
"""

import argparse
import logging
import os
import sys

from config import settings


def setup_logging() -> None:
    os.makedirs(settings.LOG_DIR, exist_ok=True)
    log_file = os.path.join(settings.LOG_DIR, "pipeline.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )


def cmd_init_db(args) -> None:
    from database import db_manager
    db_manager.init_db()
    print(f"Database ready at {settings.DB_PATH}")


def cmd_list(args) -> None:
    """Dry-run: show what the scraper finds on the CMS page, without downloading anything."""
    from scraper.scraper import get_available_files

    discovered = get_available_files()
    if not discovered:
        print("No Conversion Factor / CPT Base Unit files found on the page.")
        return

    print(f"{'DATASET':<20} {'YEAR':<6} {'LINK TEXT':<40} URL")
    print("-" * 100)
    for f in discovered:
        print(f"{f.dataset:<20} {str(f.year):<6} {f.link_text[:38]:<40} {f.url}")


def cmd_check(args) -> None:
    """Compare what's on the site against what's already recorded in SQLite."""
    from database import db_manager
    from scraper.scraper import get_available_files

    db_manager.init_db()
    discovered = get_available_files()

    if not discovered:
        print("No files found on the page to check.")
        return

    print(f"{'DATASET':<20} {'YEAR':<6} STATUS")
    print("-" * 50)
    for f in discovered:
        if f.year is None:
            print(f"{f.dataset:<20} {'?':<6} year could not be determined")
            continue
        already_done = db_manager.year_already_processed(f.dataset, f.year)
        status = "already in SQLite" if already_done else "NEW - not yet processed"
        print(f"{f.dataset:<20} {f.year:<6} {status}")


def cmd_sync(args) -> None:
    """Full run: scrape -> compare -> download -> parse -> insert -> email."""
    from pipeline.pipeline import run_pipeline
    run_pipeline()


def cmd_schedule(args) -> None:
    from pipeline.scheduler import run_forever
    run_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="CMS Anesthesiology Data Automation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Create/verify the SQLite schema only").set_defaults(func=cmd_init_db)
    subparsers.add_parser("list", help="Show files discovered on the CMS page (no download)").set_defaults(func=cmd_list)
    subparsers.add_parser("check", help="Compare discovered files against what's already in SQLite").set_defaults(func=cmd_check)
    subparsers.add_parser("sync", help="Run the full pipeline once").set_defaults(func=cmd_sync)
    subparsers.add_parser("schedule", help="Run continuously (in-process scheduler)").set_defaults(func=cmd_schedule)

    args = parser.parse_args()
    setup_logging()
    args.func(args)


if __name__ == "__main__":
    main()
