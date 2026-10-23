#!/usr/bin/env python3
"""Print a compact preview of the generated feed."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from icalendar import Calendar


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    timezone = ZoneInfo("Africa/Algiers")
    calendar = Calendar.from_ical(args.path.read_bytes())
    now = datetime.now(timezone)
    end = now + timedelta(days=args.days)
    events = []
    for component in calendar.walk("VEVENT"):
        start = component.get("DTSTART").dt.astimezone(timezone)
        end_time = component.get("DTEND").dt.astimezone(timezone)
        if start < end and end_time > now:
            events.append((start, end_time, str(component.get("SUMMARY"))))
    for start, end_time, summary in sorted(events):
        print(f"{start:%a %Y-%m-%d %H:%M}–{end_time:%H:%M}  {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
