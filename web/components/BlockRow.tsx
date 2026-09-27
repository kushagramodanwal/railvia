"use client";

import { useState } from "react";
import { BlockNotice } from "./BlockNotice";
import { ExplainDrawer } from "./ExplainDrawer";
import { Portal } from "./Portal";
import { usePlanner } from "./PlannerProvider";
import { useAuth } from "./AuthProvider";
import { Icon, PATH } from "./icons";
import type { Block, Job } from "@/lib/types";
import { blockKey, DEPT_VAR } from "@/lib/types";

function JobChip({ job, done }: { job: Job; done: boolean }) {
  return (
    <span className={"job" + (job.overdue && !done ? " od" : "")}>
      <i style={{ background: DEPT_VAR[job.department] ?? "var(--text-faint)" }} />
      <span style={{ fontWeight: 700 }}>{job.department}</span>
      <span>·</span>
      <span>{job.activity.replace(/_/g, " ")}</span>
      {done ? " · done" : job.overdue ? " · overdue" : ""}
    </span>
  );
}

export function BlockRow({ block, showDate = false }: {
  block: Block; showDate?: boolean;
}) {
  const {
    plan, store, isApproved, isDone, toggleApproval, toggleDone, approvals,
  } = usePlanner();
  const { me } = useAuth();
  const [busy, setBusy] = useState<"approve" | "done" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [explaining, setExplaining] = useState(false);
  const [issuing, setIssuing] = useState(false);

  const approved = isApproved(block);
  const done = isDone(block);
  const connected = !!store?.connected;

  /* A closure that has already happened cannot be granted. Leaving the
     button live invites approving last Tuesday, which is the kind of thing
     that makes a planning tool look like a mock-up. */
  const isPast = new Date(block.start) < new Date();

  const canApprove = connected && !!me?.can_approve && !isPast;
  const canComplete = connected && !!me?.can_complete;
  const approveWhy = !connected
    ? "Connect Supabase to record decisions"
    : !me?.can_approve
      ? "Only the divisional head can grant a closure"
      : isPast
        ? "This closure has already passed — it can no longer be granted"
        : undefined;

  const start = new Date(block.start);
  const end = new Date(block.end);
  const sameDay = start.toDateString() === end.toDateString();
  const sectionName = plan?.sections?.[block.section_id] ?? block.section_id;
  const record = approvals.get(`${block.section_id}@${block.start}`);

  const run = async (which: "approve" | "done", fn: () => Promise<void>) => {
    setBusy(which); setErr(null);
    try { await fn(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(null); }
  };

  return (
    <div className={"block" + (block.shared ? " shared" : "")
      + (block.overdue_count && !done ? " has-overdue" : "")
      + (done ? " done" : "") + (isPast ? " past" : "")}>
      <div className="when">
        <div>{start.toTimeString().slice(0, 5)}–{end.toTimeString().slice(0, 5)}</div>
        <small>
          {showDate
            ? start.toLocaleDateString(undefined, { day: "numeric", month: "short" }) + " · "
            : ""}
          {block.hours} h window{sameDay ? "" : " (+1d)"}
        </small>
      </div>

      <div>
        <div className="where">
          <span>{sectionName}</span>
          <code>{block.section_id}</code>
          {block.shared && (
            <span style={{
              fontSize: 10, fontWeight: 700, color: "var(--good)",
              background: "var(--good-soft)", padding: "2px 8px", borderRadius: 999
            }}>
              Coordinated ({block.departments.length} Depts)
            </span>
          )}
        </div>
        <div className="jobs">
          {block.tasks.map((t) => (
            <JobChip key={t.id} job={t} done={isDone(block)} />
          ))}
        </div>
        {record && (
          <div className="meta">
            Approved by <b>{record.decided_by}</b> on{" "}
            {new Date(record.decided_at).toLocaleString()}
          </div>
        )}
        {err && <div className="meta" style={{ color: "var(--bad)" }}>{err}</div>}
      </div>

      <div className="cost">
        <b>{block.train_hours.toFixed(1)}</b>
        <span>train-hours</span>
        {block.saving > 0.05 && (
          <span className="save">⚡ Saves {block.saving.toFixed(1)}h by sharing</span>
        )}
        <div className="acts">
          <button type="button" className="why-btn"
            onClick={() => setExplaining(true)}
            title="Why this section, this hour, these jobs together">
            Why?
          </button>
          <button type="button" className={approved ? "on" : ""}
            disabled={!canApprove || busy !== null}
            aria-pressed={approved}
            title={approveWhy}
            onClick={() => run("approve", () => toggleApproval(block))}>
            {approved && <Icon d={PATH.check} size={13} />}
            {busy === "approve" ? "…"
              : approved ? "Approved"
                : isPast ? "Passed" : "Approve"}
          </button>
          <button type="button" className="notice-btn"
            onClick={() => setIssuing(true)}
            title="The permission notice for this closure">
            Notice
          </button>
          <button type="button" className={done ? "on" : ""}
            disabled={!canComplete || busy !== null}
            aria-pressed={done}
            title={canComplete ? undefined : "Connect Supabase to record decisions"}
            onClick={() => run("done", () => toggleDone(block))}>
            {done && <Icon d={PATH.check} size={13} />}
            {busy === "done" ? "…" : done ? "Done" : "Mark done"}
          </button>
        </div>
      </div>
      {/* Portalled out of this row. `.block.done` and `.block.past` dim
          themselves with opacity, which composites every descendant — these
          panels included — so rendered here they came out faded. */}
      {explaining && (
        <Portal>
          <ExplainDrawer block={block} onClose={() => setExplaining(false)} />
        </Portal>
      )}
      {issuing && (
        <Portal>
          <BlockNotice block={block} approval={approvals.get(blockKey(block))}
            onClose={() => setIssuing(false)} />
        </Portal>
      )}
    </div>
  );
}
