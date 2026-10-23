"""Standards-compliant iCalendar serialization and validation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event

from .config import TIMEZONE
from .scheduler import RevisionEvent


def build_calendar(events: Iterable[RevisionEvent], generated_at: datetime | None = None) -> Calendar:
    generated_at = generated_at or datetime.now(ZoneInfo("UTC"))
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=ZoneInfo("UTC"))
    calendar = Calendar()
    calendar.add("PRODID", "-//ESI Revision Calendar//revision schedule//EN")
    calendar.add("VERSION", "2.0")
    calendar.add("CALSCALE", "GREGORIAN")
    calendar.add("METHOD", "PUBLISH")
    calendar.add("X-WR-CALNAME", "ESI — Révisions 2CP Groupe 3")
    calendar.add("X-WR-TIMEZONE", "Africa/Algiers")
    calendar.add("X-PUBLISHED-TTL", "PT6H")

    for revision in events:
        event = Event()
        event.add("UID", revision.uid)
        event.add("DTSTAMP", generated_at.astimezone(ZoneInfo("UTC")))
        event.add("DTSTART", revision.start.astimezone(TIMEZONE), parameters={"TZID": "Africa/Algiers"})
        event.add("DTEND", revision.end.astimezone(TIMEZONE), parameters={"TZID": "Africa/Algiers"})
        event.add("SUMMARY", revision.summary)
        event.add("DESCRIPTION", revision.description)
        event.add("CATEGORIES", ["Révision", revision.module])
        event.add("STATUS", "CONFIRMED")
        event.add("TRANSP", "OPAQUE")
        event.add("SEQUENCE", 0)
        calendar.add_component(event)
    return calendar


def serialize_calendar(calendar: Calendar) -> bytes:
    payload = calendar.to_ical()
    if not payload.endswith(b"\r\n"):
        payload += b"\r\n"
    # icalendar emits CRLF and folds long UTF-8 content. Assert rather than
    # silently publish a file that an iPhone might reject.
    if b"\n" in payload.replace(b"\r\n", b""):
        raise ValueError("calendar contains bare LF line endings")
    return payload


def write_calendar(calendar: Calendar, path: str | Path) -> bytes:
    payload = serialize_calendar(calendar)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return payload


def validate_calendar_bytes(payload: bytes) -> list[str]:
    errors: list[str] = []
    if not payload.startswith(b"BEGIN:VCALENDAR\r\n"):
        errors.append("missing BEGIN:VCALENDAR")
    if b"VERSION:2.0\r\n" not in payload:
        errors.append("missing VERSION:2.0")
    if not payload.endswith(b"END:VCALENDAR\r\n"):
        errors.append("missing END:VCALENDAR")
    if b"\n" in payload.replace(b"\r\n", b""):
        errors.append("bare LF line ending")
    try:
        parsed = Calendar.from_ical(payload)
    except Exception as exc:
        errors.append(f"parser rejected output: {exc}")
        return errors
    seen: set[str] = set()
    for component in parsed.walk("VEVENT"):
        uid = str(component.get("UID", ""))
        if not uid:
            errors.append("event without UID")
        elif uid in seen:
            errors.append(f"duplicate UID: {uid}")
        seen.add(uid)
        if component.get("DTSTART") is None or component.get("DTEND") is None:
            errors.append(f"event {uid} lacks DTSTART or DTEND")
    return errors
