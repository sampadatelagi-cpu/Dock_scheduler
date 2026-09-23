from datetime import date

from logic import fits, has_conflict, overlaps, yearly_usage
from models import Berth, Reservation, Vessel


def make_berth(id="b1", name="Test Berth", length_ft=100.0):
    return Berth(id=id, name=name, length_ft=length_ft, active_from=date(2000, 1, 1))


def make_vessel(loa_ft=80.0):
    return Vessel(id="v1", name="Test Vessel", loa_ft=loa_ft, draft_ft=None, category="test", operator_id="op1")


def test_fits_pass():
    assert fits(make_vessel(loa_ft=80.0), make_berth(length_ft=100.0)) == "OK"


def test_fits_fail():
    assert fits(make_vessel(loa_ft=150.0), make_berth(length_ft=100.0)) == "FAIL"


def test_fits_unknown():
    assert fits(make_vessel(loa_ft=None), make_berth(length_ft=100.0)) == "UNKNOWN"
    assert fits(make_vessel(loa_ft=80.0), make_berth(length_ft=None)) == "UNKNOWN"


def test_conflict_detected():
    existing = [Reservation("R1", "b1", "v1", None, date(2020, 6, 1), date(2020, 6, 10))]
    new = Reservation("R2", "b1", "v2", None, date(2020, 6, 5), date(2020, 6, 15))
    conflicts = has_conflict(new, existing)
    assert conflicts == existing


def test_no_conflict_on_adjacent_dates():
    existing = [Reservation("R1", "b1", "v1", None, date(2020, 6, 1), date(2020, 6, 10))]
    new = Reservation("R2", "b1", "v2", None, date(2020, 6, 11), date(2020, 6, 15))
    assert has_conflict(new, existing) == []


def test_no_conflict_different_berth():
    existing = [Reservation("R1", "b1", "v1", None, date(2020, 6, 1), date(2020, 6, 10))]
    new = Reservation("R2", "b2", "v2", None, date(2020, 6, 5), date(2020, 6, 15))
    assert has_conflict(new, existing) == []


def test_yearly_usage_sums_correctly():
    berths = [make_berth(id="b1", name="Berth One"), make_berth(id="b2", name="Berth Two")]
    reservations = [
        Reservation("R1", "b1", "v1", None, date(2020, 1, 1), date(2020, 1, 10)),  # 10 days
        Reservation("R2", "b1", "v2", None, date(2020, 12, 28), date(2021, 1, 3)),  # clipped to 4 days in 2020
        Reservation("R3", "b2", "v3", None, date(2019, 1, 1), date(2019, 1, 5)),  # outside the year
    ]
    usage = yearly_usage(reservations, berths, 2020)
    assert usage["Berth One"] == 14
    assert usage["Berth Two"] == 0
