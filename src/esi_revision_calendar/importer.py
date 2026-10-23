"""Download, merge, expand, and filter source iCalendar feeds."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from email.utils import format_datetime
from typing import Iterable, Iterator, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr
from icalendar import Calendar, Event

from .config import ExclusionRule, TIMEZONE


class FeedDownloadError(RuntimeError):
    """Raised when a source feed cannot be downloaded or parsed."""


@dataclass(frozen=True)
class SourceEvent:
    uid: str
    start: datetime
    end: datetime
    summary: str
    source_calendar: str
    recurring: bool = False
    all_day: bool = False
    source_uid: str | None = None


def download_feed(url: str, timeout: int = 30) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "text/calendar, text/plain;q=0.9, */*;q=0.1",
            "User-Agent": "esi-revision-calendar/0.1 (+https://github.com/)",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise FeedDownloadError(f"could not download {url}: {exc}") from exc
    if not payload.strip():
        raise FeedDownloadError(f"empty iCalendar response from {url}")
    return payload


def parse_feed(payload: bytes | str) -> Calendar:
    try:
        calendar = Calendar.from_ical(payload)
    except Exception as exc:  # icalendar exposes several parser exceptions
        raise FeedDownloadError(f"invalid iCalendar feed: {exc}") from exc
    if calendar.get("VERSION") != "2.0":
        raise FeedDownloadError("source feed is not iCalendar VERSION:2.0")
    return calendar


def fetch_calendars(urls: Sequence[str]) -> list[Calendar]:
    return [parse_feed(download_feed(url)) for url in urls]


def _text(value: object | None) -> str:
    if value is None:
        return ""
    if hasattr(value, "to_ical"):
        try:
            return value.to_ical().decode("utf-8")
        except (UnicodeDecodeError, AttributeError):
            pass
    return str(value)


def _prop_datetime(component: Event, name: str) -> datetime | date | None:
    prop = component.get(name)
    return prop.dt if prop is not None else None


def _as_local(value: datetime | date, timezone: ZoneInfo = TIMEZONE) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone)
        return value.astimezone(timezone)
    return datetime.combine(value, time.min, tzinfo=timezone)


def _duration(component: Event, timezone: ZoneInfo = TIMEZONE) -> timedelta:
    start_value = _prop_datetime(component, "DTSTART")
    start = _as_local(start_value, timezone) if start_value is not None else None
    end_value = _prop_datetime(component, "DTEND")
    if end_value is not None and start is not None:
        end = _as_local(end_value, timezone)
        return max(end - start, timedelta(minutes=1))
    duration = component.get("DURATION")
    if duration is not None:
        return duration.dt
    return timedelta(days=1) if component.get("DTSTART").params.get("VALUE") == "DATE" else timedelta(hours=1)


def _sort_key(component: Event) -> tuple[int, datetime, str]:
    sequence = int(_text(component.get("SEQUENCE")) or 0)
    modified_value = _prop_datetime(component, "LAST-MODIFIED") or _prop_datetime(component, "DTSTAMP")
    if isinstance(modified_value, date) and not isinstance(modified_value, datetime):
        modified = datetime.combine(modified_value, time.min, tzinfo=TIMEZONE)
    elif isinstance(modified_value, datetime):
        modified = _as_local(modified_value)
    else:
        modified = datetime.min.replace(tzinfo=TIMEZONE)
    return sequence, modified, _text(component.get("DTSTAMP"))


def _recurrence_key(value: datetime | date | None, timezone: ZoneInfo = TIMEZONE) -> str | None:
    if value is None:
        return None
    if hasattr(value, "dt"):
        value = value.dt
    if isinstance(value, datetime):
        local = _as_local(value, timezone)
        return local.replace(tzinfo=None).isoformat()
    return datetime.combine(value, time.min).isoformat()


def merge_components(calendars: Sequence[Calendar]) -> list[Event]:
    """Merge component updates while retaining masters and exceptions.

    A recurrence exception is keyed by UID plus RECURRENCE-ID. Thus an
    exception cannot overwrite its series master, and a duplicate copy of an
    event in both feeds is reduced to the latest version.
    """

    chosen: dict[tuple[str, str | None], Event] = {}
    for calendar in calendars:
        for component in calendar.walk("VEVENT"):
            uid = _text(component.get("UID"))
            if not uid:
                continue
            recurrence_id = _recurrence_key(_prop_datetime(component, "RECURRENCE-ID"))
            key = (uid, recurrence_id)
            previous = chosen.get(key)
            if previous is None or _sort_key(component) >= _sort_key(previous):
                chosen[key] = component
    return sorted(chosen.values(), key=lambda item: (_text(item.get("UID")), _recurrence_key(_prop_datetime(item, "RECURRENCE-ID")) or ""))


def _rrule_text(component: Event) -> str | None:
    rule = component.get("RRULE")
    if rule is None:
        return None
    raw = rule.to_ical().decode("utf-8")
    # Expand in local wall-clock time. A UTC UNTIL is converted to Algiers
    # wall time so dateutil does not compare aware and naive datetimes.
    parts: list[str] = []
    for part in raw.split(";"):
        if part.upper().startswith("UNTIL="):
            key, value = part.split("=", 1)
            if re.fullmatch(r"\d{8}", value):
                value = f"{value}T235959"
            elif value.endswith("Z") and len(value) == 16:
                until_utc = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=ZoneInfo("UTC"))
                value = until_utc.astimezone(TIMEZONE).strftime("%Y%m%dT%H%M%S")
            else:
                value = value.rstrip("Z")
            part = f"{key}={value}"
        parts.append(part)
    return ";".join(parts)


def _exdates(component: Event) -> set[str]:
    excluded: set[str] = set()
    for name, prop in component.property_items():
        if name != "EXDATE":
            continue
        values = prop.dts if hasattr(prop, "dts") else [prop.dt]
        excluded.update(key for value in values if (key := _recurrence_key(value)) is not None)
    return excluded


def _components_for_uid(components: Sequence[Event]) -> dict[str, list[Event]]:
    grouped: dict[str, list[Event]] = {}
    for component in components:
        grouped.setdefault(_text(component.get("UID")), []).append(component)
    return grouped


def _make_source_event(
    component: Event,
    start: datetime,
    end: datetime,
    calendar_name: str,
    recurring: bool,
) -> SourceEvent | None:
    if _text(component.get("STATUS")).upper() == "CANCELLED":
        return None
    summary = _text(component.get("SUMMARY")) or "University class"
    return SourceEvent(
        uid=_text(component.get("UID")),
        source_uid=_text(component.get("UID")),
        start=start,
        end=end,
        summary=summary,
        source_calendar=calendar_name,
        recurring=recurring,
        all_day=component.get("DTSTART").params.get("VALUE") == "DATE",
    )


def _expand_uid_group(
    uid_components: Sequence[Event],
    window_start: datetime,
    window_end: datetime,
    calendar_name: str,
) -> Iterator[SourceEvent]:
    masters = [component for component in uid_components if component.get("RECURRENCE-ID") is None]
    master = max(masters, key=_sort_key) if masters else None
    overrides = {
        _recurrence_key(_prop_datetime(component, "RECURRENCE-ID")): component
        for component in uid_components
        if component.get("RECURRENCE-ID") is not None
    }
    if master is None:
        for component in uid_components:
            value = _prop_datetime(component, "DTSTART")
            if value is None:
                continue
            start = _as_local(value)
            end = start + _duration(component)
            if start < window_end and end > window_start:
                result = _make_source_event(component, start, end, calendar_name, recurring=False)
                if result:
                    yield result
        return

    start_value = _prop_datetime(master, "DTSTART")
    if start_value is None:
        return
    master_start = _as_local(start_value)
    duration = _duration(master)
    recurring = master.get("RRULE") is not None or bool(overrides)
    if _text(master.get("STATUS")).upper() == "CANCELLED":
        return

    rule_text = _rrule_text(master)
    if rule_text:
        try:
            rule = rrulestr(rule_text, dtstart=master_start.replace(tzinfo=None))
            candidate_starts = rule.between(
                (window_start - duration).replace(tzinfo=None),
                window_end.replace(tzinfo=None),
                inc=True,
            )
        except (ValueError, TypeError, OverflowError):
            # A malformed recurrence must not make the whole calendar empty.
            candidate_starts = [master_start.replace(tzinfo=None)]
    else:
        candidate_starts = [master_start.replace(tzinfo=None)]

    excluded = _exdates(master)
    for candidate in candidate_starts:
        occurrence_start = candidate.replace(tzinfo=TIMEZONE)
        occurrence_key = _recurrence_key(occurrence_start)
        if occurrence_key in excluded:
            continue
        override = overrides.get(occurrence_key)
        component = override or master
        if _text(component.get("STATUS")).upper() == "CANCELLED":
            continue
        # A master DTSTART is the anchor for the series; each occurrence must
        # use the expanded candidate. An override may move the occurrence and
        # therefore uses its own DTSTART.
        actual_start = _as_local(_prop_datetime(override, "DTSTART")) if override is not None and _prop_datetime(override, "DTSTART") is not None else occurrence_start
        actual_end = actual_start + _duration(override if override is not None else master)
        if actual_start >= window_end or actual_end <= window_start:
            continue
        result = _make_source_event(component, actual_start, actual_end, calendar_name, recurring=recurring)
        if result:
            yield result


def expand_events(
    calendars: Sequence[Calendar],
    window_start: datetime,
    window_end: datetime,
) -> list[SourceEvent]:
    """Expand all source occurrences inside a local-time window."""

    grouped: dict[str, list[Event]] = {}
    names: dict[str, str] = {}
    # Merge across both feeds in one pass so a duplicate UID is not emitted
    # twice merely because it appeared in both source calendars.
    merged = merge_components(calendars)
    for component in merged:
        uid = _text(component.get("UID"))
        grouped.setdefault(uid, []).append(component)
        names[uid] = " + ".join(
            sorted(
                {
                    _text(calendar.get("X-WR-CALNAME")) or "ESI timetable"
                    for calendar in calendars
                    if any(_text(item.get("UID")) == uid for item in calendar.walk("VEVENT"))
                }
            )
        )
    expanded: list[SourceEvent] = []
    for uid, components in grouped.items():
        expanded.extend(_expand_uid_group(components, window_start, window_end, names[uid]))
    return sorted(expanded, key=lambda item: (item.start, item.end, item.uid))


def matches_exclusion(event: SourceEvent, rule: ExclusionRule) -> bool:
    if rule.recurring_only and not event.recurring:
        return False
    if event.start.weekday() != rule.weekday:
        return False
    # Match classes contained in the user's stated block. This catches the
    # live 13:30–14:55 course inside the requested Wednesday 13:00–15:00 slot.
    if event.start.time() < rule.start or event.end.time() > rule.end:
        return False
    return re.search(rule.title_pattern, event.summary) is not None


def filter_attendance(events: Iterable[SourceEvent], rules: Sequence[ExclusionRule]) -> list[SourceEvent]:
    return [event for event in events if not any(matches_exclusion(event, rule) for rule in rules)]


def import_attendance(
    calendars: Sequence[Calendar],
    window_start: datetime,
    window_end: datetime,
    rules: Sequence[ExclusionRule],
) -> tuple[list[SourceEvent], list[SourceEvent]]:
    """Return (attended, excluded) source occurrences for diagnostics."""

    expanded = expand_events(calendars, window_start, window_end)
    excluded = [event for event in expanded if any(matches_exclusion(event, rule) for rule in rules)]
    attended = [event for event in expanded if event not in excluded]
    return attended, excluded
