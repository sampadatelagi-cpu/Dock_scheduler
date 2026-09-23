# WHOI Dock Scheduling System

A system for managing berth reservations at a marine research facility, built from a real 23-year Excel workbook (1997–2019) of hand-maintained booking calendars.

## What it does

- Loads real historical berth/reservation data directly from the source workbook (`ingest.py`)
- Checks whether a vessel fits a berth by length (`fits()`)
- Detects double-bookings — the exact problem this facility currently solves by manually eyeballing a grid (`has_conflict()`)
- Computes yearly berth usage, replacing a hand-tallied summary sheet (`yearly_usage()`)
- A Streamlit interface for non-technical dock staff to view the schedule, try a new reservation, and see usage stats

## Run it

Install the dependencies, then launch the app:

```
python3 -m pip install --user streamlit pandas openpyxl
python3 -m streamlit run app.py
```

## Real result found

Running the conflict checker against the actual 1997–2019 data surfaced a real double-booking: the same vessel booked twice on North Pier West around December 2002 — something that's been sitting undetected in the historical record. This is not a synthetic test case; it's the tool catching a real error a manual grid-check missed.

## Architecture

| File | Responsibility |
|---|---|
| `models.py` | Data types: `Berth`, `Vessel`, `Operator`, `Reservation`, `Tour` |
| `ingest.py` | Parses the raw workbook into clean `Berth`/`Reservation` objects — the one place spreadsheet messiness is absorbed |
| `logic.py` | Core rules: fit checking, conflict detection, yearly usage |
| `app.py` | Streamlit UI for dock staff |
| `demo.py` | Console script showing the logic running against real data |
| `test_logic.py` | Unit tests for the core logic |

`ingest.py` is deliberately isolated so nothing downstream — logic, UI, tests — ever has to know the data came from a hand-maintained Excel file. Everything past that boundary works with clean typed objects.

## Why each tab exists

Every tab maps to something explicitly called out in the original brief — this wasn't features added for their own sake, each one replaces a specific manual process WHOI staff currently do by hand.

**Schedule** — The brief describes staff manually checking a grid to spot double-bookings and verify a vessel fits its assigned berth. This tab is that grid, but computed from the real ingested data instead of maintained by eye — staff can pick a berth and month and see exactly what's booked, including both vessel stays and non-vessel events (like a community sail day) in the same view, since both compete for the same physical space.

**Add a reservation** — This is where the two manual checks the brief names — "does it fit" and "is it already booked" — actually get automated. Instead of a staff member eyeballing a calendar and a berth spec sheet, the form runs `fits()` and `has_conflict()` against the full real historical dataset the moment a new booking is proposed, and shows the specific conflicting reservation by name rather than just "yes/no." It supports both vessel bookings and non-vessel events, since the brief treats community sail days as occupying a berth exactly like a vessel does.

**Data quality** — The brief doesn't ask for this directly, but it's the honest byproduct of everything else: migrating 23 years of hand-maintained spreadsheets into a system that refuses to guess produces a list of records it genuinely can't resolve. Staff need to know which parts of the historical record are trustworthy and which need a human to double-check by hand — hiding that uncertainty would be worse than showing it, even though it makes the tool look "less finished."

**Yearly usage** — The brief specifically mentions a yearly count of total days each berth is used, which the sample data shows is currently a hand-tallied table (the "8YR Dock Usage" sheet). This tab computes that same figure directly from the reservation data instead of a manual tally, so it's always in sync with the actual schedule rather than a separately-maintained summary that can drift out of date.

## Data quality: why a whole tab is dedicated to it

The real workbook is 23 years of manual entry, and it shows: shifting column layouts, merged cells used inconsistently, berths renamed or added mid-history, and ambiguous formatting with no documented meaning.

Ingestion extracted **2,179 reservations** across **8 berths**, and explicitly flagged **337 records** it could not confidently interpret, rather than guessing:

| Flag reason | What it means |
|---|---|
| Rare, sheet-specific fill color on a blank cell | Could be a leftover highlight from a deleted booking — not enough signal to invent a reservation |
| Empty merged cell range | A colored block with no text at all — genuinely ambiguous |
| Date-count mismatch in a month's header row | A handful of month blocks have one or two extra/missing day columns, meaning the last day or two of that block may be mis-dated |

**Why this matters as a design choice, not a footnote:** a system that quietly resolves ambiguity to make its output look clean is more dangerous than one that shows its uncertainty — staff relying on this tool need to know which parts of 23 years of history are trustworthy and which need a human to double-check, not be told everything is fine when it isn't. The Data Quality tab is that list, made visible instead of buried in a log file.

For most of these flags, there's genuinely no additional information in the source to resolve them against — an empty merged cell either was a real booking someone deleted, or it never was one, and nothing in the sheet says which. Guessing would just hide an assumption behind a clean report. Human review is the correct resolution mechanism for that kind of ambiguity, not a stopgap.

### Two real bugs caught during ingestion

1. **False-positive flagging from decorative formatting.** Nearly every blank grid cell carries a background fill for weekend shading — flagging all of those as "ambiguous" would have produced 12,000+ false positives and made the flag list meaningless. Fixed by only flagging fills that are rare *within their own sheet*, not the dominant background color.
2. **Silent data loss from a hardcoded column assumption.** The date-header row's starting column drifts across years (column B in early years, column F by 2011); the initial parser assumed a fixed position and silently dropped all of 2011–2019. Caught by comparing extracted date ranges against the sheet names before trusting the output.

## Key design decisions

- **Unknown data is modeled explicitly, never guessed.** `fits()` returns `OK`, `FAIL`, or `UNKNOWN` — `UNKNOWN` when a vessel's length or a berth's length isn't recorded, rather than silently passing or failing. This same pattern is reused, not reinvented, when two berth categories ("North Finger Piers", "Small craft slips") appeared in the data from ~2015 onward with no recorded length: they're modeled as real berths with `length_ft=None`, flowing through the exact same `UNKNOWN` logic as an unknown-length vessel.
- **Non-vessel events share the same table as vessel bookings.** A community sail day occupies a berth exactly like a vessel does, so `Reservation.vessel_id` is nullable with a `label` field for events — one conflict-check path instead of two, and the "Add a reservation" form lets staff create either type.
- **Cell fill color was investigated and intentionally not used.** Inspection showed each vessel is manually assigned one consistent color across its bookings — it's a per-vessel visual convention, not a status field, so it carries no information `has_conflict()` needs.
- **Berths aren't static over 23 years.** The berth list changes between the 1997 calendar tabs and the later usage summaries (e.g. "Inner Channel" disappears, "North Finger Piers" and "Marsh Landing" appear) — `Berth` supports `active_from`/`active_to` rather than assuming one fixed list for all time.

## Scoped out (and why)

Given the ~3–5 hour time budget, these were deliberately not built:

- **Vessel/operator contact normalization** (Science/Yachts sheets) — the layout has no reliable delimiter between one vessel's contact block and the next; doing this correctly needs dedicated row-grouping logic that didn't fit the remaining budget.
- **Tours integration** — the Tours tab is explicitly marked in the source file as historical/deprecated ("tours are now tracked in a separate workbook"), so building against it wouldn't reflect current operations; would need the current tracking source.
- **Tide/weather integration** — `Vessel.draft_ft` is already captured in the model for exactly this purpose. The real integration point would be NOAA's CO-OPS API for tide predictions; not implemented here to keep scope realistic for the time budget.
- **Public/private views** — considered early on, but nothing in the actual data supports a meaningful public/private distinction, so building it would have meant designing around a guess rather than evidence.

## Future additions

With more time, the natural next layer on top of this foundation:

- **Live tide/weather advisories.** `Vessel.draft_ft` is already captured in the model for this. The next step is pulling real tide predictions (NOAA's CO-OPS API, free and station-based) and warning staff if a vessel's draft won't clear a berth's low tide during its reservation window — not just whether it fits by length, but whether it's safe to dock there on those specific days.
- **More visually distinct conflict alerts.** A conflict currently shows as a red text message. A stronger visual treatment would make a double-booking harder to miss when someone is scanning quickly rather than reading carefully.
- **Per-reservation access control.** A blanket public/private dashboard split wasn't justified by the data, but a narrower `restricted` flag on individual reservations could handle the rare case of a booking that shouldn't be publicly visible, without assuming that applies to a whole category of vessels.
- **Automated triage of flagged records.** Not all 337 flagged records are equally uncertain — a secondary pass could rank them by confidence (e.g. an empty merged cell adjacent to an identical-vessel booking on either side is a stronger candidate for "likely part of that stay" than an isolated blank cell) to shrink the manual-review pile without fabricating bookings for genuinely unresolvable cases.
- **Vessel/operator contact normalization and Tours integration** — scoped out here due to time, but a natural extension once the core scheduling logic is trusted.

None of these are built here — they're what this submission is a foundation for, not a replacement for.

## Tests

`test_logic.py` covers: berth-fit pass/fail/unknown, conflict detection on overlapping dates, no false conflict on adjacent (non-overlapping) dates, and yearly usage totals (including a reservation spanning a year boundary). Run with:

```
python3 -m pytest test_logic.py
```