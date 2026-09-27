"""Persistence boundary for planning decisions.

What actually needs storing is small: which proposed closures a planner has
approved, and which jobs have been reported done. Everything else in this
system is reproducible — instances rebuild byte-identically from a seed, and
the timetable is a set of cached files.

But approvals are exactly the thing that must NOT live in a browser. An
approval a colleague cannot see, with no record of who made it or when, is
the one part of this a railway would object to. So it gets a real store with
a real audit trail.

Supabase (hosted Postgres) is the only implementation, deliberately. A local
fallback would let two planners approve different things and never find out,
which is worse than being told the store is unreachable. When Supabase is
down, approving stops and says so; planning is unaffected, because the
planner is a pure function of its inputs and needs no store.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def now_iso() -> str:
    """One timestamp format across every record, so an audit trail sorts."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Approval(BaseModel):
    """One planner accepting one proposed closure."""

    instance_id: str
    section_id: str
    start_iso: str
    decided_by: str = "demo-planner"
    decided_at: str = Field(default_factory=now_iso)
    note: str = ""

    @property
    def key(self) -> str:
        return f"{self.section_id}@{self.start_iso}"


class Completion(BaseModel):
    """One maintenance job reported done."""

    instance_id: str
    task_id: str
    completed_at: str = Field(default_factory=now_iso)
    completed_by: str = "demo-planner"
    note: str = ""


class ReportStatus(str, Enum):
    """Where a filed report has got to.

    Deliberately short. A report is either waiting to be looked at, taken
    into the plan, or turned down — anything finer is process theatre.
    """

    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Report(BaseModel):
    """A defect or work request raised from the field.

    This is the front door. Today each department raises its own through its
    own system, which is precisely why the same section gets closed three
    times — nobody sees the other two requests until the closures are already
    booked. One intake form, shared by all three, is the smallest change that
    makes co-location possible at all.

    A report is NOT a scheduled task. It is a request, and it stays a request
    until the divisional head accepts it. Accepted reports join the backlog
    the planner draws from on its next run — they do not re-solve the current
    plan, which is precomputed. See the intake note in ASSUMPTIONS.md.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    section_id: str
    activity_type: str
    summary: str = Field(min_length=1, max_length=200)

    #: The department that owns the asset and will do the work.
    department: str
    #: Others whose presence the work requires — an OHE isolation for track
    #: work, a signal disconnection for point work. These are the reason a
    #: closure is shared rather than repeated.
    concerns: list[str] = Field(default_factory=list)

    severity: int = Field(default=3, ge=1, le=5)
    #: True when the defect will not wait for the next planning cycle.
    emergency: bool = False
    duration_minutes: int = Field(default=120, gt=0)
    crew_required: int = Field(default=2, ge=1)
    detail: str = ""

    status: ReportStatus = ReportStatus.OPEN
    reported_by: str = "unknown"
    reported_at: str = Field(default_factory=now_iso)
    decided_by: str = ""
    decided_at: str = ""
    decision_note: str = ""

    @property
    def departments(self) -> list[str]:
        """Everyone who has to be on site, owner first, no duplicates."""
        seen = [self.department]
        seen += [d for d in self.concerns if d not in seen]
        return seen


class Store(ABC):
    """Where planning decisions are recorded."""

    #: Shown in the UI so nobody has to guess where their approval went.
    backend: str = "unknown"
    shared: bool = False

    @abstractmethod
    def approve(self, approval: Approval) -> Approval: ...

    @abstractmethod
    def unapprove(self, instance_id: str, section_id: str, start_iso: str) -> None: ...

    @abstractmethod
    def approvals(self, instance_id: str) -> list[Approval]: ...

    @abstractmethod
    def complete(self, completion: Completion) -> Completion: ...

    @abstractmethod
    def uncomplete(self, instance_id: str, task_id: str) -> None: ...

    @abstractmethod
    def completions(self, instance_id: str) -> list[Completion]: ...

    @abstractmethod
    def file_report(self, report: Report) -> Report: ...

    @abstractmethod
    def reports(self) -> list[Report]: ...

    @abstractmethod
    def decide_report(
        self, report_id: str, status: ReportStatus, decided_by: str, note: str
    ) -> Report: ...

    def describe(self) -> str:
        scope = "shared" if self.shared else "this machine only"
        return f"{self.backend} ({scope})"
