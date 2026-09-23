"""Streamlit demo for non-technical dock staff, built on the real 23-year
workbook via ingest.py -- not sample_data.py."""

from __future__ import annotations

import calendar
from datetime import date

import pandas as pd
import streamlit as st

import ingest
from logic import fits, has_conflict, yearly_usage
from models import Reservation, Vessel

st.set_page_config(page_title="Dock Schedule", layout="wide")


@st.cache_data
def load_data():
    berths, reservations, needs_review = ingest.load_all()
    return berths, reservations, needs_review


berths, reservations, needs_review = load_data()
berths_by_id = {b.id: b for b in berths}

# Widest real date range in the workbook, used to bound the date pickers below
# so 1997-2019 stays clickable (Streamlit defaults date_input to +/-10 years
# around `value`, which cuts off anything before ~2016 when value=today()).
_data_min_date = min((r.start_date for r in reservations), default=date(1997, 1, 1))
_data_max_date = date(date.today().year + 5, 12, 31)  # padded forward so future bookings are still enterable

if "draft_reservations" not in st.session_state:
    st.session_state.draft_reservations = []  # session-only, never written to the real dataset

st.title("Dock Schedule")

tab_schedule, tab_add, tab_quality, tab_usage = st.tabs(
    ["Schedule", "Add a reservation", "Data quality", "Yearly usage"]
)

# ---------------------------------------------------------------------------
# Schedule view
# ---------------------------------------------------------------------------
with tab_schedule:
    st.subheader("Look up a berth's reservations")

    berth_names = sorted(berths_by_id.values(), key=lambda b: b.name)
    berth_labels = {
        f"{b.name} ({b.length_ft:.0f}')" if b.length_ft else f"{b.name} (length unknown)": b.id
        for b in berth_names
    }
    picked_label = st.selectbox("Berth", list(berth_labels.keys()))
    picked_berth_id = berth_labels[picked_label]

    years_available = sorted({r.start_date.year for r in reservations} | {r.end_date.year for r in reservations})
    col1, col2 = st.columns(2)
    with col1:
        picked_year = st.selectbox("Year", years_available, index=len(years_available) - 1)
    with col2:
        picked_month = st.selectbox(
            "Month", list(range(1, 13)), format_func=lambda m: calendar.month_name[m], index=0
        )

    month_start = date(picked_year, picked_month, 1)
    month_end = date(picked_year, picked_month, calendar.monthrange(picked_year, picked_month)[1])

    period_reservations = [
        r
        for r in reservations
        if r.berth_id == picked_berth_id and r.start_date <= month_end and r.end_date >= month_start
    ]
    period_reservations.sort(key=lambda r: r.start_date)

    st.caption(f"Showing {picked_label} for {calendar.month_name[picked_month]} {picked_year}")

    if period_reservations:
        df = pd.DataFrame(
            [
                {
                    "Start": r.start_date.isoformat(),
                    "End": r.end_date.isoformat(),
                    "Nights": (r.end_date - r.start_date).days + 1,
                    "Vessel / event": r.vessel_id or r.label or "(unlabeled)",
                }
                for r in period_reservations
            ]
        )
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No reservations on this berth for the selected month.")

# ---------------------------------------------------------------------------
# Add-reservation form
# ---------------------------------------------------------------------------
with tab_add:
    st.subheader("Try a new reservation (not saved)")
    st.caption("This checks fit and conflicts against the real historical schedule, but nothing here is written back to the workbook.")

    # Outside the form so switching it immediately swaps the fields below,
    # rather than waiting for a submit (widgets inside st.form don't rerun the
    # script until submitted).
    entry_type = st.radio("What are you scheduling?", ["Vessel booking", "Non-vessel event"], horizontal=True)

    with st.form("add_reservation_form"):
        berth_label = st.selectbox("Berth", list(berth_labels.keys()), key="add_berth")
        if entry_type == "Vessel booking":
            vessel_name = st.text_input("Vessel name")
            loa = st.number_input("Vessel LOA in feet (leave at 0 if unknown)", min_value=0.0, step=1.0, value=0.0)
        else:
            event_label = st.text_input("Event label", placeholder="e.g. Community sail day")
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start date", value=date.today(), min_value=_data_min_date, max_value=_data_max_date)
        with col2:
            end_date = st.date_input("End date", value=date.today(), min_value=_data_min_date, max_value=_data_max_date)
        submitted = st.form_submit_button("Check this reservation")

    if submitted:
        berth = berths_by_id[berth_labels[berth_label]]

        if end_date < start_date:
            st.error("End date is before the start date -- fix the dates and try again.")
        elif entry_type == "Vessel booking":
            vessel = Vessel(
                id="draft-vessel",
                name=vessel_name or "(unnamed vessel)",
                loa_ft=loa if loa > 0 else None,
                draft_ft=None,
                category="draft",
                operator_id="draft",
            )
            draft = Reservation(
                id=f"DRAFT-{len(st.session_state.draft_reservations) + 1}",
                berth_id=berth.id,
                vessel_id=vessel.name,
                label=None,
                start_date=start_date,
                end_date=end_date,
            )

            all_known = reservations + st.session_state.draft_reservations
            conflicts = has_conflict(draft, all_known)
            fit_result = fits(vessel, berth)

            if conflicts:
                st.error(f"Conflict: this overlaps {len(conflicts)} existing reservation(s) on {berth.name}:")
                st.dataframe(
                    pd.DataFrame(
                        [
                            {"Start": c.start_date.isoformat(), "End": c.end_date.isoformat(), "Vessel / event": c.vessel_id or c.label or "(unlabeled)"}
                            for c in conflicts
                        ]
                    ),
                    hide_index=True,
                )
            elif fit_result == "FAIL":
                st.error(f"{vessel.name} (LOA {vessel.loa_ft:.0f}') is longer than {berth.name} ({berth.length_ft:.0f}').")
            elif fit_result == "UNKNOWN":
                st.warning(
                    "Can't verify the vessel fits this berth -- "
                    + ("the vessel's LOA wasn't entered" if vessel.loa_ft is None else "this berth has no recorded length in the workbook")
                    + ". Not blocking submission, just flagging it."
                )
            else:
                st.success(f"OK: {vessel.name} fits {berth.name} and there's no scheduling conflict.")

            st.session_state.draft_reservations.append(draft)
        else:
            # Non-vessel event: no length to check, so fits() doesn't apply -- conflict check only.
            draft = Reservation(
                id=f"DRAFT-{len(st.session_state.draft_reservations) + 1}",
                berth_id=berth.id,
                vessel_id=None,
                label=event_label or "(unlabeled event)",
                start_date=start_date,
                end_date=end_date,
            )

            all_known = reservations + st.session_state.draft_reservations
            conflicts = has_conflict(draft, all_known)

            if conflicts:
                st.error(f"Conflict: this overlaps {len(conflicts)} existing reservation(s) on {berth.name}:")
                st.dataframe(
                    pd.DataFrame(
                        [
                            {"Start": c.start_date.isoformat(), "End": c.end_date.isoformat(), "Vessel / event": c.vessel_id or c.label or "(unlabeled)"}
                            for c in conflicts
                        ]
                    ),
                    hide_index=True,
                )
            else:
                st.success(f"OK: no scheduling conflict for '{draft.label}' on {berth.name}.")

            st.session_state.draft_reservations.append(draft)

    if st.session_state.draft_reservations:
        st.caption(f"{len(st.session_state.draft_reservations)} draft reservation(s) this session (not saved):")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Berth": berths_by_id[d.berth_id].name,
                        "Vessel / event": d.vessel_id or d.label or "(unlabeled)",
                        "Start": d.start_date.isoformat(),
                        "End": d.end_date.isoformat(),
                    }
                    for d in st.session_state.draft_reservations
                ]
            ),
            hide_index=True,
        )

# ---------------------------------------------------------------------------
# Data quality panel
# ---------------------------------------------------------------------------
with tab_quality:
    st.subheader("Flagged during import")
    st.caption(
        "The original workbook has 23 years of hand-maintained formatting. Anything the importer "
        "couldn't confidently parse is flagged here instead of guessed -- this is what that looks like."
    )

    if needs_review:
        categories = pd.Series([ingest.categorize_review_reason(item.reason) for item in needs_review])
        counts = categories.value_counts().rename_axis("Category").reset_index(name="Count")
        st.dataframe(counts, hide_index=True, use_container_width=True)

        st.caption(f"{len(needs_review)} total flagged items. Sample below:")
        sample_df = pd.DataFrame(
            [
                {
                    "Sheet": item.sheet,
                    "Location": item.location,
                    "Category": ingest.categorize_review_reason(item.reason),
                    "Reason": item.reason,
                    "Raw value": item.raw_value,
                }
                for item in needs_review[:200]
            ]
        )
        st.dataframe(sample_df, hide_index=True, use_container_width=True)
    else:
        st.info("Nothing flagged.")

# ---------------------------------------------------------------------------
# Yearly usage view
# ---------------------------------------------------------------------------
with tab_usage:
    st.subheader("Berth usage by year")
    st.caption("Replaces the hand-tallied 8YR Dock Summary sheet from the original workbook.")

    usage_year = st.selectbox("Year", years_available, index=len(years_available) - 1, key="usage_year")
    usage = yearly_usage(reservations, berths, usage_year)
    usage_df = pd.DataFrame(sorted(usage.items(), key=lambda kv: -kv[1]), columns=["Berth", "Days booked"])
    st.bar_chart(usage_df.set_index("Berth"))
    st.dataframe(usage_df, hide_index=True, use_container_width=True)
