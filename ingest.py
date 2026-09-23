"""
Absorbs the messiness of the hand-maintained dock schedule workbook.

This is the only module that should ever touch openpyxl or know that the
source of truth is an Excel file. Everything downstream (logic.py, app.py)
works with the clean dataclasses from models.py.
"""

from __future__ import annotations

import calendar
import re
import sys
from dataclasses import dataclass
from datetime import date

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

from models import Berth, Reservation

DEFAULT_WORKBOOK_PATH = "/Users/sampadatelagi/Downloads/Dock Schedule - Synthetic Sample.xlsx"

YEAR_TAB_RE = re.compile(r"^(19|20)\d{2}$")
BERTH_LABEL_RE = re.compile(r"^(?P<name>.+?)\s*-\s*(?P<length>\d+)\s*'\s*$")

# Berth-category labels that never carry a "- NNN'" footage in the workbook
# (Pass 1 found these appearing from ~2014 on). Folded in as real berths with
# length_ft=None rather than left flagged, per explicit instruction.
NON_STANDARD_BERTHS = {"north finger piers", "small craft slips (institution boats)"}

MONTH_PREFIXES = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
MONTH_TITLE_RE = re.compile(r"^([A-Za-z]{3,9})\.?\s*(\d{4})?\s*$")

VESSEL_PREFIX_RE = re.compile(
    r"^(M/V|F/V|S/V|R/V|M/Y|OSV|Tug|Barge)\b", re.IGNORECASE
)


@dataclass
class NeedsReview:
    sheet: str
    location: str
    reason: str
    raw_value: object = None


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug


def _berth_id(name: str, length: int | None) -> str:
    return _slugify(f"{name}-{length}" if length is not None else name)


def _month_from_title(title: str) -> int | None:
    m = MONTH_TITLE_RE.match(title.strip())
    if not m:
        return None
    prefix = m.group(1)[:3].upper()
    return MONTH_PREFIXES.get(prefix)


def _find_title_rows(wsf: Worksheet, wsv: Worksheet) -> list[int]:
    rows = []
    for r in range(1, wsf.max_row + 1):
        a = wsf.cell(row=r, column=1).value
        if isinstance(a, str) and _month_from_title(a) is not None:
            rows.append(r)
    return rows


MAX_HEADER_SCAN_COL = 15  # date sequences have been seen starting as late as col F


def _find_number_sequence_start(wsf: Worksheet, row: int) -> int | None:
    """Returns the column where a literal-or-formula incrementing day sequence
    begins in this row, scanning a bounded window since the start column has
    drifted across years (col B in some, col F in others)."""
    for c in range(2, MAX_HEADER_SCAN_COL + 1):
        seed = wsf.cell(row=row, column=c).value
        if not isinstance(seed, (int, float)):
            continue
        nxt = wsf.cell(row=row, column=c + 1).value
        if isinstance(nxt, str) and nxt.startswith("="):
            return c
        if isinstance(nxt, (int, float)) and nxt == seed + 1:
            return c
    return None


def _row_has_number_sequence(wsf: Worksheet, wsv: Worksheet, row: int) -> bool:
    return _find_number_sequence_start(wsf, row) is not None


def _resolve_day_columns(
    wsf: Worksheet, wsv: Worksheet, date_row: int, sheet_name: str, title_row: int
) -> tuple[int, int, int]:
    """Returns (start_col, end_col, seed_value) for the contiguous day-number run."""
    start_col = _find_number_sequence_start(wsf, date_row)
    if start_col is None:
        return (2, 1, 1)  # empty range, signals failure
    seed = wsf.cell(row=date_row, column=start_col).value

    col = start_col
    expected = seed
    while True:
        v = wsf.cell(row=date_row, column=col).value
        cached = wsv.cell(row=date_row, column=col).value
        resolved = cached if isinstance(cached, (int, float)) else v
        if isinstance(resolved, (int, float)) and resolved == expected:
            col += 1
            expected += 1
            continue
        if isinstance(v, str) and v.startswith("="):
            # formula with no cached value -- trust the incrementing pattern
            col += 1
            expected += 1
            continue
        break
    end_col = col - 1
    return (start_col, end_col, int(seed))


def _parse_year_blocks(wsf: Worksheet, wsv: Worksheet, sheet_name: str, needs_review: list[NeedsReview]):
    """Yields (month, year, start_col, end_col, first_berth_row, last_berth_row) per month block."""
    title_rows = _find_title_rows(wsf, wsv)
    blocks = []
    for i, trow in enumerate(title_rows):
        title_text = wsf.cell(row=trow, column=1).value
        month = _month_from_title(title_text)
        m = MONTH_TITLE_RE.match(title_text.strip())
        year = int(m.group(2)) if m and m.group(2) else None
        if year is None:
            if YEAR_TAB_RE.match(sheet_name):
                year = int(sheet_name)
            else:
                needs_review.append(NeedsReview(sheet_name, f"row {trow}", "could not determine year for month title", title_text))
                continue

        # Pattern B: dates live on the title row itself
        if _row_has_number_sequence(wsf, wsv, trow):
            date_row = trow
            first_berth_row = trow + 2
        else:
            # Pattern A: title, day-letters, dates, then berths
            date_row = trow + 1
            if not _row_has_number_sequence(wsf, wsv, date_row):
                date_row = trow + 2
            first_berth_row = date_row + 1
            if not _row_has_number_sequence(wsf, wsv, date_row):
                needs_review.append(NeedsReview(sheet_name, f"row {trow}", "could not locate date-number row for month block", title_text))
                continue

        start_col, end_col, seed = _resolve_day_columns(wsf, wsv, date_row, sheet_name, trow)
        if end_col < start_col:
            needs_review.append(NeedsReview(sheet_name, f"row {date_row}", "empty/unparseable date row", None))
            continue

        days_found = end_col - start_col + 1
        days_expected = calendar.monthrange(year, month)[1]
        if days_found not in (days_expected, days_expected - 1, days_expected + 1):
            needs_review.append(
                NeedsReview(sheet_name, f"row {date_row}", f"date run length {days_found} doesn't match expected {days_expected} days in {year}-{month:02d}", None)
            )

        last_berth_row = (title_rows[i + 1] - 1) if i + 1 < len(title_rows) else wsf.max_row
        # trim trailing blank rows
        while last_berth_row > first_berth_row and wsf.cell(row=last_berth_row, column=1).value is None:
            last_berth_row -= 1

        blocks.append((month, year, seed, start_col, end_col, first_berth_row, last_berth_row))
    return blocks


def _col_to_date(seed: int, start_col: int, col: int, year: int, month: int) -> date | None:
    day = seed + (col - start_col)
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _looks_like_vessel(text: str) -> bool:
    return bool(VESSEL_PREFIX_RE.match(text.strip()))


def _fill_key(cell):
    fill = cell.fill
    if fill is None or fill.patternType is None:
        return None
    fg = fill.fgColor
    if fg.type == "rgb":
        return ("rgb", fg.rgb)
    if fg.type == "indexed":
        return ("indexed", fg.indexed)
    if fg.type == "theme":
        return ("theme", fg.theme, fg.tint)
    return None


RARE_FILL_THRESHOLD = 5


def _rare_blank_fill_colors(wsf: Worksheet) -> set:
    """Fill colors that show up on only a handful of blank cells in this sheet.
    A color used on hundreds of blanks is page decoration (weekend shading,
    week banding); a color used once or twice looks like a leftover from a
    booking whose text got deleted but the highlight didn't -- worth a flag."""
    from collections import Counter

    counts = Counter()
    for row in wsf.iter_rows():
        for cell in row:
            if cell.value is None:
                key = _fill_key(cell)
                if key is not None:
                    counts[key] += 1
    return {k for k, n in counts.items() if n <= RARE_FILL_THRESHOLD}


def load_berths(path: str = DEFAULT_WORKBOOK_PATH) -> list[Berth]:
    berths, _ = _load(path)
    return berths


def load_reservations(path: str = DEFAULT_WORKBOOK_PATH) -> list[Reservation]:
    _, reservations = _load(path)
    return reservations


def load_needs_review(path: str = DEFAULT_WORKBOOK_PATH) -> list[NeedsReview]:
    """Re-runs the load to get the flagged items alongside it (small file, cheap)."""
    _load(path)
    return list(_NEEDS_REVIEW)


def load_all(path: str = DEFAULT_WORKBOOK_PATH) -> tuple[list[Berth], list[Reservation], list[NeedsReview]]:
    """Single parse for callers (e.g. the Streamlit app) that want all three
    without re-parsing the workbook once per list."""
    berths, reservations = _load(path)
    return berths, reservations, list(_NEEDS_REVIEW)


def categorize_review_reason(reason: str) -> str:
    """Buckets a NeedsReview.reason string into the categories used in the data
    quality panel -- kept as substring matches on the exact phrasing _load()
    already produces, rather than a separate enum, so the two can't drift."""
    if "fill color" in reason:
        return "Rare fill color on blank cell"
    if "merged booking range has no text" in reason:
        return "Empty merged range"
    if "date run length" in reason:
        return "Date-count mismatch"
    if "berth pattern" in reason:
        return "Unrecognized berth label"
    return "Other"


_NEEDS_REVIEW: list[NeedsReview] = []


def _load(path: str) -> tuple[list[Berth], list[Reservation]]:
    global _NEEDS_REVIEW
    _NEEDS_REVIEW = []
    wbf = openpyxl.load_workbook(path, data_only=False)
    wbv = openpyxl.load_workbook(path, data_only=True)

    # name+length -> {"years": set(), }
    berth_registry: dict[tuple[str, int | None], set[int]] = {}
    reservations: list[Reservation] = []
    res_counter = 0

    year_sheets = [n for n in wbf.sheetnames if YEAR_TAB_RE.match(n)]

    for sheet_name in year_sheets:
        wsf = wbf[sheet_name]
        wsv = wbv[sheet_name]
        merged_lookup: dict[tuple[int, int], object] = {}
        for mr in wsf.merged_cells.ranges:
            for r in range(mr.min_row, mr.max_row + 1):
                for c in range(mr.min_col, mr.max_col + 1):
                    merged_lookup[(r, c)] = mr

        blocks = _parse_year_blocks(wsf, wsv, sheet_name, _NEEDS_REVIEW)
        rare_fill_colors = _rare_blank_fill_colors(wsf)

        for (month, year, seed, start_col, end_col, first_berth_row, last_berth_row) in blocks:
            for row in range(first_berth_row, last_berth_row + 1):
                label = wsf.cell(row=row, column=1).value
                if not isinstance(label, str) or not label.strip():
                    continue
                bm = BERTH_LABEL_RE.match(label)
                if bm:
                    berth_name = bm.group("name").strip()
                    berth_length = int(bm.group("length"))
                else:
                    canonical = label.strip().rstrip(":").strip()
                    if canonical.lower() not in NON_STANDARD_BERTHS:
                        _NEEDS_REVIEW.append(NeedsReview(sheet_name, f"row {row}", "row label doesn't match berth pattern '<name> - N\\''", label))
                        continue
                    berth_name = canonical
                    berth_length = None
                key = (berth_name, berth_length)
                berth_registry.setdefault(key, set()).add(year)

                col = start_col
                run_text = None
                run_start_col = None
                handled_merge_ids = set()

                def flush_run(end_col_excl: int):
                    nonlocal run_text, run_start_col, res_counter
                    if run_text is None:
                        return
                    start_d = _col_to_date(seed, start_col, run_start_col, year, month)
                    end_d = _col_to_date(seed, start_col, end_col_excl - 1, year, month)
                    if start_d is None or end_d is None:
                        _NEEDS_REVIEW.append(NeedsReview(sheet_name, f"row {row} cols {run_start_col}-{end_col_excl - 1}", "could not resolve date for run", run_text))
                        return
                    _emit_reservation(reservations, sheet_name, berth_name, berth_length, run_text, start_d, end_d)
                    res_counter += 1

                while col <= end_col:
                    mr = merged_lookup.get((row, col))
                    if mr is not None:
                        flush_run(col)
                        run_text = None
                        if id(mr) not in handled_merge_ids:
                            handled_merge_ids.add(id(mr))
                            top_val = wsf.cell(row=mr.min_row, column=mr.min_col).value
                            m_start_col = max(mr.min_col, start_col)
                            m_end_col = min(mr.max_col, end_col)
                            if not isinstance(top_val, str) or not top_val.strip():
                                _NEEDS_REVIEW.append(NeedsReview(sheet_name, f"row {row} {mr.coord}", "merged booking range has no text", top_val))
                            else:
                                start_d = _col_to_date(seed, start_col, m_start_col, year, month)
                                end_d = _col_to_date(seed, start_col, m_end_col, year, month)
                                if start_d is None or end_d is None:
                                    _NEEDS_REVIEW.append(NeedsReview(sheet_name, f"row {row} {mr.coord}", "could not resolve date for merged range", top_val))
                                else:
                                    _emit_reservation(reservations, sheet_name, berth_name, berth_length, top_val, start_d, end_d)
                        col = mr.max_col + 1
                        continue

                    cell = wsf.cell(row=row, column=col)
                    value = cell.value
                    text = value.strip() if isinstance(value, str) and value.strip() else None

                    if text is None and _fill_key(cell) in rare_fill_colors:
                        flush_run(col)
                        run_text = None
                        _NEEDS_REVIEW.append(NeedsReview(sheet_name, f"row {row} col {col}", "empty cell has a fill color but no text", None))
                        col += 1
                        continue

                    if text == run_text:
                        col += 1
                        continue

                    flush_run(col)
                    run_text = text
                    run_start_col = col
                    col += 1

                flush_run(end_col + 1)

    berths: list[Berth] = []
    for (name, length), years in berth_registry.items():
        berth_id = _berth_id(name, length)
        active_from = date(min(years), 1, 1)
        active_to = None if max(years) >= max(int(y) for y in year_sheets) else date(max(years), 12, 31)
        length_ft = float(length) if length is not None else None
        berths.append(Berth(id=berth_id, name=name, length_ft=length_ft, active_from=active_from, active_to=active_to))

    return berths, reservations


def _emit_reservation(reservations: list[Reservation], sheet_name: str, berth_name: str, berth_length: int | None, text: str, start_d: date, end_d: date):
    berth_id = _berth_id(berth_name, berth_length)
    res_id = f"R{len(reservations) + 1:05d}"
    if _looks_like_vessel(text):
        vessel_id = _slugify(text)
        label = None
    else:
        vessel_id = None
        label = text
    reservations.append(
        Reservation(
            id=res_id,
            berth_id=berth_id,
            vessel_id=vessel_id,
            label=label,
            start_date=start_d,
            end_date=end_d,
        )
    )


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_WORKBOOK_PATH
    berths, reservations = _load(path)

    print(f"Total reservations extracted: {len(reservations)}")
    if reservations:
        min_d = min(r.start_date for r in reservations)
        max_d = max(r.end_date for r in reservations)
        print(f"Date range covered: {min_d} to {max_d}")
    print(f"Flagged for review: {len(_NEEDS_REVIEW)}")
    print()
    print(f"Distinct berths ({len(berths)}):")
    for b in sorted(berths, key=lambda b: b.name):
        to_str = b.active_to.isoformat() if b.active_to else "present"
        length_str = f"{b.length_ft:.0f}'" if b.length_ft is not None else "length unknown"
        print(f"  - {b.name} ({length_str}) : {b.active_from.isoformat()} -> {to_str}")

    if _NEEDS_REVIEW:
        print()
        print("Sample of flagged items (up to 20):")
        for item in _NEEDS_REVIEW[:20]:
            print(f"  [{item.sheet}] {item.location}: {item.reason} (raw={item.raw_value!r})")


if __name__ == "__main__":
    main()
