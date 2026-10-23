from datetime import datetime
from zoneinfo import ZoneInfo

from icalendar import Calendar

from esi_revision_calendar.config import Preferences
from esi_revision_calendar.importer import expand_events, filter_attendance, merge_components


TZ = ZoneInfo("Africa/Algiers")


def calendar_from(text: str) -> Calendar:
    return Calendar.from_ical(text.replace("\n", "\r\n").encode())


def test_recurring_event_honours_exdate_and_cancelled_exception():
    source = calendar_from(
        """BEGIN:VCALENDAR
VERSION:2.0
X-WR-CALNAME:Test
BEGIN:VEVENT
UID:series@example
DTSTART;TZID=Africa/Algiers:20261025T150000
DTEND;TZID=Africa/Algiers:20261025T170000
RRULE:FREQ=WEEKLY;COUNT=4
EXDATE;TZID=Africa/Algiers:20261108T150000
SUMMARY:TD CAD
END:VEVENT
BEGIN:VEVENT
UID:series@example
RECURRENCE-ID;TZID=Africa/Algiers:20261101T150000
DTSTART;TZID=Africa/Algiers:20261101T150000
DTEND;TZID=Africa/Algiers:20261101T170000
STATUS:CANCELLED
SUMMARY:TD CAD
END:VEVENT
END:VCALENDAR
"""
    )
    events = expand_events(
        [source],
        datetime(2026, 10, 23, tzinfo=TZ),
        datetime(2026, 11, 20, tzinfo=TZ),
    )
    assert [event.start.date().isoformat() for event in events] == ["2026-10-25", "2026-11-15"]


def test_duplicate_uid_uses_latest_sequence_and_is_not_duplicated():
    first = calendar_from(
        """BEGIN:VCALENDAR
VERSION:2.0
X-WR-CALNAME:A
BEGIN:VEVENT
UID:duplicate@example
DTSTART;TZID=Africa/Algiers:20261026T090000
DTEND;TZID=Africa/Algiers:20261026T100000
DTSTAMP:20261001T000000Z
SEQUENCE:0
SUMMARY:Old
END:VEVENT
END:VCALENDAR
"""
    )
    second = calendar_from(
        """BEGIN:VCALENDAR
VERSION:2.0
X-WR-CALNAME:B
BEGIN:VEVENT
UID:duplicate@example
DTSTART;TZID=Africa/Algiers:20261026T100000
DTEND;TZID=Africa/Algiers:20261026T110000
DTSTAMP:20261002T000000Z
SEQUENCE:1
SUMMARY:Updated
END:VEVENT
END:VCALENDAR
"""
    )
    assert len(merge_components([first, second])) == 1
    events = expand_events([first, second], datetime(2026, 10, 26, tzinfo=TZ), datetime(2026, 10, 27, tzinfo=TZ))
    assert len(events) == 1
    assert events[0].summary == "Updated"
    assert events[0].start.hour == 10


def test_attendance_exclusions_match_day_time_and_title_only():
    source = calendar_from(
        """BEGIN:VCALENDAR
VERSION:2.0
X-WR-CALNAME:2CP A G03
BEGIN:VEVENT
UID:sun-td@example
DTSTART;TZID=Africa/Algiers:20261025T150000
DTEND;TZID=Africa/Algiers:20261025T165500
RRULE:FREQ=WEEKLY;COUNT=2
SUMMARY:TD CAD BOUMAZOUZA D
END:VEVENT
BEGIN:VEVENT
UID:wed-td@example
DTSTART;TZID=Africa/Algiers:20261028T083000
DTEND;TZID=Africa/Algiers:20261028T095500
RRULE:FREQ=WEEKLY;COUNT=2
SUMMARY:TD SFSV MEKKI M
END:VEVENT
BEGIN:VEVENT
UID:wed-course@example
DTSTART;TZID=Africa/Algiers:20261028T133000
DTEND;TZID=Africa/Algiers:20261028T145500
RRULE:FREQ=WEEKLY;COUNT=2
SUMMARY:Cours LALG2 CHACHOUA A
END:VEVENT
BEGIN:VEVENT
UID:wed-other@example
DTSTART;TZID=Africa/Algiers:20261028T133000
DTEND;TZID=Africa/Algiers:20261028T145500
RRULE:FREQ=WEEKLY;COUNT=2
SUMMARY:TD LALG2 OTHER
END:VEVENT
END:VCALENDAR
"""
    )
    expanded = expand_events([source], datetime(2026, 10, 23, tzinfo=TZ), datetime(2026, 11, 5, tzinfo=TZ))
    attended = filter_attendance(expanded, Preferences().exclusion_rules)
    assert {event.summary for event in attended} == {"TD LALG2 OTHER"}
