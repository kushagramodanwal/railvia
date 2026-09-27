"""The adapter boundary.

This is the seam where real Indian Railways feeds would attach. Everything
upstream of it is department-specific and outside our control; everything
downstream speaks only src.models.

Enforced rule (PROJECT_BRIEF.md section 10): the optimiser imports
`DataSource`. It must never import `src.generator`. If that import ever
appears in src/optimiser, the boundary has been broken and the claim "real
feeds plug in here" stops being true.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.models import PlanningInstance


class DataSource(ABC):
    """Supplies one PlanningInstance from somewhere."""

    #: Human-readable statement of where this data came from. Surfaced in the
    #: UI and the CLI so synthetic data can never be mistaken for live data.
    provenance: str = "unspecified"

    #: False only for adapters reading a genuine railway system.
    is_synthetic: bool = True

    #: True only once this source can actually return data.
    is_connected: bool = True

    @abstractmethod
    def load(self) -> PlanningInstance:
        """Return a fully populated, referentially valid planning instance."""

    def describe(self) -> str:
        # A stub must never label itself LIVE. Nothing in this system is
        # allowed to overstate the reality of its data source.
        if not self.is_connected:
            tag = "NOT CONNECTED"
        elif self.is_synthetic:
            tag = "SYNTHETIC"
        else:
            tag = "LIVE"
        return f"[{tag}] {type(self).__name__}: {self.provenance}"


class NotYetIntegrated(NotImplementedError):
    """Raised by the real-feed stubs.

    These stubs exist to make the integration point visible and typed, not to
    pretend integration has happened.
    """


class _RealFeedAdapter(DataSource):
    """Base for the four real-system adapters we cannot yet connect to."""

    system_name: str = "unknown"
    supplies: str = ""
    is_synthetic = False
    is_connected = False

    def __init__(self, connection_string: str | None = None) -> None:
        self.connection_string = connection_string

    @property
    def provenance(self) -> str:  # type: ignore[override]
        return f"{self.system_name} (not connected) — would supply {self.supplies}"

    def load(self) -> PlanningInstance:
        raise NotYetIntegrated(
            f"{self.system_name} is an internal Indian Railways system and is "
            f"not accessible to this project. This adapter defines the "
            f"integration contract: it would supply {self.supplies}, mapped "
            f"onto src.models. Use SyntheticDataSource until a feed exists."
        )


class TMSAdapter(_RealFeedAdapter):
    """Track Management System — the ENGG department's defect and task store."""

    system_name = "TMS"
    supplies = "ENGG tasks (track defects, permanent way activities) and section metadata"


class SMMSAdapter(_RealFeedAdapter):
    """Signalling maintenance management system — S&T's defect and task store."""

    system_name = "SMMS"
    supplies = "S&T tasks (signal gear, point machines, cabling)"


class TDMSAdapter(_RealFeedAdapter):
    """Traction distribution maintenance system — TRD's defect and task store."""

    system_name = "TDMS"
    supplies = "TRD tasks (overhead equipment inspection and repair)"


class COAAdapter(_RealFeedAdapter):
    """Control Office Application — timetable and corridor availability."""

    system_name = "COA"
    supplies = "TrafficWindow data (train timetable, goods forecast, corridor windows)"


REAL_FEED_ADAPTERS: tuple[type[_RealFeedAdapter], ...] = (
    TMSAdapter,
    SMMSAdapter,
    TDMSAdapter,
    COAAdapter,
)
