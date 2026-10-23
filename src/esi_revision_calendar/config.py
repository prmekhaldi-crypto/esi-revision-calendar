"""User preferences and timetable matching rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

TIMEZONE: Final = ZoneInfo("Africa/Algiers")
FEED_URLS: Final = (
    "https://calendar.google.com/calendar/ical/esi.dz_1ak7f1i5ck5stp9ffrqhacksi4%40group.calendar.google.com/public/basic.ics",
    "https://calendar.google.com/calendar/ical/esi.dz_7nkdki6hpqv1l7880cmpe3qj14%40group.calendar.google.com/public/basic.ics",
)


@dataclass(frozen=True)
class ExclusionRule:
    """A class block the student does not attend.

    Matching is deliberately narrow: weekday, time containment, a title
    pattern, and (by default) recurrence are all required. This prevents a
    similarly named one-off class from being removed accidentally.
    """

    name: str
    weekday: int  # Monday=0, Sunday=6
    start: time
    end: time
    title_pattern: str
    recurring_only: bool = True


@dataclass(frozen=True)
class FixedCommitment:
    name: str
    start: datetime
    end: datetime
    # Extra preparation or travel time is busy for scheduling, but is not
    # emitted in the revision-only calendar.
    buffer_before: timedelta = timedelta(0)
    buffer_after: timedelta = timedelta(0)

    @property
    def busy_start(self) -> datetime:
        return self.start - self.buffer_before

    @property
    def busy_end(self) -> datetime:
        return self.end + self.buffer_after


@dataclass(frozen=True)
class Preferences:
    timezone: ZoneInfo = TIMEZONE
    academic_year: str = "2026–2027"
    year: int = 2
    group: int = 3
    poo_test_date: date = date(2026, 10, 27)
    daily_limit_minutes: int = 240
    weekend_limit_minutes: int = 270
    min_session_minutes: int = 45
    max_session_minutes: int = 90
    modules: tuple[str, ...] = (
        "POO",
        "ELECF",
        "Algèbre",
        "PRST",
        "Analyse",
        "SFSD",
        "Archi",
    )
    # Source names observed in the official feeds. These are used only for
    # optional reporting; all timetable events remain busy regardless of
    # whether a module name is recognized.
    source_aliases: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: {
            "POO": ("POO", "OOP", "OOE"),
            "PRST": ("PRST", "PRDS"),
            "SFSD": ("SFSD", "SFSV"),
            "Archi": ("ARCH", "ARCHI", "CAD"),
            "Analyse": ("ANAL", "ANALYSE"),
            "Algèbre": ("ALG", "ALGEBRE", "LALG"),
            "ELECF": ("ELECF", "ELEF"),
        }
    )

    @property
    def exclusion_rules(self) -> tuple[ExclusionRule, ...]:
        return (
            ExclusionRule(
                "Sunday TD 15:00–17:00",
                weekday=6,
                start=time(15, 0),
                end=time(17, 0),
                title_pattern=r"(?i)^e?-?TD\b",
            ),
            ExclusionRule(
                "Wednesday TD 08:30–10:00",
                weekday=2,
                start=time(8, 30),
                end=time(10, 0),
                title_pattern=r"(?i)^e?-?TD\b",
            ),
            ExclusionRule(
                "Wednesday course 13:00–15:00",
                weekday=2,
                start=time(13, 0),
                end=time(15, 0),
                title_pattern=r"(?i)^e?Cours\b",
            ),
        )

    def fixed_commitments(self) -> tuple[FixedCommitment, ...]:
        tz = self.timezone
        return (
            FixedCommitment(
                "Completed POO study on 23 October",
                datetime(2026, 10, 23, 10, 0, tzinfo=tz),
                datetime(2026, 10, 23, 16, 0, tzinfo=tz),
            ),
            FixedCommitment(
                "Internship",
                datetime(2026, 10, 24, 9, 0, tzinfo=tz),
                datetime(2026, 10, 24, 16, 0, tzinfo=tz),
                buffer_before=timedelta(minutes=30),
                buffer_after=timedelta(minutes=30),
            ),
            FixedCommitment(
                "Meeting and preparation",
                datetime(2026, 10, 24, 20, 0, tzinfo=tz),
                datetime(2026, 10, 24, 21, 30, tzinfo=tz),
                buffer_before=timedelta(hours=2, minutes=30),
                buffer_after=timedelta(minutes=30),
            ),
        )


def local_now() -> datetime:
    return datetime.now(TIMEZONE)


def parse_start(value: str | None, timezone: ZoneInfo = TIMEZONE) -> datetime:
    """Parse an ISO datetime, defaulting to the current local time."""

    if not value:
        return datetime.now(timezone)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)
