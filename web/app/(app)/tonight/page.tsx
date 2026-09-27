"use client";

import { useMemo } from "react";
import Link from "next/link";
import { usePlanner } from "@/components/PlannerProvider";
import { BlockRow } from "@/components/BlockRow";
import { Fact, Loading } from "@/components/Common";
import { DEPT_VAR, type Block } from "@/lib/types";

/* The next twenty-four hours.
 *
 * Every other view in this app is built for planning a month. Nobody on
 * shift needs a month. The person coming on duty needs one question
 * answered — what is happening on my division tonight, and has it been
 * granted — and answering it from the month plan means scrolling past three
 * weeks of work that is not theirs.
 *
 * Deliberately derived entirely from the plan already in memory. Opening
 * this page costs nothing and cannot fail on its own.
 */

const WINDOW_HOURS = 24;

const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

const relative = (iso: string, now: number) => {
  const mins = Math.round((new Date(iso).getTime() - now) / 60000);
  if (mins < 0) return "under way";
  if (mins < 60) return `in ${mins} min`;
  const h = Math.floor(mins / 60);
  return `in ${h} h${mins % 60 ? ` ${mins % 60} min` : ""}`;
};

export default function TonightPage() {
  const { plan, loading, error, isApproved } = usePlanner();

  const { soon, now } = useMemo(() => {
    const t = Date.now();
    const end = t + WINDOW_HOURS * 3600_000;
    const list = (plan?.blocks ?? [])
      .filter((b) => {
        const start = new Date(b.start).getTime();
        const finish = new Date(b.end).getTime();
        // Anything overlapping the window, so a closure already under way
        // when the shift begins is not missed.
        return finish >= t && start <= end;
      })
      .sort((a, b) => a.start.localeCompare(b.start));
    return { soon: list, now: t };
  }, [plan]);

  if (loading) return <Loading what="Reading tonight's closures…" />;
  if (error) return <div className="err">Could not load the plan: {error}</div>;
  if (!plan) return null;

  const granted = soon.filter((b) => isApproved(b));
  const waiting = soon.filter((b) => !isApproved(b));
  const trainHours = soon.reduce((sum, b) => sum + b.train_hours, 0);
  const departments = new Set(soon.flatMap((b) => b.departments));

  return (
    <>
      <div className="page-header">
        <h1>Tonight</h1>
        <span className="tn-when">
          {new Date(now).toLocaleString(undefined, {
            weekday: "long", day: "numeric", month: "long",
            hour: "2-digit", minute: "2-digit",
          })} — next {WINDOW_HOURS} hours
        </span>
      </div>

      <div className="brief">
        <div className="kpi-grid">
          <Fact value={String(soon.length)} label="Closures Due" />
          <Fact
            value={`${granted.length}/${soon.length}`}
            label="Granted By Head"
            tone={waiting.length === 0 && soon.length > 0 ? "win" : undefined}
          />
          <Fact value={String(departments.size)} label="Departments On Site" />
          <Fact value={`${trainHours.toFixed(1)} h`} label="Train-Hours At Stake" />
        </div>
      </div>

      {soon.length === 0 ? (
        <div className="empty-state">
          <b>Nothing booked in the next {WINDOW_HOURS} hours</b>
          The line is open across the division. The{" "}
          <Link href="/plan">month plan</Link> shows what comes next.
        </div>
      ) : (
        <>
          {waiting.length > 0 && (
            <div className="tn-alert">
              <b>
                {waiting.length} closure{waiting.length === 1 ? "" : "s"} tonight
                {waiting.length === 1 ? " has" : " have"} not been granted
              </b>
              <span>
                Work cannot start without the divisional head&rsquo;s
                authority. These are listed first.
              </span>
            </div>
          )}

          <div className="tn-list">
            {[...waiting, ...granted].map((b) => (
              <TonightRow key={b.section_id + b.start} block={b} now={now}
                granted={isApproved(b)}
                section={plan.sections[b.section_id] ?? b.section_id} />
            ))}
          </div>
        </>
      )}
    </>
  );
}

function TonightRow({ block, now, granted, section }: {
  block: Block; now: number; granted: boolean; section: string;
}) {
  const started = new Date(block.start).getTime() <= now;
  return (
    <div className={"tn-item" + (granted ? "" : " ungranted") + (started ? " live" : "")}>
      <div className="tn-time">
        <b>{clock(block.start)}</b>
        <span>to {clock(block.end)}</span>
        <em>{relative(block.start, now)}</em>
      </div>
      <div className="tn-body">
        <div className="tn-where">
          {section}<code>{block.section_id}</code>
          {!granted && <span className="tn-flag">Not granted</span>}
          {started && granted && <span className="tn-flag live">Under way</span>}
        </div>
        <div className="jobs">
          {block.tasks.map((t) => (
            <span key={t.id} className={"job" + (t.overdue ? " od" : "")}>
              <i style={{ background: DEPT_VAR[t.department] }} />
              <b>{t.department}</b> · {t.activity.replace(/_/g, " ")}
            </span>
          ))}
        </div>
      </div>
      <div className="tn-cost">
        <b>{block.train_hours.toFixed(1)}</b>
        <span>train-hours</span>
      </div>
      <div className="tn-act"><BlockRow block={block} /></div>
    </div>
  );
}
