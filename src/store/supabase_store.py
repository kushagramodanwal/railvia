"""Supabase (hosted Postgres) store.

Configured with two environment variables, read from .env like the RailRadar
key:

    SUPABASE_URL=https://<project>.supabase.co
    SUPABASE_KEY=<anon or service key>

Run `src/store/schema.sql` in the Supabase SQL editor once to create the
tables.

Failure policy: if Supabase is unreachable this raises and the API answers
503 saying so. There is no local fallback on purpose — see the note in
`src/store/__init__.py`. Planning is unaffected either way, because the
planner needs no store at all.
"""

from __future__ import annotations

import logging
import os

from src.store.base import (
    Approval, Completion, Report, ReportStatus, Store, now_iso,
)

log = logging.getLogger(__name__)

URL_VAR = "SUPABASE_URL"
KEY_VAR = "SUPABASE_KEY"

# The browser bundle needs its own copy of these, and Next only exposes
# variables prefixed NEXT_PUBLIC_ to client code — a deliberate guard against
# shipping a secret in a public bundle. That leaves the same two values
# needing two names, which is a trap: set only the NEXT_PUBLIC_ pair and
# sign-in works while every approval fails.
#
# So the server falls back to the prefixed names. Safe, because this is the
# anon key: it is designed to be public, and row-level security is what
# protects the data. A deployment using a service key sets SUPABASE_KEY
# explicitly, which still wins.
URL_FALLBACK = "NEXT_PUBLIC_SUPABASE_URL"
KEY_FALLBACK = "NEXT_PUBLIC_SUPABASE_ANON_KEY"


def configured_url() -> str | None:
    return os.environ.get(URL_VAR) or os.environ.get(URL_FALLBACK)


def configured_key() -> str | None:
    return os.environ.get(KEY_VAR) or os.environ.get(KEY_FALLBACK)


class SupabaseNotConfigured(RuntimeError):
    pass


# Every call to Supabase gets a deadline.
#
# Without one the client waits forever: measured here, create_client returned
# in 0.22s and the first query never came back at all, while curl to the same
# project answered in half a second. A request that cannot fail cannot be
# caught either, so the API hung, and with it the whole UI — which had no
# business waiting on the store to draw a plan.
#
# Ten seconds is far longer than a healthy round trip (~0.5s) and far shorter
# than a person will wait before deciding the page is broken.
REQUEST_TIMEOUT_SECONDS = 10


class SupabaseStore(Store):
    backend = "Supabase"
    shared = True

    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
        access_token: str | None = None,
    ) -> None:
        url = url or configured_url()
        key = key or configured_key()
        if not url or not key:
            missing = [n for n, v in ((URL_VAR, url), (KEY_VAR, key)) if not v]
            # Say it in terms of wherever this is actually running. Telling
            # someone to edit .env on a server that has no .env sends them
            # looking for a file that is not there.
            where = (
                "your hosting provider's environment variables"
                if os.environ.get("RENDER") or os.environ.get("PORT")
                else ".env in the repo root (see .env.example)"
            )
            raise SupabaseNotConfigured(
                f"{' and '.join(missing)} not set. Set "
                f"{' and '.join(missing)} in {where}, then restart."
            )
        try:
            from supabase import ClientOptions, create_client
        except ImportError as exc:  # pragma: no cover
            raise SupabaseNotConfigured("supabase package not installed") from exc

        self.client = create_client(url, key, options=ClientOptions(
            postgrest_client_timeout=REQUEST_TIMEOUT_SECONDS,
            storage_client_timeout=REQUEST_TIMEOUT_SECONDS,
            function_client_timeout=REQUEST_TIMEOUT_SECONDS,
        ))
        if access_token:
            # Act AS the signed-in user, so Postgres row-level security
            # decides what they may do. Without this every request would run
            # as the anonymous key and the role policies would be bypassed —
            # the API would be enforcing its own opinion instead of the
            # database enforcing the rule.
            self.client.postgrest.auth(access_token)
        self.access_token = access_token
        # Fail here rather than on the planner's first approval.
        self.client.table("approvals").select("instance_id").limit(1).execute()
        log.info("Supabase store connected (%s)",
                 "as user" if access_token else "anonymous")

    def role(self) -> str | None:
        """The signed-in user's role, or None when not signed in.

        Read from `profiles`, which RLS restricts to the caller's own row.
        """
        if not self.access_token:
            return None
        res = self.client.table("profiles").select("role").limit(1).execute()
        rows = res.data or []
        return rows[0]["role"] if rows else None

    def approve(self, approval: Approval) -> Approval:
        self.client.table("approvals").upsert(
            approval.model_dump(),
            on_conflict="instance_id,section_id,start_iso",
        ).execute()
        return approval

    def unapprove(self, instance_id: str, section_id: str, start_iso: str) -> None:
        (self.client.table("approvals").delete()
            .eq("instance_id", instance_id)
            .eq("section_id", section_id)
            .eq("start_iso", start_iso)
            .execute())

    def approvals(self, instance_id: str) -> list[Approval]:
        res = (self.client.table("approvals").select("*")
               .eq("instance_id", instance_id)
               .order("decided_at", desc=True).execute())
        return [Approval(**row) for row in (res.data or [])]

    def complete(self, completion: Completion) -> Completion:
        self.client.table("completions").upsert(
            completion.model_dump(), on_conflict="instance_id,task_id"
        ).execute()
        return completion

    def uncomplete(self, instance_id: str, task_id: str) -> None:
        (self.client.table("completions").delete()
            .eq("instance_id", instance_id).eq("task_id", task_id).execute())

    def completions(self, instance_id: str) -> list[Completion]:
        res = (self.client.table("completions").select("*")
               .eq("instance_id", instance_id)
               .order("completed_at", desc=True).execute())
        return [Completion(**row) for row in (res.data or [])]

    # ── field reports ────────────────────────────────────────────────────
    #
    # Reports differ from approvals and completions in one way that matters:
    # they are not keyed to an instance. A cracked fishplate is a fact about
    # the track, not about whichever month's plan happened to be open when
    # somebody noticed it, and it stays true across replans.

    def file_report(self, report: Report) -> Report:
        self.client.table("reports").upsert(
            report.model_dump(mode="json"), on_conflict="id"
        ).execute()
        return report

    def reports(self) -> list[Report]:
        res = (self.client.table("reports").select("*")
               .order("reported_at", desc=True).execute())
        return [Report(**row) for row in (res.data or [])]

    def decide_report(
        self, report_id: str, status: ReportStatus, decided_by: str, note: str
    ) -> Report:
        res = (self.client.table("reports")
               .update({
                   "status": status.value,
                   "decided_by": decided_by,
                   "decided_at": now_iso(),
                   "decision_note": note,
               })
               .eq("id", report_id).execute())
        rows = res.data or []
        if not rows:
            # Either the id is wrong or RLS refused the update. Postgres
            # returns an empty set for both, so say both.
            raise LookupError(
                f"no report {report_id} was updated — either it does not "
                "exist, or only the divisional head may decide it"
            )
        return Report(**rows[0])
