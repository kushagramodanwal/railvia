"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import { usePlanner } from "@/components/PlannerProvider";
import { Loading, SetupBanner } from "@/components/Common";
import {
  decideReport, fileReport, getActivities, getWindows, type ReportDraft,
} from "@/lib/api";
import {
  DEPTS, DEPT_FULL, DEPT_VAR, STATUS_LABEL,
  type Activity, type Block, type Dept, type Report, type ReportStatus,
  type WindowQuote,
} from "@/lib/types";

/* The front door.
 *
 * Every other view in this app answers "when should we close the line?".
 * This one answers the question that comes first — "there is something wrong
 * with the track, who needs to know?" — and it is deliberately separate,
 * because the person asking it is standing next to the defect, not sitting
 * in front of a plan.
 *
 * The reason it earns its place is the panel on the right. Filing a report
 * here immediately says whether the line is already being closed for someone
 * else's work, and what a closure of your own would cost if it is not. That
 * comparison is the entire argument of this project, made at the one moment
 * a person can still act on it.
 */

const HHMM = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    weekday: "short", day: "numeric", month: "short",
    hour: "2-digit", minute: "2-digit",
  });

const hours = (minutes: number) =>
  minutes % 60 === 0 ? `${minutes / 60} h` : `${(minutes / 60).toFixed(1)} h`;

/* Supabase answers a missing table with PostgREST's own wording, which says
   "schema cache" and means nothing to anybody. The reports table is new, so
   this is the single most likely first-run failure — name it properly. */
const missingTable = (message: string) =>
  /reports/i.test(message)
    && /(does not exist|schema cache|PGRST205|relation)/i.test(message);

const EMPTY: ReportDraft = {
  section_id: "", activity_type: "", summary: "", department: "ENGG",
  concerns: [], severity: 3, emergency: false, duration_minutes: 120,
  crew_required: 2, detail: "",
};

export default function ReportPage() {
  const {
    plan, store, loading, error, params, reports, reloadReports, reportsError,
  } = usePlanner();
  const { session, me } = useAuth();
  const token = session?.access_token;

  const [tab, setTab] = useState<"new" | "register">("new");
  const [draft, setDraft] = useState<ReportDraft>(EMPTY);
  const [activities, setActivities] = useState<Activity[]>([]);
  const [quote, setQuote] = useState<WindowQuote | null>(null);
  const [busy, setBusy] = useState(false);
  const [filed, setFiled] = useState<Report | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [schemaProblem, setSchemaProblem] = useState(false);

  // The table is missing either way; the provider notices it on load, this
  // page notices it on a failed write.
  const needsSchema = schemaProblem || (!!reportsError && missingTable(reportsError));

  const set = useCallback(
    (patch: Partial<ReportDraft>) => setDraft((d) => ({ ...d, ...patch })), []);

  useEffect(() => { getActivities().then((a) => setActivities(a.activities)).catch(() => {}); }, []);

  /* Default the section to the first one, once the plan names them. */
  useEffect(() => {
    if (!draft.section_id && plan) {
      const first = Object.keys(plan.sections).sort()[0];
      if (first) set({ section_id: first });
    }
  }, [plan, draft.section_id, set]);

  /* Price a standalone closure. Cheap on the server — pure arithmetic over
     the traffic profile — but still debounced, because the duration field
     changes on every keystroke. */
  useEffect(() => {
    if (!draft.section_id || draft.duration_minutes <= 0) { setQuote(null); return; }
    let live = true;
    const timer = setTimeout(() => {
      getWindows(draft.section_id, draft.duration_minutes, params)
        .then((q) => { if (live) setQuote(q); })
        .catch(() => { if (live) setQuote(null); });
    }, 250);
    return () => { live = false; clearTimeout(timer); };
  }, [draft.section_id, draft.duration_minutes, params]);

  /* Closures already planned on this section that are long enough to absorb
     the job. Computed here rather than asked for: the plan is already loaded,
     and this is the comparison that matters.
     Only closures still to come — a report cannot be attached to a handover
     that happened last week, and offering one would be the same mistake the
     window quote avoids on the server. */
  const absorbing: Block[] = useMemo(() => {
    if (!plan || !draft.section_id) return [];
    const now = new Date().toISOString();
    return plan.blocks
      .filter((b) => b.section_id === draft.section_id
        && b.start >= now
        && b.hours * 60 >= draft.duration_minutes)
      .sort((a, b) => a.start.localeCompare(b.start));
  }, [plan, draft.section_id, draft.duration_minutes]);

  const forDept = activities.filter((a) => a.department === draft.department);
  const open = reports.filter((r) => r.status === "open");

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!token) return;
    setBusy(true);
    setProblem(null);
    try {
      // Severity is derived, not asked. A five-point scale in front of
      // someone standing next to a defect is bureaucracy: the decision that
      // actually changes anything is whether it waits for the next cycle.
      // The field stays, because a report becomes a Task later and a Task
      // needs one — it is just not the reporter's to grade.
      const saved = await fileReport(
        { ...draft, severity: draft.emergency ? 5 : 3 }, token,
      );
      setFiled(saved);
      setDraft({ ...EMPTY, section_id: draft.section_id });
      // Shared state, so an emergency filed here lights up the calendar
      // banner and the sidebar badge without a reload.
      reloadReports();
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setSchemaProblem(missingTable(message));
      setProblem(missingTable(message) ? null : message);
    } finally {
      setBusy(false);
    }
  };

  const decide = async (report: Report, status: ReportStatus) => {
    if (!token) return;
    try {
      await decideReport(report.id, status, "", token);
      reloadReports();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
    }
  };

  if (loading) return <Loading what="Loading sections and the current plan…" />;
  if (error) return <div className="err">Could not load: {error}</div>;

  return (
    <>
      <div className="page-header">
        <h1>Raise a Job</h1>
        <div className="seg-group">
          <button type="button" aria-pressed={tab === "new"}
            onClick={() => setTab("new")}>New report</button>
          <button type="button" aria-pressed={tab === "register"}
            onClick={() => setTab("register")}>
            Register{open.length ? ` (${open.length})` : ""}
          </button>
        </div>
      </div>

      {needsSchema && (
        <div className="setup">
          <h3>The reports table is not there yet</h3>
          <div className="note">
            Intake needs a fourth table alongside <code>profiles</code>,{" "}
            <code>approvals</code> and <code>completions</code>. The schema
            file already creates it — it just has not been run since this was
            added. Everything in it is <code>create if not exists</code>, so
            re-running it will not touch the decisions already recorded.
          </div>
          <pre>{`Supabase dashboard → SQL editor → paste and run:

  src/store/schema.sql`}</pre>
        </div>
      )}

      {!store?.connected ? <SetupBanner /> : tab === "new" ? (
        <div className="intake">
          <form className="panel intake-form" onSubmit={submit}>
            <div className="panel-head">
              <h3>What have you found?</h3>
            </div>

            <div className="field">
              <label htmlFor="summary">In one line</label>
              <input id="summary" required maxLength={200} value={draft.summary}
                placeholder="Cracked fishplate at km 21/4, down line"
                onChange={(e) => set({ summary: e.target.value })} />
            </div>

            <div className="field">
              <label htmlFor="section">Where</label>
              <select id="section" value={draft.section_id}
                onChange={(e) => set({ section_id: e.target.value })}>
                {plan && Object.entries(plan.sections)
                  .sort((a, b) => a[1].localeCompare(b[1]))
                  .map(([id, name]) => (
                    <option key={id} value={id}>{name} ({id})</option>
                  ))}
              </select>
            </div>

            <div className="field">
              <label>Whose asset is it?</label>
              <div className="dept-filters">
                {DEPTS.map((d) => (
                  <button key={d} type="button" title={DEPT_FULL[d]}
                    className={"dept-chip" + (draft.department === d ? " active" : "")}
                    onClick={() => set({
                      department: d,
                      concerns: draft.concerns.filter((c) => c !== d),
                      activity_type: "",
                    })}>
                    <i style={{ background: DEPT_VAR[d] }} />{d}
                  </button>
                ))}
              </div>
              <p className="hint">{DEPT_FULL[draft.department]}</p>
            </div>

            <div className="field">
              <label>Who else must be on site?</label>
              <div className="dept-filters">
                {DEPTS.filter((d) => d !== draft.department).map((d) => {
                  const on = draft.concerns.includes(d);
                  return (
                    <button key={d} type="button"
                      className={"dept-chip" + (on ? " active" : "")}
                      onClick={() => set({
                        concerns: on
                          ? draft.concerns.filter((c) => c !== d)
                          : [...draft.concerns, d],
                      })}>
                      <i style={{ background: DEPT_VAR[d] }} />{d}
                    </button>
                  );
                })}
              </div>
              <p className="hint">
                An overhead isolation before track work, a signal
                disconnection before a point machine is opened. Naming them
                here is what turns three closures into one.
              </p>
            </div>

            <div className="field">
              <label htmlFor="activity">What work does it need?</label>
              <select id="activity" required value={draft.activity_type}
                onChange={(e) => {
                  const spec = forDept.find((a) => a.activity_type === e.target.value);
                  set({
                    activity_type: e.target.value,
                    ...(spec ? {
                      duration_minutes: spec.typical_minutes,
                      crew_required: spec.typical_crew,
                    } : {}),
                  });
                }}>
                <option value="" disabled>Choose an activity…</option>
                {forDept.map((a) => (
                  <option key={a.activity_type} value={a.activity_type}>{a.label}</option>
                ))}
              </select>
              <p className="hint">
                The same list the planner schedules from, so this report can
                actually be placed. Choosing one fills in its usual duration
                and crew — correct them if this job differs.
              </p>
            </div>

            <label className={"emergency" + (draft.emergency ? " on" : "")}>
              <input type="checkbox" checked={draft.emergency}
                onChange={(e) => set({ emergency: e.target.checked })} />
              <span>
                <b>This will not wait for the next planning cycle</b>
                Emergency work is placed before the plan is next solved, and
                needs the divisional head now rather than at the next review.
              </span>
            </label>

            <div className="field-row">
              <div className="field">
                <label htmlFor="mins">How long, in minutes</label>
                <input id="mins" type="number" min={15} step={15}
                  value={draft.duration_minutes}
                  onChange={(e) => set({
                    duration_minutes: Math.max(1, Number(e.target.value) || 0),
                  })} />
              </div>
              <div className="field">
                <label htmlFor="crew">Crews needed</label>
                <input id="crew" type="number" min={1} max={12}
                  value={draft.crew_required}
                  onChange={(e) => set({
                    crew_required: Math.max(1, Number(e.target.value) || 1),
                  })} />
              </div>
            </div>

            <div className="field">
              <label htmlFor="detail">Anything else</label>
              <textarea id="detail" rows={3} value={draft.detail}
                placeholder="Measurements, what you have already done, access notes…"
                onChange={(e) => set({ detail: e.target.value })} />
            </div>

            {problem && <div className="err">{problem}</div>}

            <div className="form-foot">
              <button type="submit" className="primary" disabled={busy || !token}>
                {busy ? "Filing…" : "File this report"}
              </button>
              <span className="hint">
                Filed as {me?.email ?? "you"}. Everyone in the division sees
                it; the head decides whether it goes into the plan.
              </span>
            </div>
          </form>

          <aside className="intake-side">
            {filed && (
              <div className="filed">
                <b>Report filed</b>
                <span>
                  “{filed.summary}” is now in front of the divisional head.
                </span>
              </div>
            )}

            <div className="panel assess">
              <div className="panel-head"><h3>What this would cost</h3></div>

              {absorbing.length > 0 ? (
                <div className="assess-body good">
                  <div className="assess-lead">
                    The line is <b>already being closed here</b>.
                  </div>
                  <p>
                    {absorbing.length === 1 ? "One closure is" : `${absorbing.length} closures are`}
                    {" "}planned on this section this month with room for
                    {" "}{hours(draft.duration_minutes)} of work. Attaching this
                    job to one of them costs <b>no new closure</b> and no
                    further train-hours — the track is already handed over.
                  </p>
                  <ul className="cand">
                    {absorbing.slice(0, 3).map((b) => (
                      <li key={b.start}>
                        <span className="mono">{HHMM(b.start)}</span>
                        <span className="cand-meta">
                          {hours(Math.round(b.hours * 60))} ·{" "}
                          {b.departments.map((d) => (
                            <i key={d} style={{ background: DEPT_VAR[d] }} title={d} />
                          ))}
                          {" "}{b.departments.join(" + ")}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : quote && quote.candidates.length > 0 ? (
                <div className="assess-body">
                  <div className="assess-lead">
                    Nothing is planned here yet.
                  </div>
                  <p>
                    On its own this job needs its own closure. The quietest
                    {" "}{hours(draft.duration_minutes)} window on this section costs
                    {" "}<b>{quote.candidates[0].train_hours} train-hours</b>.
                  </p>
                  <ul className="cand">
                    {quote.candidates.slice(0, 3).map((c) => (
                      <li key={c.start}>
                        <span className="mono">{HHMM(c.start)}</span>
                        <span className="cand-meta">{c.train_hours} train-h</span>
                      </li>
                    ))}
                  </ul>
                  <p className="hint">
                    Only {Math.round(quote.permitted_share * 100)}% of this
                    section&rsquo;s month is quiet enough to block at all,
                    which is why placement is not a matter of picking a night.
                  </p>
                </div>
              ) : quote?.horizon_over ? (
                <div className="assess-body warn">
                  <div className="assess-lead">
                    This month has already run out.
                  </div>
                  <p>
                    Every window on this section that fits{" "}
                    {hours(draft.duration_minutes)} is now in the past. File
                    the report anyway — it does not expire — but pick a later
                    month on the calendar to see when it could be done.
                  </p>
                </div>
              ) : quote ? (
                <div className="assess-body warn">
                  <div className="assess-lead">
                    {hours(draft.duration_minutes)} does not fit here.
                  </div>
                  <p>
                    No quiet stretch on this section is long enough for a job
                    this size, so it cannot be done under a normal traffic
                    block. Either split it, or it needs a traffic block —
                    which is a different authority&rsquo;s decision.
                  </p>
                </div>
              ) : (
                <div className="assess-body"><p className="hint">
                  Choose a section and a duration.
                </p></div>
              )}

              {draft.emergency && quote && (
                <div className="assess-body urgent">
                  <div className="assess-lead">Soonest possible</div>
                  {quote.earliest ? (
                    <p>
                      <span className="mono">{HHMM(quote.earliest.start)}</span> —
                      the first window on this section that has not already
                      passed, costing {quote.earliest.train_hours} train-hours.
                    </p>
                  ) : (
                    <p>
                      Nothing left this month. Emergency work that cannot wait
                      for a quiet window needs a traffic block, granted by the
                      divisional head against the running timetable.
                    </p>
                  )}
                </div>
              )}

              {draft.concerns.length > 0 && (
                <div className="assess-body">
                  <div className="assess-lead">
                    {[draft.department, ...draft.concerns].join(" + ")} together
                  </div>
                  <p>
                    Filed as one report this is one closure. Filed
                    separately — which is what happens today — it is
                    {" "}{1 + draft.concerns.length}.
                  </p>
                </div>
              )}
            </div>
          </aside>
        </div>
      ) : (
        <Register reports={reports} canDecide={Boolean(me?.can_approve)}
          sections={plan?.sections ?? {}} onDecide={decide} problem={problem} />
      )}
    </>
  );
}

function Register({ reports, canDecide, sections, onDecide, problem }: {
  reports: Report[];
  canDecide: boolean;
  sections: Record<string, string>;
  onDecide: (r: Report, s: ReportStatus) => void;
  problem: string | null;
}) {
  if (reports.length === 0) {
    return (
      <div className="empty-state">
        <b>Nothing has been reported yet</b>
        Defects raised from the field appear here, in front of all three
        departments at once, before any closure is booked.
      </div>
    );
  }
  return (
    <>
      {problem && <div className="err">{problem}</div>}
      <div className="reg">
        {reports.map((r) => (
          <article key={r.id}
            className={"rep " + r.status + (r.emergency ? " urgent" : "")}>
            <div className="rep-main">
              <div className="rep-top">
                {r.emergency && <span className="tag-urgent">Emergency</span>}
                <b>{r.summary}</b>
              </div>
              <div className="rep-meta">
                <span className="where">
                  {sections[r.section_id] ?? r.section_id}
                  <code>{r.section_id}</code>
                </span>
                <span className="jobs">
                  {[r.department, ...r.concerns].map((d) => (
                    <span className="job" key={d}>
                      <i style={{ background: DEPT_VAR[d as Dept] }} />{d}
                    </span>
                  ))}
                </span>
                <span className="hint">
                  {r.activity_type.replace(/_/g, " ")} ·{" "}
                  {hours(r.duration_minutes)} · {r.crew_required} crew
                </span>
              </div>
              {r.detail && <p className="rep-detail">{r.detail}</p>}
              <div className="hint">
                {r.reported_by} · {new Date(r.reported_at).toLocaleString()}
              </div>
            </div>
            <div className="rep-side">
              <span className={"rep-status " + r.status}>
                {STATUS_LABEL[r.status]}
              </span>
              {canDecide && r.status === "open" ? (
                <div className="acts">
                  <button type="button" onClick={() => onDecide(r, "accepted")}>
                    Accept
                  </button>
                  <button type="button" onClick={() => onDecide(r, "rejected")}>
                    Turn down
                  </button>
                </div>
              ) : r.decided_by ? (
                <span className="hint">by {r.decided_by}</span>
              ) : (
                <span className="hint">
                  {canDecide ? "" : "Only the divisional head decides."}
                </span>
              )}
            </div>
          </article>
        ))}
      </div>
    </>
  );
}
