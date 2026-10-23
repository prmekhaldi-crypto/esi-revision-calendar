from datetime import datetime
from zoneinfo import ZoneInfo

from esi_revision_calendar.config import Preferences
from esi_revision_calendar.importer import SourceEvent
from esi_revision_calendar.scheduler import schedule_revision_sessions


TZ = ZoneInfo("Africa/Algiers")


def test_scheduler_prioritises_poo_and_avoids_classes_and_commitments():
    now = datetime(2026, 10, 23, 17, 30, tzinfo=TZ)
    attended = [
        SourceEvent("class", datetime(2026, 10, 26, 8, 30, tzinfo=TZ), datetime(2026, 10, 26, 10, 25, tzinfo=TZ), "Cours PRDS", "ESI", True),
        SourceEvent("class2", datetime(2026, 10, 28, 10, 0, tzinfo=TZ), datetime(2026, 10, 28, 12, 25, tzinfo=TZ), "TD OOP", "ESI", True),
    ]
    events = schedule_revision_sessions(attended, Preferences(), now, horizon_days=7)
    urgent = [event for event in events if event.module == "POO" and event.start.date() < Preferences().poo_test_date]
    assert len(urgent) >= 3
    assert all(event.end.date() <= Preferences().poo_test_date for event in urgent)
    for revision in events:
        assert not any(
            revision.start < busy.end + __import__("datetime").timedelta(minutes=15)
            and revision.end > busy.start - __import__("datetime").timedelta(minutes=15)
            for busy in attended
        )
    assert not any(
        revision.start < fixed.busy_end and revision.end > fixed.busy_start
        for revision in events
        for fixed in Preferences().fixed_commitments()
    )


def test_schedule_is_deterministic_for_same_inputs():
    now = datetime(2026, 10, 23, 17, 30, tzinfo=TZ)
    first = schedule_revision_sessions([], Preferences(), now, horizon_days=3)
    second = schedule_revision_sessions([], Preferences(), now, horizon_days=3)
    assert [(event.uid, event.start, event.end) for event in first] == [(event.uid, event.start, event.end) for event in second]
