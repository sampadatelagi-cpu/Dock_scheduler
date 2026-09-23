from dataclasses import dataclass, field
from datetime import date


@dataclass
class Berth:
    id: str
    name: str
    length_ft: float | None  # None for berth categories the workbook never gives a footage for (e.g. "North Finger Piers")
    active_from: date
    active_to: date | None = None


@dataclass
class Operator:
    id: str
    name: str
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)


@dataclass
class Vessel:
    id: str
    name: str
    loa_ft: float | None
    draft_ft: float | None
    category: str
    operator_id: str


@dataclass
class Reservation:
    id: str
    berth_id: str
    vessel_id: str | None
    label: str | None
    start_date: date
    end_date: date


@dataclass
class Tour:
    id: str
    vessel_id: str
    date: date
    time: str | None
    guide: str
    guest_name: str
    guest_org: str
    headcount: int | None
    status: str
    notes: str
