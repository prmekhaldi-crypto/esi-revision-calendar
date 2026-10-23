# ESI Revision Calendar for iPhone

This project generates a revision-only iCalendar feed for ESI 2CP, group 3,
using the two public ESI timetable feeds as availability constraints. It does
not copy or modify the source timetables. It expands recurrence rules,
exceptions, cancellations, and updates before deciding which intervals are
available for revision.

The current exclusions are deliberately matched by weekday, contained time
block, title, and recurrence: Sunday TD 15:00–17:00; Wednesday TD
08:30–10:00; and Wednesday course/lecture 13:00–15:00. In the live feed these
correspond to `TD CAD`, `TD SFSV`, and `Cours LALG2` occurrences. The live
2026–27 feed exposes module abbreviations such as `PRDS`, `SFSV`, `LALG2`, and
`ELEF2`; all source events remain busy even when a module alias is unknown.

## Local setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
PYTHONPATH=src python -m esi_revision_calendar.cli \
  --output public/revision-calendar.ics \
  --horizon-days 42 \
  --keep-previous
```

The generator starts at the current `Africa/Algiers` time by default. For a
reproducible run:

```bash
PYTHONPATH=src python -m esi_revision_calendar.cli \
  --start 2026-10-23T17:30:00+01:00 \
  --output public/revision-calendar.ics
```

If either feed fails or returns invalid/empty data, generation exits before
touching the previous output. The file is validated for iCalendar 2.0,
parseability, stable unique UIDs, required start/end fields, UTF-8, line
folding, and CRLF line endings.

## Preview

After generation, the next-seven-day preview can be printed with:

```bash
PYTHONPATH=src python scripts/preview.py public/revision-calendar.ics --days 7
```

The urgent plan gives POO active problem-solving priority before 27 October
2026, then rotates ELECF, Algèbre, PRST, Analyse, SFSD, and Archi. It does not
invent assessment dates for the other modules.

## Tests

```bash
pytest -q
```

The tests cover recurrence expansion, EXDATE, cancelled exceptions, duplicate
UID updates, time-zone handling, the three attendance filters, commitment
overlap prevention, deterministic UIDs, output validation, and failed-feed
failover.

## GitHub Pages deployment

The included workflow regenerates the feed twice daily at 02:17 and 14:17 UTC
and supports **Run workflow** for a manual refresh. It deploys `public/` as a
GitHub Pages artifact. Enable Pages in the repository settings with **Source:
GitHub Actions**. The final subscription URL is:

```text
https://<github-user>.github.io/<repository>/revision-calendar.ics
```

Once the repository has been created and Pages has completed its first
deployment, verify it before subscribing:

```bash
curl --fail --location --silent \
  https://<github-user>.github.io/<repository>/revision-calendar.ics \
  | python -c 'import sys; from icalendar import Calendar; Calendar.from_ical(sys.stdin.buffer.read()); print("valid iCalendar")'
```

## Subscribe on iPhone

1. Copy the verified HTTPS URL ending in `.ics`.
2. On iPhone, open **Settings → Calendar → Accounts → Add Account → Other**.
3. Choose **Add Subscribed Calendar**, paste the URL, and tap **Next**.
4. Confirm the calendar name and tap **Save**.

The workflow publishes a rolling 42-day plan. Completed/past revision events
already present in the output are preserved when `--keep-previous` is used;
future events are recalculated against the latest timetable. iPhone refresh
timing is controlled by iOS, while the public file is rebuilt every 12 hours.
