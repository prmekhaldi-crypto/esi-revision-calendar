"""Command-line generation entry point."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

from icalendar import Calendar

from .config import FEED_URLS, Preferences, parse_start
from .ical_output import build_calendar, validate_calendar_bytes, write_calendar
from .importer import FeedDownloadError, fetch_calendars, filter_attendance, import_attendance
from .scheduler import RevisionEvent, schedule_revision_sessions


def _existing_revision_events(path: Path) -> list[RevisionEvent]:
    if not path.exists():
        return []
    try:
        calendar = Calendar.from_ical(path.read_bytes())
    except Exception:
        return []
    result: list[RevisionEvent] = []
    for component in calendar.walk("VEVENT"):
        start = component.get("DTSTART").dt
        end = component.get("DTEND").dt
        if start.tzinfo is None:
            start = start.replace(tzinfo=Preferences().timezone)
        if end.tzinfo is None:
            end = end.replace(tzinfo=Preferences().timezone)
        summary = str(component.get("SUMMARY", "Revision"))
        description = str(component.get("DESCRIPTION", ""))
        categories = str(component.get("CATEGORIES", ""))
        module = categories.split(",")[-1] if categories else ""
        result.append(
            RevisionEvent(
                uid=str(component.get("UID")),
                start=start,
                end=end,
                summary=summary,
                description=description,
                module=module,
                objective_key="preserved",
            )
        )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("public/revision-calendar.ics"))
    parser.add_argument("--horizon-days", type=int, default=42)
    parser.add_argument("--start", help="ISO datetime in Africa/Algiers; defaults to now")
    parser.add_argument("--keep-previous", action="store_true", help="preserve past events from the output file")
    parser.add_argument("--feed", action="append", dest="feeds", help="override a source feed; repeat twice")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    preferences = Preferences()
    now = parse_start(args.start, preferences.timezone)
    feed_urls = tuple(args.feeds) if args.feeds else FEED_URLS
    if len(feed_urls) != 2:
        print("exactly two --feed values are required", file=sys.stderr)
        return 2
    end = now + timedelta(days=args.horizon_days)
    try:
        calendars = fetch_calendars(feed_urls)
    except FeedDownloadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("The previous output was left untouched.", file=sys.stderr)
        return 1

    attended, excluded = import_attendance(calendars, now - timedelta(days=1), end, preferences.exclusion_rules)
    # Keep the audit output useful in CI logs without writing the source feeds.
    print(f"Imported {len(attended) + len(excluded)} source occurrences; excluded {len(excluded)} attendance occurrences.")
    if excluded:
        names = sorted({event.summary for event in excluded})
        print("Excluded source titles: " + ", ".join(names))

    previous = _existing_revision_events(args.output) if args.keep_previous else []
    events = schedule_revision_sessions(attended, preferences, now, args.horizon_days, previous)
    calendar = build_calendar(events)
    payload = calendar.to_ical()
    errors = validate_calendar_bytes(payload)
    if errors:
        print("ERROR: generated calendar failed validation:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    # Atomic replacement only happens after successful fetch, scheduling, and
    # validation. A temporary file is used in the same directory for rename.
    temp = args.output.with_suffix(args.output.suffix + ".tmp")
    write_calendar(calendar, temp)
    temp.replace(args.output)
    print(f"Wrote {len(events)} revision events to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
