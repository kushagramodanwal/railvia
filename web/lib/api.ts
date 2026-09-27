import type {
  Activity, Approval, Block, Completion, Impact, Me, Network, Plan, Report,
  Replan, ReportStatus, StoreStatus, TrafficCase, WindowQuote,
} from "./types";

/** Planning parameters. Kept in one place so every view asks for the same
 *  instance — decisions are keyed by instance_id, and a mismatch would
 *  silently show approvals against the wrong plan. */
export interface PlanParams {
  days: number;
  tasks: number;
  grounded: boolean;
  timeLimit: number;
  /** First day of the horizon, ISO. Empty means the coming Monday. */
  horizonStart: string;
}

const pad = (n: number) => String(n).padStart(2, "0");
export const isoDate = (d: Date) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

export const daysInMonth = (y: number, m: number) =>
  new Date(y, m + 1, 0).getDate();

/** Planning parameters for one calendar month. */
export function monthParams(first: Date): Pick<PlanParams, "horizonStart" | "days"> {
  return {
    horizonStart: isoDate(new Date(first.getFullYear(), first.getMonth(), 1)),
    // The month's real length — February is not 30 days, and a plan running
    // past the end of the month it claims to cover is wrong.
    days: daysInMonth(first.getFullYear(), first.getMonth()),
  };
}

export const DEFAULT_PARAMS: PlanParams = {
  // 10s, not 30: measured, 10 gives a better plan than 30 on this instance.
  // See the note beside DEFAULT_UI_BUDGET in src/api/app.py.
  tasks: 120, grounded: true, timeLimit: 10,
  ...monthParams(new Date()),
};

/** The FastAPI service. Called directly, not through Next's rewrite proxy:
 *  a solve can take 60 seconds and the dev proxy drops the socket long
 *  before that. Override with NEXT_PUBLIC_API_ORIGIN when deploying. */
export const API_ORIGIN =
  process.env.NEXT_PUBLIC_API_ORIGIN ?? "http://localhost:8077";

const qs = (p: PlanParams) => {
  const q = new URLSearchParams({
    grounded: String(p.grounded),
    tasks: String(p.tasks),
    days: String(p.days),
    seed: "42",
    time_limit: String(p.timeLimit),
  });
  if (p.horizonStart) q.set("horizon_start", p.horizonStart);
  return q.toString();
};

/** Attach the caller's Supabase access token. The API verifies it and then
 *  acts as that user against Postgres, so row-level security decides what
 *  they may do. */
const auth = (token?: string): HeadersInit =>
  token ? { Authorization: `Bearer ${token}` } : {};

/** Every call gets a deadline. A request that hangs never rejects, so a
 *  `.catch` never runs and the awaiting code waits forever — which is
 *  exactly how a slow store took the whole app down once. */
const DEADLINE_MS = 90_000;

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      signal: init?.signal ?? AbortSignal.timeout(DEADLINE_MS),
    });
  } catch {
    // A browser reports every network-level failure as the same opaque
    // "Failed to fetch". Nine times out of ten here it means the Python
    // service is not running, so say that rather than repeating the browser.
    throw new Error(
      `Cannot reach the planning API at ${API_ORIGIN}. `
      + "It runs separately from this app — start it with:  "
      + ".venv/bin/uvicorn src.api.app:app --port 8077",
    );
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const getPlan = (p: PlanParams) =>
  json<Plan>(`${API_ORIGIN}/api/plan?${qs(p)}`);

export const getStore = () =>
  json<StoreStatus>(`${API_ORIGIN}/api/store`, {
    // Shorter than the rest: nothing on screen depends on this answer, and a
    // store that takes longer than this is unusable for recording decisions
    // anyway. Failing fast shows the banner instead of a spinner.
    signal: AbortSignal.timeout(12_000),
  });

/** Station positions and section geometry. Fetched once — it does not change
 *  with the plan. */
export const getNetwork = () => json<Network>(`${API_ORIGIN}/api/network`);

/** The named trains a closure stops. Sliced per closure because the full set
 *  is over seven thousand traversals. */
export const getImpact = (sectionId: string, start: string, end: string) =>
  json<Impact>(
    `${API_ORIGIN}/api/impact?${new URLSearchParams({
      section_id: sectionId, start, end,
    })}`,
  );

export const getMe = (token: string) =>
  json<Me>(`${API_ORIGIN}/api/me`, { headers: auth(token) });

export const getDecisions = (instanceId: string, token: string) =>
  json<{ approvals: Approval[]; completions: Completion[] }>(
    `${API_ORIGIN}/api/decisions?instance_id=${encodeURIComponent(instanceId)}`,
    { headers: auth(token) },
  );

export const approve = (instanceId: string, b: Block, token: string) =>
  json<Approval>(`${API_ORIGIN}/api/approvals`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...auth(token) },
    body: JSON.stringify({
      instance_id: instanceId, section_id: b.section_id, start_iso: b.start,
    }),
  });

export const unapprove = (instanceId: string, b: Block, token: string) =>
  json<{ removed: boolean }>(
    `${API_ORIGIN}/api/approvals?${new URLSearchParams({
      instance_id: instanceId, section_id: b.section_id, start_iso: b.start,
    })}`,
    { method: "DELETE", headers: auth(token) },
  );

export const completeJob = (instanceId: string, taskId: string, token: string) =>
  json<Completion>(`${API_ORIGIN}/api/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...auth(token) },
    body: JSON.stringify({ instance_id: instanceId, task_id: taskId }),
  });

export const uncompleteJob = (instanceId: string, taskId: string, token: string) =>
  json<{ removed: boolean }>(
    `${API_ORIGIN}/api/completions?${new URLSearchParams({
      instance_id: instanceId, task_id: taskId,
    })}`,
    { method: "DELETE", headers: auth(token) },
  );

/* ── field intake ────────────────────────────────────────────────────── */

/** The maintenance vocabulary, from the API. Fetched rather than hardcoded:
 *  a form offering work the optimiser has never heard of files reports that
 *  can never be planned. */
export const getActivities = () =>
  json<{ activities: Activity[]; departments: string[] }>(
    `${API_ORIGIN}/api/activities`,
  );

export const getReports = (token: string) =>
  json<{ reports: Report[] }>(`${API_ORIGIN}/api/reports`, {
    headers: auth(token),
  });

export const fileReport = (body: ReportDraft, token: string) =>
  json<Report>(`${API_ORIGIN}/api/reports`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...auth(token) },
    body: JSON.stringify(body),
  });

export const decideReport = (
  id: string, status: ReportStatus, note: string, token: string,
) =>
  json<Report>(`${API_ORIGIN}/api/reports/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...auth(token) },
    body: JSON.stringify({ status, note }),
  });

/** What a standalone closure for this job would cost on this section.
 *  Arithmetic over the traffic profile — no solve, so it can run on every
 *  keystroke of the duration field. */
export const getWindows = (
  sectionId: string, minutes: number, p: PlanParams,
) =>
  json<WindowQuote>(
    `${API_ORIGIN}/api/window?${new URLSearchParams({
      section_id: sectionId, minutes: String(minutes),
      days: String(p.days), tasks: String(p.tasks),
      grounded: String(p.grounded), seed: "42",
      ...(p.horizonStart ? { horizon_start: p.horizonStart } : {}),
    })}`,
  );

/** Everything a report needs at filing time. The rest — id, who filed it,
 *  when, its status — the server fills in and the browser is not trusted to
 *  supply. */
export type ReportDraft = Pick<
  Report,
  "section_id" | "activity_type" | "summary" | "department" | "concerns"
  | "severity" | "emergency" | "duration_minutes" | "crew_required" | "detail"
>;

/** The traffic case behind one closure. Arithmetic, not a solve — safe to
 *  open on any box, and it never re-runs the optimiser. */
export const getTraffic = (
  sectionId: string, start: string, end: string, p: PlanParams,
) =>
  json<TrafficCase>(
    `${API_ORIGIN}/api/traffic?${new URLSearchParams({
      section_id: sectionId, start, end,
      days: String(p.days), tasks: String(p.tasks),
      grounded: String(p.grounded), seed: "42",
      ...(p.horizonStart ? { horizon_start: p.horizonStart } : {}),
    })}`,
  );

/** Re-plan the remainder after an overrun. This one does solve, so it is
 *  slow (up to the time limit) — and on a host with runtime solving off it
 *  returns the constructive schedule, with a status that says so. */
export const replanAfter = (
  sectionId: string, at: string, overrunMinutes: number, p: PlanParams,
) =>
  json<Replan>(
    `${API_ORIGIN}/api/replan?${new URLSearchParams({
      days: String(p.days), tasks: String(p.tasks),
      grounded: String(p.grounded), seed: "42",
      time_limit: String(p.timeLimit),
      ...(p.horizonStart ? { horizon_start: p.horizonStart } : {}),
    })}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        section_id: sectionId, at, overrun_minutes: overrunMinutes,
      }),
    },
  );
