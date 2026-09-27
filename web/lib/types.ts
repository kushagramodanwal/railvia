export type Dept = "ENGG" | "TRD" | "S&T";

export interface Division {
  id: string;
  name: string;
  zone: string;
  sectionsCount: number;
}

export const DIVISIONS: Division[] = [
  { id: "DLI", name: "Delhi", zone: "Northern Railway (NR)", sectionsCount: 39 },
  { id: "UMB", name: "Ambala", zone: "Northern Railway (NR)", sectionsCount: 28 },
  { id: "MB", name: "Moradabad", zone: "Northern Railway (NR)", sectionsCount: 34 },
  { id: "MMCT", name: "Mumbai Central", zone: "Western Railway (WR)", sectionsCount: 42 },
  { id: "HWH", name: "Howrah", zone: "Eastern Railway (ER)", sectionsCount: 45 },
  { id: "SBC", name: "Bengaluru", zone: "South Western Railway (SWR)", sectionsCount: 30 },
];

export interface Job {
  id: string;
  activity: string;
  department: Dept;
  severity: number;
  overdue: boolean;
}

export interface Block {
  section_id: string;
  start: string;
  end: string;
  hours: number;
  train_hours: number;
  departments: Dept[];
  shared: boolean;
  tasks: Job[];
  separate_cost: number;
  saving: number;
  overdue_count: number;
}

export interface Exception {
  id: string;
  section: string;
  activity: string;
  department: Dept;
  severity: number;
  overdue: boolean;
  due: string;
  criticality: number;
  reason: string;
  fix: string;
}

export interface Plan {
  instance_id: string;
  status: string;
  wall_time: number;
  train_hours_lost: number;
  blocks: Block[];
  block_count: number;
  scheduled: number;
  task_total: number;
  shared_blocks: number;
  unscheduled: string[];
  exceptions: Exception[];
  late_tasks: number;
  total_saving: number;
  horizon_start: string;
  horizon_days: number;
  sections: Record<string, string>;
}

export interface StoreStatus {
  connected: boolean;
  backend: string;
  shared: boolean;
  detail: string;
}

export interface Approval {
  instance_id: string;
  section_id: string;
  start_iso: string;
  decided_by: string;
  decided_at: string;
  note: string;
}

export interface Completion {
  instance_id: string;
  task_id: string;
  completed_at: string;
  completed_by: string;
  note: string;
}

export const DEPT_VAR: Record<Dept, string> = {
  ENGG: "var(--engg)",
  TRD: "var(--trd)",
  "S&T": "var(--snt)",
};

export const blockKey = (b: Pick<Block, "section_id" | "start">) =>
  `${b.section_id}@${b.start}`;

export type Role = "head" | "engineer";

/** Who is signed in and what they may do. Supplied by the API, which reads
 *  the role from Postgres under row-level security — never trusted from the
 *  browser. */
export interface Me {
  user_id: string;
  email: string;
  role: Role;
  can_approve: boolean;
  can_complete: boolean;
}

export const ROLE_LABEL: Record<Role, string> = {
  head: "Divisional head",
  engineer: "Section engineer",
};

export interface Station { name: string; lat: number | null; lng: number | null; }

/** One section, as /api/network sends it.
 *
 * Geometry only. The endpoint deliberately trims the full section record —
 * no train lists, no hourly profile — so these are the only fields that
 * exist here, whatever `_network()` holds internally. */
export interface NetworkSection {
  id: string;
  a: string;
  b: string;
  name: string;
  length_km: number | null;
  daily_trains: number;
  /** Busiest hour, trains/hour. */
  peak: number;
}

export interface Network {
  stations: Record<string, Station>;
  sections: NetworkSection[];
  corridors: string[][];
}

export interface AffectedTrain {
  number: string; name: string; entry: number; exit: number | null;
  days: number[]; type: string; at: string;
}

export interface Impact {
  section_id: string; section_name: string;
  start: string; end: string;
  affected_count: number; trains: AffectedTrain[];
}

/* ── field intake ──────────────────────────────────────────────────────
 *
 * A report is what an engineer files when they find something wrong. It is a
 * request, not a scheduled job: it becomes work the planner can place only
 * once the divisional head accepts it.
 */

export type ReportStatus = "open" | "accepted" | "rejected";

export interface Report {
  id: string;
  section_id: string;
  activity_type: string;
  summary: string;
  /** The department that owns the asset and will do the work. */
  department: Dept;
  /** Others who must attend — an OHE isolation, a signal disconnection.
   *  This is the co-location signal: it is why one closure serves two. */
  concerns: Dept[];
  severity: number;
  emergency: boolean;
  duration_minutes: number;
  crew_required: number;
  detail: string;
  status: ReportStatus;
  reported_by: string;
  reported_at: string;
  decided_by: string;
  decided_at: string;
  decision_note: string;
}

/** One entry from the maintenance catalogue. Served by the API rather than
 *  hardcoded here, so the form can only offer work the planner knows how to
 *  schedule. */
export interface Activity {
  activity_type: string;
  label: string;
  department: Dept;
  interval_days: number;
  typical_minutes: number;
  typical_crew: number;
  co_locatable: boolean;
  source: string;
}

export interface QuietWindow {
  start: string;
  end: string;
  train_hours: number;
}

export interface WindowQuote {
  section_id: string;
  section_name: string;
  minutes: number;
  candidates: QuietWindow[];
  earliest: QuietWindow | null;
  permitted_share: number;
  /** True when the month being planned has already run out — a different
   *  fact from the job not fitting, and it needs different words. */
  horizon_over: boolean;
}

export const STATUS_LABEL: Record<ReportStatus, string> = {
  open: "Awaiting the head",
  accepted: "Accepted into the backlog",
  rejected: "Turned down",
};

export const DEPTS: Dept[] = ["ENGG", "TRD", "S&T"];

export const DEPT_FULL: Record<Dept, string> = {
  ENGG: "Permanent way — track, ballast, rails, bridges",
  TRD: "Traction distribution — overhead equipment",
  "S&T": "Signal & telecommunications",
};

/** The traffic case for one closure: why this hour, and not another.
 *  Everything else the explanation needs is already in the loaded plan. */
export interface TrafficCase {
  section_id: string;
  section_name: string;
  /** Trains per hour, index 0–23. The section's own daily shape. */
  profile: number[];
  peak: number;
  peak_hour: number;
  quietest: number;
  daily_trains: number;
  /** An hour is blockable only at or below this, measured per section. */
  threshold: number;
  percentile: number;
  blockable_hours: number[];
  permitted_share: number;
  window: {
    hours: number[];
    mean_trains_per_hour: number;
    train_hours: number;
    /** The same closure in the section's busiest hour — the counterfactual
     *  that shows the placement was not arbitrary. */
    at_peak_train_hours: number;
  } | Record<string, never>;
}

/** What happens to the rest of the month after something overruns.
 *
 * `delta` is positive when the disruption cost train-hours, and it often is:
 * the horizon has shrunk and the overrun ate a quiet window other work
 * needed. A re-planner that always claimed an improvement would not be
 * measuring anything, so the UI shows this signed and unhidden.
 */
export interface Replan {
  section_id: string;
  section_name: string;
  at: string;
  overrun_minutes: number;
  description: string;
  status: string;
  wall_time: number;
  completed: number;
  carried: number;
  /** What the original month-long plan had booked for this stretch.
   *  Context only — comparing against it credits the disruption with the
   *  benefit of a second, smaller solve. */
  train_hours_before: number;
  /** The same leftover work re-solved with nothing gone wrong. This is the
   *  like-for-like baseline. */
  train_hours_control: number;
  train_hours_after: number;
  /** The disruption's own cost: after minus control. The only figure worth
   *  quoting, and it is signed. */
  delta: number;
  /** What a naive reading would have reported. Kept so the difference can be
   *  shown rather than quietly corrected. */
  delta_vs_original: number;
  blocks_before: number;
  blocks_after: number;
  blocks_control: number;
  scheduled_after: number;
  unplaceable: number;
  unplaceable_control: number;
  blocks: Block[];
}
