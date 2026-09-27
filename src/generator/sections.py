"""Section list and traffic archetypes for the Phase 0 tiny instance.

Sections are real Northern Railway (Delhi division) inter-station stretches.
Using real names from a real division from day one keeps the synthetic
instance recognisable to anyone who knows the territory.

PROVENANCE (PROJECT_BRIEF.md section 3):
  - Station names and their ordering on the route: real.
  - length_km: APPROXIMATE. Phase 2 replaces these with distances from the
    Northern Railway Working Time Table.
  - traffic_density_profile: HAND-BUILT ARCHETYPES, not measured. Phase 2
    derives them from published zonal timetables (departures per hour
    counted from the public timetable). Tracked in ASSUMPTIONS.md (A-02).
"""

from __future__ import annotations

from src.models import Section

# Trains per hour, index = hour of day (0..23). Hand-built shapes chosen so
# that night hours are unambiguously the cheapest time to block, which is the
# behaviour the optimiser must discover. See ASSUMPTIONS.md (A-02).
TRAFFIC_ARCHETYPES: dict[str, list[float]] = {
    # Dense passenger/EMU corridor: sharp morning and evening commuter peaks.
    "suburban_trunk": [
        2, 1, 1, 1, 2, 4,        # 00-05
        8, 12, 14, 13, 11, 9,    # 06-11
        8, 7, 7, 8, 9, 12,       # 12-17
        14, 13, 10, 7, 5, 3,     # 18-23
    ],
    # Mixed passenger and goods: flatter, and busy at night with freight.
    "mixed_trunk": [
        5, 5, 4, 4, 5, 6,
        7, 9, 10, 9, 8, 7,
        7, 6, 6, 7, 8, 9,
        10, 9, 8, 6, 6, 5,
    ],
    # Lightly used branch: never exceeds the peak-hour block threshold.
    "branch_line": [
        0, 0, 1, 1, 1, 2,
        3, 4, 4, 3, 3, 2,
        2, 2, 2, 3, 3, 4,
        4, 3, 2, 2, 1, 1,
    ],
}

# (id, name, approx length_km, archetype)
_SECTION_SPECS: tuple[tuple[str, str, float, str], ...] = (
    ("NDLS-DSA", "New Delhi - Shahdara", 7.0, "suburban_trunk"),
    ("DSA-SBB", "Shahdara - Sahibabad", 6.5, "suburban_trunk"),
    ("SBB-GZB", "Sahibabad - Ghaziabad", 5.5, "mixed_trunk"),
    ("NDLS-OKA", "New Delhi - Okhla", 9.0, "mixed_trunk"),
    ("OKA-FDB", "Okhla - Faridabad", 14.0, "branch_line"),
)

DIVISION = "Delhi (Northern Railway)"


def build_sections() -> list[Section]:
    return [
        Section(
            id=sid,
            name=name,
            division=DIVISION,
            length_km=km,
            traffic_density_profile=list(TRAFFIC_ARCHETYPES[arch]),
        )
        for sid, name, km, arch in _SECTION_SPECS
    ]


def archetype_of(section_id: str) -> str:
    for sid, _, _, arch in _SECTION_SPECS:
        if sid == section_id:
            return arch
    raise KeyError(section_id)
