"""The one DataSource that actually returns data today."""

from __future__ import annotations

from datetime import date

from src.adapters.base import DataSource
from src.models import PlanningInstance


class SyntheticDataSource(DataSource):
    """Serves generated data, clearly labelled as generated."""

    is_synthetic = True

    def __init__(
        self,
        seed: int = 42,
        n_tasks: int = 20,
        horizon_days: int = 7,
        n_sections: int | None = 5,
        horizon_start: date | None = None,
    ) -> None:
        self.seed = seed
        self.n_tasks = n_tasks
        self.horizon_days = horizon_days
        self.n_sections = n_sections
        self.horizon_start = horizon_start

    @property
    def provenance(self) -> str:  # type: ignore[override]
        return (
            f"generated, seed={self.seed}, {self.n_sections} sections, "
            f"{self.n_tasks} tasks, {self.horizon_days}-day horizon"
        )

    def load(self) -> PlanningInstance:
        # Imported here, not at module scope: this is the only file in the
        # codebase permitted to know the generator exists.
        from src.generator.synthetic import generate_instance

        kwargs = dict(
            seed=self.seed,
            n_tasks=self.n_tasks,
            horizon_days=self.horizon_days,
            n_sections=self.n_sections,
        )
        if self.horizon_start is not None:
            kwargs["horizon_start"] = self.horizon_start
        return generate_instance(**kwargs)


class JSONFileDataSource(DataSource):
    """Replays a previously generated instance from disk.

    Used so a demo can run from a frozen file rather than re-generating, and
    so the exact instance behind a quoted number can be committed.
    """

    def __init__(self, path: str) -> None:
        self.path = path

    @property
    def provenance(self) -> str:  # type: ignore[override]
        return f"replayed from {self.path}"

    def load(self) -> PlanningInstance:
        with open(self.path) as fh:
            instance = PlanningInstance.model_validate_json(fh.read())
        # is_synthetic is computed from the instance's own provenance record,
        # so a replayed file cannot misreport what it contains.
        self.is_synthetic = instance.is_synthetic
        instance.validate_referential_integrity()
        return instance
