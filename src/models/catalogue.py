"""Maintenance activity catalogue: the kinds of work that need a block.

This sits beside the models, not in the generator, because it is shared
vocabulary rather than a way of inventing data. The generator draws jobs from
it; the intake form offers it to whoever is filing a defect. If it lived in
the generator, the API could not name an activity without importing the
generator — which the adapter boundary forbids, and the boundary test
enforces. `calendar.py` moved here for the same reason.

PROVENANCE WARNING (PROJECT_BRIEF.md section 3)
-----------------------------------------------
Every periodicity below is PROVISIONAL. Phase 0 exists to prove the data
model and pipeline, not to be defensible in front of judges. Phase 2
replaces each `interval_days` with a value read from the Indian Railways
Permanent Way Manual (IRPWM), the AC Traction Manual, or the Signal
Engineering Manual, and records the clause number in the `source` field.

We deliberately do NOT write clause numbers we have not read. A fabricated
citation is worse than an admitted gap. Anything still reading
"PROVISIONAL" is a known debt tracked in ASSUMPTIONS.md (A-01).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.models.core import Department


@dataclass(frozen=True)
class ActivitySpec:
    """One kind of maintenance work, with its mandated periodicity."""

    activity_type: str
    department: Department
    interval_days: int
    duration_minutes_range: tuple[int, int]
    crew_range: tuple[int, int]
    co_locatable: bool
    source: str

    @property
    def label(self) -> str:
        return self.activity_type.replace("_", " ").title()


# Blocks in Indian Railways practice are typically granted in 2-4 hour
# windows; durations below sit inside that envelope. See ASSUMPTIONS.md (A-03).
CATALOGUE: tuple[ActivitySpec, ...] = (
    # --- ENGG: permanent way -------------------------------------------------
    ActivitySpec(
        "through_packing", Department.ENGG, 365, (150, 240), (2, 3), True,
        "PROVISIONAL — IRPWM through packing periodicity, cite in Phase 2",
    ),
    ActivitySpec(
        "usfd_rail_testing", Department.ENGG, 180, (90, 180), (1, 2), True,
        "PROVISIONAL — USFD frequency is GMT-dependent, cite in Phase 2",
    ),
    ActivitySpec(
        "points_and_crossings_overhaul", Department.ENGG, 180, (120, 240), (2, 3), True,
        "PROVISIONAL — IRPWM P&C maintenance, cite in Phase 2",
    ),
    ActivitySpec(
        "ballast_deep_screening", Department.ENGG, 1825, (210, 240), (3, 4), False,
        "PROVISIONAL — deep screening cycle, cite in Phase 2",
    ),
    ActivitySpec(
        "lwr_destressing", Department.ENGG, 365, (180, 240), (2, 3), False,
        "PROVISIONAL — LWR manual destressing, cite in Phase 2",
    ),
    # --- TRD: overhead equipment ---------------------------------------------
    ActivitySpec(
        "ohe_tension_length_inspection", Department.TRD, 180, (90, 150), (1, 2), True,
        "PROVISIONAL — AC Traction Manual, cite in Phase 2",
    ),
    ActivitySpec(
        "ohe_insulator_cleaning", Department.TRD, 180, (60, 120), (1, 2), True,
        "PROVISIONAL — AC Traction Manual, cite in Phase 2",
    ),
    ActivitySpec(
        "ohe_wire_wear_measurement", Department.TRD, 365, (90, 180), (2, 2), True,
        "PROVISIONAL — AC Traction Manual, cite in Phase 2",
    ),
    # --- S&T: signalling ------------------------------------------------------
    ActivitySpec(
        "point_machine_maintenance", Department.SNT, 90, (60, 120), (1, 2), True,
        "PROVISIONAL — Signal Engineering Manual, cite in Phase 2",
    ),
    ActivitySpec(
        "track_circuit_adjustment", Department.SNT, 90, (60, 90), (1, 1), True,
        "PROVISIONAL — Signal Engineering Manual, cite in Phase 2",
    ),
    ActivitySpec(
        "signal_gear_overhaul", Department.SNT, 180, (120, 180), (2, 2), True,
        "PROVISIONAL — Signal Engineering Manual, cite in Phase 2",
    ),
    ActivitySpec(
        "cable_megger_test", Department.SNT, 365, (90, 150), (1, 2), True,
        "PROVISIONAL — Signal Engineering Manual, cite in Phase 2",
    ),
)


def by_department(dept: Department) -> list[ActivitySpec]:
    return [a for a in CATALOGUE if a.department == dept]
