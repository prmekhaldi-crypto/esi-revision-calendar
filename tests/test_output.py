from datetime import datetime
from zoneinfo import ZoneInfo

from esi_revision_calendar.ical_output import build_calendar, serialize_calendar, validate_calendar_bytes
from esi_revision_calendar.scheduler import RevisionEvent


def test_output_is_parseable_ics_with_stable_uid_and_escaped_description():
    event = RevisionEvent(
        uid="poo-2026-10-24-past-exams@esi-revision-calendar",
        start=datetime(2026, 10, 24, 16, 30, tzinfo=ZoneInfo("Africa/Algiers")),
        end=datetime(2026, 10, 24, 18, 0, tzinfo=ZoneInfo("Africa/Algiers")),
        summary="POO — Examen blanc",
        description="Line one, with comma; and a backslash \\ plus\nLine two.",
        module="POO",
        objective_key="past-exams",
    )
    payload = serialize_calendar(build_calendar([event], datetime(2026, 10, 23, 16, 0, tzinfo=ZoneInfo("UTC"))))
    assert validate_calendar_bytes(payload) == []
    assert b"UID:poo-2026-10-24-past-exams@esi-revision-calendar\r\n" in payload
    assert b"DTSTART;TZID=tzid" not in payload
    assert b"\n" in payload
    assert b"\r\n" in payload
