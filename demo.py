"""Sanity-check script: proves logic.py works against the real 23-year
workbook (not sample_data.py) before building the Streamlit UI on top of it."""

from datetime import date

import ingest
from logic import fits, has_conflict, yearly_usage
from models import Vessel


def main():
    berths = ingest.load_berths()
    reservations = ingest.load_reservations()

    print("=" * 60)
    print("LOAD SUMMARY")
    print("=" * 60)
    print(f"Total berths: {len(berths)}")
    print(f"Total reservations: {len(reservations)}")
    print()

    # --- has_conflict() example -------------------------------------------
    print("=" * 60)
    print("has_conflict() EXAMPLE")
    print("=" * 60)
    by_berth = {}
    for r in reservations:
        by_berth.setdefault(r.berth_id, []).append(r)

    natural_pair = None
    for berth_id, rs in by_berth.items():
        rs_sorted = sorted(rs, key=lambda r: r.start_date)
        for i, a in enumerate(rs_sorted):
            for b in rs_sorted[i + 1:]:
                if a.start_date <= b.end_date and b.start_date <= a.end_date:
                    natural_pair = (a, b)
                    break
            if natural_pair:
                break
        if natural_pair:
            break

    if natural_pair:
        existing_res, conflicting_res = natural_pair
        print("Found two real reservations that already overlap on the same berth:")
        print(f"  Existing:    {existing_res}")
        print(f"  Overlapping: {conflicting_res}")
        conflicts = has_conflict(conflicting_res, [r for r in reservations if r.id != conflicting_res.id])
        print(f"  has_conflict() correctly flags {len(conflicts)} conflict(s): {[c.id for c in conflicts]}")
    else:
        # fallback: construct a hypothetical booking against a real, busy berth
        sample_berth_id = max(by_berth, key=lambda k: len(by_berth[k]))
        existing_res = by_berth[sample_berth_id][0]
        hypothetical = existing_res.__class__(
            id="HYPOTHETICAL",
            berth_id=sample_berth_id,
            vessel_id="test-vessel",
            label=None,
            start_date=existing_res.start_date,
            end_date=existing_res.end_date,
        )
        print("No naturally-overlapping pair found; constructed a hypothetical booking against real data:")
        print(f"  Existing real reservation: {existing_res}")
        print(f"  Hypothetical new booking:  {hypothetical}")
        conflicts = has_conflict(hypothetical, reservations)
        print(f"  has_conflict() correctly flags {len(conflicts)} conflict(s): {[c.id for c in conflicts]}")
    print()

    # --- fits() examples -----------------------------------------------------
    print("=" * 60)
    print("fits() EXAMPLES")
    print("=" * 60)
    berths_with_length = [b for b in berths if b.length_ft is not None]
    berths_without_length = [b for b in berths if b.length_ft is None]

    small_berth = min(berths_with_length, key=lambda b: b.length_ft)
    large_berth = max(berths_with_length, key=lambda b: b.length_ft)

    small_vessel = Vessel(id="demo-small", name="Demo Vessel (short)", loa_ft=30.0, draft_ft=None, category="demo", operator_id="demo")
    big_vessel = Vessel(id="demo-big", name="Demo Vessel (too long)", loa_ft=1000.0, draft_ft=None, category="demo", operator_id="demo")

    print(f"OK example:      {small_vessel.name} (LOA {small_vessel.loa_ft}') vs {large_berth.name} ({large_berth.length_ft}') -> {fits(small_vessel, large_berth)}")
    print(f"FAIL example:    {big_vessel.name} (LOA {big_vessel.loa_ft}') vs {small_berth.name} ({small_berth.length_ft}') -> {fits(big_vessel, small_berth)}")

    if berths_without_length:
        unknown_berth = berths_without_length[0]
        print(f"UNKNOWN example: {small_vessel.name} (LOA {small_vessel.loa_ft}') vs {unknown_berth.name} (length unrecorded) -> {fits(small_vessel, unknown_berth)}")
    print()

    # --- yearly_usage() example -----------------------------------------------
    print("=" * 60)
    print("yearly_usage() EXAMPLE")
    print("=" * 60)
    sample_year = 2015
    usage = yearly_usage(reservations, berths, sample_year)
    print(f"Days booked per berth in {sample_year}:")
    name_width = max(len(name) for name in usage) + 2
    for name, days in sorted(usage.items(), key=lambda kv: -kv[1]):
        print(f"  {name:<{name_width}} {days:>4} days")


if __name__ == "__main__":
    main()
