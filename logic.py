"""Scheduling rules over the clean models from models.py."""

from __future__ import annotations

from datetime import date

from models import Berth, Reservation, Vessel


def fits(vessel: Vessel, berth: Berth) -> str:
    """"OK"/"FAIL" by length only (no draft/tide check yet); "UNKNOWN" when either
    length is unrecorded (e.g. loa_ft missing, or a berth like North Finger Piers
    that has no footage in the workbook)."""
    if vessel.loa_ft is None or berth.length_ft is None:
        return "UNKNOWN"
    return "OK" if vessel.loa_ft <= berth.length_ft else "FAIL"


def overlaps(start1: date, end1: date, start2: date, end2: date) -> bool:
    return start1 <= end2 and start2 <= end1


def has_conflict(new_reservation: Reservation, existing_reservations: list[Reservation]) -> list[Reservation]:
    return [
        r
        for r in existing_reservations
        if r.id != new_reservation.id
        and r.berth_id == new_reservation.berth_id
        and overlaps(new_reservation.start_date, new_reservation.end_date, r.start_date, r.end_date)
    ]


def yearly_usage(reservations: list[Reservation], berths: list[Berth], year: int) -> dict[str, int]:
    berth_name_by_id = {b.id: b.name for b in berths}
    usage = {b.name: 0 for b in berths}
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)

    for r in reservations:
        name = berth_name_by_id.get(r.berth_id)
        if name is None or not overlaps(r.start_date, r.end_date, year_start, year_end):
            continue
        clipped_start = max(r.start_date, year_start)
        clipped_end = min(r.end_date, year_end)
        usage[name] += (clipped_end - clipped_start).days + 1

    return usage
