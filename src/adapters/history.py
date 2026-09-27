"""History supply, on the adapter side of the boundary.

The criticality model needs past maintenance outcomes. Today those come from
the generator; one day they would come from TMS/SMMS/TDMS defect history. The
ML layer therefore talks to this interface and never imports the generator,
the same rule the optimiser follows.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from src.models import Section


class HistorySource(ABC):
    """Supplies past maintenance observations with their outcomes."""

    provenance: str = "unspecified"
    is_synthetic: bool = True

    @abstractmethod
    def records(self, sections: list[Section], n_records: int, as_of: date) -> list:
        """Return HistoryRecord entries."""


class SyntheticHistorySource(HistorySource):
    """Generated history. The only source available today."""

    is_synthetic = True
    provenance = (
        "SYNTHETIC maintenance history from a modelled failure hazard. "
        "See ASSUMPTIONS.md (A-08) — we wrote the hazard the model learns."
    )

    def __init__(self, seed: int = 7) -> None:
        self.seed = seed

    def records(self, sections: list[Section], n_records: int, as_of: date) -> list:
        # The adapter layer is the one place permitted to know the generator.
        from src.generator.history import build_history

        return build_history(sections, n_records=n_records, seed=self.seed, as_of=as_of)
