"""Deterministic, deadline-aware revision scheduling."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from .config import FixedCommitment, Preferences
from .importer import SourceEvent


@dataclass(frozen=True)
class RevisionEvent:
    uid: str
    start: datetime
    end: datetime
    summary: str
    description: str
    module: str
    objective_key: str


@dataclass(frozen=True)
class Task:
    module: str
    objective_key: str
    label: str
    duration_minutes: int
    objective: str
    tasks: str
    completion: str


def _slug(value: str) -> str:
    value = value.lower().replace("è", "e").replace("é", "e").replace("ê", "e")
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def _overlaps(start: datetime, end: datetime, other_start: datetime, other_end: datetime) -> bool:
    return start < other_end and end > other_start


def _busy_intervals(
    attended: Sequence[SourceEvent],
    fixed: Sequence[FixedCommitment],
    timezone: ZoneInfo,
) -> list[tuple[datetime, datetime]]:
    result = []
    for event in attended:
        # A short buffer protects travel/recovery time around campus sessions.
        result.append((event.start - timedelta(minutes=15), event.end + timedelta(minutes=15)))
    result.extend((item.busy_start, item.busy_end) for item in fixed)
    return sorted(result)


def _study_windows(day: date, timezone: ZoneInfo) -> list[tuple[datetime, datetime]]:
    # These windows provide meals and recovery breaks while allowing daytime
    # free intervals to be used when the university timetable permits it.
    if day.weekday() == 5:  # Saturday: internship/meeting make this narrow.
        spans = [(time(16, 30), time(18, 0))]
    elif day.weekday() == 6:  # Sunday
        spans = [(time(9, 0), time(12, 0)), (time(14, 0), time(18, 0)), (time(19, 30), time(22, 0))]
    else:
        spans = [(time(8, 30), time(12, 0)), (time(14, 0), time(17, 30)), (time(19, 0), time(22, 30))]
    return [
        (datetime.combine(day, start, tzinfo=timezone), datetime.combine(day, end, tzinfo=timezone))
        for start, end in spans
    ]


def _free_intervals(
    day: date,
    busy: Sequence[tuple[datetime, datetime]],
    now: datetime,
    timezone: ZoneInfo,
) -> list[tuple[datetime, datetime]]:
    free: list[tuple[datetime, datetime]] = []
    for window_start, window_end in _study_windows(day, timezone):
        cursor = max(window_start, now)
        for busy_start, busy_end in busy:
            if busy_end <= cursor or busy_start >= window_end:
                continue
            if busy_start > cursor:
                free.append((cursor, min(busy_start, window_end)))
            cursor = max(cursor, busy_end)
            if cursor >= window_end:
                break
        if cursor < window_end:
            free.append((cursor, window_end))
    return [(start, end) for start, end in free if (end - start) >= timedelta(minutes=45)]


def _urgent_tasks(now: datetime, preferences: Preferences) -> list[tuple[date, Task]]:
    """Return a small active-recall plan before the known POO test."""

    if now.date() > preferences.poo_test_date - timedelta(days=1):
        return []
    tasks = [
        Task("POO", "timed-exercises", "POO — Exercices chronométrés", 90, "Practise under test conditions.", "Solve a representative timed exercise without notes, then mark uncertain steps.", "One complete timed solution and a list of errors to correct."),
        Task("POO", "past-exams", "POO — Examen blanc", 90, "Practise a past exam or exam-style set.", "Complete the hardest available past-paper questions; keep the phone and notes away.", "A full attempt with every unanswered item flagged."),
        Task("POO", "correction", "POO — Correction ciblée", 60, "Turn mistakes into reusable rules.", "Correct the timed/past-paper attempt and write a compact error log.", "Each error has a cause, corrected method, and one follow-up question."),
        Task("POO", "weak-topics", "POO — Points faibles", 75, "Repair the weakest POO topics.", "Re-solve only the questions linked to the error log; explain each solution aloud.", "At least three weak-topic questions solved without notes."),
        Task("POO", "final-recall", "POO — Rappel final", 45, "Consolidate before the test.", "Review the error log, definitions, and common traps; do not start a new chapter.", "A one-page checklist and no unresolved high-risk error."),
    ]
    # Spread the urgent work across the days available, with two blocks on
    # the first/last days only when the timetable leaves room.
    available_days = []
    day = now.date()
    while day < preferences.poo_test_date:
        available_days.append(day)
        day += timedelta(days=1)
    if not available_days:
        return []
    assignments: list[tuple[date, Task]] = []
    # Friday evening, Saturday, Sunday, and Monday receive respectively 1–2
    # blocks. The exact start times are chosen later from free intervals.
    for index, task in enumerate(tasks):
        preferred_index = min(index * max(1, len(available_days) // len(tasks)), len(available_days) - 1)
        assignments.append((available_days[preferred_index], task))
    if len(available_days) >= 3 and len(tasks) >= 4:
        # Ensure correction happens soon after the first timed work.
        assignments[2] = (available_days[min(1, len(available_days) - 1)], tasks[2])
    return assignments


def _rotation_tasks() -> list[Task]:
    return [
        Task("ELECF", "course-and-formulas", "ELECF — Révision du cours", 75, "Understand definitions and formulas.", "Review one section, derive the key formulas, and do two applications.", "A short formula sheet plus two checked applications."),
        Task("Algèbre", "exercises", "Algèbre — Exercices", 75, "Practise problem-solving.", "Solve representative exercises and correct mistakes; keep theory review short.", "Three exercises corrected and one recurring mistake noted."),
        Task("PRST", "exercises", "PRST — Exercices", 75, "Maintain the probability/statistics rotation.", "Work a representative exercise set and record formulas that were actually needed.", "Two exercises solved and a compact list of uncertainties."),
        Task("Analyse", "spaced-recall", "Analyse — Rappel espacé", 60, "Keep familiar material active.", "Recall key methods from memory, then complete one representative exercise.", "One exercise corrected and the recall score recorded."),
        Task("SFSD", "spaced-recall", "SFSD — Rappel espacé", 60, "Keep familiar material active.", "Recall the main data-structure/file concepts and solve one representative exercise.", "One exercise corrected and one misconception logged."),
        Task("Archi", "representative-exercise", "Archi — Exercice représentatif", 60, "Maintain core architecture fluency.", "Review the method from memory, then solve one representative exercise.", "One complete exercise corrected."),
    ]


def _task_description(task: Task, start: datetime, attended: Sequence[SourceEvent]) -> str:
    return (
        f"Module: {task.module}\n"
        f"Objectif: {task.objective}\n"
        f"Tâches suggérées: {task.tasks}\n"
        f"Critère de fin: {task.completion}\n"
        "\n"
        "Cette séance a été placée dans un intervalle libre du calendrier ESI; "
        "les événements universitaires ne sont pas copiés dans ce calendrier."
    )


def _uid(task: Task, day: date) -> str:
    return f"{_slug(task.module)}-{day.isoformat()}-{_slug(task.objective_key)}@esi-revision-calendar"


def _place_task(
    task: Task,
    day: date,
    free: list[tuple[datetime, datetime]],
    daily_used: int,
    daily_limit: int,
    attended: Sequence[SourceEvent],
) -> tuple[RevisionEvent | None, int]:
    duration = timedelta(minutes=task.duration_minutes)
    if daily_used + task.duration_minutes > daily_limit:
        return None, daily_used
    for index, (slot_start, slot_end) in enumerate(free):
        if slot_end - slot_start < duration:
            continue
        start = slot_start.replace(second=0, microsecond=0)
        end = start + duration
        if end > slot_end:
            continue
        if any(_overlaps(start, end, item.start - timedelta(minutes=15), item.end + timedelta(minutes=15)) for item in attended):
            continue
        event = RevisionEvent(
            uid=_uid(task, day),
            start=start,
            end=end,
            summary=task.label,
            description=_task_description(task, start, attended),
            module=task.module,
            objective_key=task.objective_key,
        )
        replacement: list[tuple[datetime, datetime]] = []
        if start > slot_start:
            replacement.append((slot_start, start))
        # Keep a short reset break between focused sessions. The break is not
        # emitted as a calendar event, but remains unavailable to the next
        # session so two blocks never become an exhausting back-to-back run.
        next_start = end + timedelta(minutes=15)
        if next_start < slot_end:
            replacement.append((next_start, slot_end))
        free[index : index + 1] = replacement
        return event, daily_used + task.duration_minutes
    return None, daily_used


def schedule_revision_sessions(
    attended: Sequence[SourceEvent],
    preferences: Preferences,
    now: datetime,
    horizon_days: int = 42,
    existing: Iterable[RevisionEvent] = (),
) -> list[RevisionEvent]:
    """Generate future sessions without moving past existing sessions."""

    timezone = preferences.timezone
    now = now.astimezone(timezone)
    horizon_end = now + timedelta(days=horizon_days)
    busy = _busy_intervals(attended, preferences.fixed_commitments(), timezone)
    previous = [item for item in existing if item.end <= now]
    generated: list[RevisionEvent] = list(previous)
    used_uids = {item.uid for item in generated}

    by_day_free: dict[date, list[tuple[datetime, datetime]]] = {}
    daily_used: dict[date, int] = {}
    day = now.date()
    while day <= horizon_end.date():
        by_day_free[day] = _free_intervals(day, busy, now, timezone)
        daily_used[day] = 0
        day += timedelta(days=1)

    for preferred_day, task in _urgent_tasks(now, preferences):
        candidate_days = [d for d in sorted(by_day_free) if d >= preferred_day and d < preferences.poo_test_date]
        for candidate_day in candidate_days:
            limit = preferences.weekend_limit_minutes if candidate_day.weekday() >= 5 else preferences.daily_limit_minutes
            event, updated = _place_task(task, candidate_day, by_day_free[candidate_day], daily_used[candidate_day], limit, attended)
            if event and event.uid not in used_uids:
                generated.append(event)
                used_uids.add(event.uid)
                daily_used[candidate_day] = updated
                break

    rotation = _rotation_tasks()
    rotation_index = 0
    for day in sorted(by_day_free):
        # The test time is not provided, so keep the entire assessment date
        # free instead of inventing a safe-looking slot around it.
        if day == preferences.poo_test_date:
            continue
        limit = preferences.weekend_limit_minutes if day.weekday() >= 5 else preferences.daily_limit_minutes
        # Fill at most two normal sessions per day; urgent POO naturally may
        # already have consumed the daily budget.
        attempts = 0
        while by_day_free[day] and daily_used[day] + 45 <= limit and attempts < len(rotation) * 2:
            task = rotation[rotation_index % len(rotation)]
            rotation_index += 1
            attempts += 1
            event, updated = _place_task(task, day, by_day_free[day], daily_used[day], limit, attended)
            if event and event.uid not in used_uids:
                generated.append(event)
                used_uids.add(event.uid)
                daily_used[day] = updated
                break
            if all(slot_end - slot_start < timedelta(minutes=45) for slot_start, slot_end in by_day_free[day]):
                break

    return sorted(generated, key=lambda item: (item.start, item.end, item.uid))
