"use client";

import { useState } from "react";
import { usePlanner } from "@/components/PlannerProvider";
import { Fact, Loading } from "@/components/Common";
import { PeriodPicker } from "@/components/PeriodPicker";
import { GanttView } from "@/components/GanttView";
import { DayDetailModal } from "@/components/DayDetailModal";
import { DEPT_VAR, type Block, type Dept } from "@/lib/types";

export default function CalendarPage() {
  const {
    plan, loading, error, approvals, completions, isApproved, division, reports,
  } = usePlanner();
  const [selected, setSelected] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"grid" | "gantt">("grid");
  const [deptFilter, setDeptFilter] = useState<Dept | "ALL">("ALL");

  if (loading) return <Loading what="Optimising track maintenance blocks with CP-SAT…" />;
  if (error) return <div className="err">Could not load the plan: {error}</div>;
  if (!plan) return null;

  // Filter blocks by department if requested
  const filteredBlocks = plan.blocks.filter((b) =>
    deptFilter === "ALL" ? true : b.departments.includes(deptFilter)
  );

  const byDay = new Map<string, Block[]>();
  for (const b of filteredBlocks) {
    const k = new Date(b.start).toDateString();
    if (!byDay.has(k)) byDay.set(k, []);
    byDay.get(k)!.push(b);
  }

  /* Midnight today, so a day is "past" by date rather than by clock time —
     a closure at 02:00 this morning is history, but today's cell is not. */
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);

  /* Emergencies still waiting on the head. These are requests, not placements:
     nothing has scheduled them, and the calendar must not imply otherwise. */
  const emergencies = reports.filter((r) => r.emergency && r.status === "open");

  const first = new Date(plan.horizon_start + "T00:00:00");
  const lead = (first.getDay() + 6) % 7; // 0 = Monday
  const heading = first.toLocaleDateString(undefined, { month: "long", year: "numeric" });

  const approvalRate = plan.block_count > 0 ? (approvals.size / plan.block_count) * 100 : 0;
  const chosenDayBlocks = selected ? byDay.get(selected) ?? [] : [];

  return (
    <>
      <div className="page-header">
        <h1>
          Calendar Schedule
        </h1>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <PeriodPicker />
        </div>
      </div>

      <div className="brief">
        <div className="brief-top">
          <h2>{heading} Overview — {division.name} Division</h2>
          <span style={{ fontSize: 13, color: "var(--text-faint)" }}>
            {division.zone} · {division.sectionsCount} Sections · {plan.horizon_days} Days · {plan.task_total} Jobs
          </span>
        </div>
        <div className="kpi-grid">
          <Fact
            value={String(plan.block_count)}
            label="Closures Scheduled"
          />
          <Fact
            value={`${approvals.size}/${plan.block_count}`}
            label="Approved by Head"
            progress={approvalRate}
            tone={approvalRate > 50 ? "win" : undefined}
          />
          <Fact
            value={String(completions.size)}
            label="Jobs Completed"
          />
          <Fact
            value={`${plan.total_saving.toFixed(0)} h`}
            label="Saved by Sharing"
            tone="win"
          />
          {plan.exceptions.length > 0 && (
            <Fact
              value={String(plan.exceptions.length)}
              label="Unscheduled Conflicts"
              tone="warn"
            />
          )}
        </div>
      </div>

      {emergencies.length > 0 && (
        <div className="emg" role="alert">
          <div className="emg-head">
            <span className="emg-tag">Emergency</span>
            <b>
              {emergencies.length} report{emergencies.length === 1 ? "" : "s"} cannot
              wait for the next planning cycle
            </b>
          </div>
          <ul className="emg-list">
            {emergencies.map((r) => (
              <li key={r.id}>
                <span className="emg-where">
                  {plan.sections[r.section_id] ?? r.section_id}
                  <code>{r.section_id}</code>
                </span>
                <span className="emg-what">{r.summary}</span>
                <span className="emg-who">
                  {[r.department, ...r.concerns].join(" + ")} · {r.reported_by}
                </span>
              </li>
            ))}
          </ul>
          <div className="emg-foot">
            Raised from the field and not yet placed in a plan — the divisional
            head decides these on the <a href="/report">Raise a job</a> register.
          </div>
        </div>
      )}

      {/* Controls Bar: Department Filter & View Switcher */}
      <div className="controls-bar">
        <div className="dept-filters">
          <button
            type="button"
            className={"dept-chip" + (deptFilter === "ALL" ? " active" : "")}
            onClick={() => setDeptFilter("ALL")}
          >
            All Departments
          </button>
          <button
            type="button"
            className={"dept-chip" + (deptFilter === "ENGG" ? " active" : "")}
            onClick={() => setDeptFilter("ENGG")}
          >
            <i style={{ background: DEPT_VAR.ENGG }} /> ENGG Track
          </button>
          <button
            type="button"
            className={"dept-chip" + (deptFilter === "TRD" ? " active" : "")}
            onClick={() => setDeptFilter("TRD")}
          >
            <i style={{ background: DEPT_VAR.TRD }} /> TRD Overhead
          </button>
          <button
            type="button"
            className={"dept-chip" + (deptFilter === "S&T" ? " active" : "")}
            onClick={() => setDeptFilter("S&T")}
          >
            <i style={{ background: DEPT_VAR["S&T"] }} /> S&T Signals
          </button>
        </div>

        <div className="seg-group" role="tablist" aria-label="Schedule View Selector">
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === "grid"}
            aria-pressed={viewMode === "grid"}
            onClick={() => setViewMode("grid")}
          >
            Month Grid
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === "gantt"}
            aria-pressed={viewMode === "gantt"}
            onClick={() => setViewMode("gantt")}
          >
            Gantt Timeline
          </button>
        </div>
      </div>

      {viewMode === "gantt" ? (
        <GanttView
          blocks={filteredBlocks}
          sections={plan.sections}
          onSelectBlock={(b) => setSelected(new Date(b.start).toDateString())}
        />
      ) : (
        <div className="panel">
          <div className="panel-head">
            <h3>Monthly Block Matrix</h3>
            <span style={{ fontSize: 12, color: "var(--text-faint)" }}>
              Click any date to inspect coordinated closures
            </span>
          </div>
          <div className="cal">
            {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
              <div className="dow" key={d}>{d}</div>
            ))}
            {Array.from({ length: lead }, (_, i) => (
              <div className="cell empty" key={`pad${i}`} />
            ))}
            {Array.from({ length: plan.horizon_days }, (_, i) => {
              const day = new Date(first.getTime() + i * 86400000);
              const key = day.toDateString();
              const blocks = byDay.get(key) ?? [];
              const hours = blocks.reduce((a, b) => a + b.train_hours, 0);
              const ok = blocks.filter(isApproved).length;
              const depts = [...new Set(blocks.flatMap((b) => b.departments))];
              const past = day < startOfToday;
              const today = day.getTime() === startOfToday.getTime();
              // Emergencies sit on today, because "as soon as possible" is
              // the only date a request that has not been scheduled has.
              const urgent = today && emergencies.length > 0;

              return (
                <button
                  type="button"
                  key={key}
                  className={"cell" + (blocks.length ? " busy" : "")
                    + (past ? " past" : "") + (today ? " today" : "")
                    + (urgent ? " urgent" : "")}
                  aria-pressed={selected === key}
                  aria-label={
                    `${key}: ${blocks.length} closures, ${hours.toFixed(1)} train-hours lost`
                    + (past ? ", already past" : "")
                    + (urgent ? `, ${emergencies.length} emergency reports waiting` : "")
                  }
                  onClick={() => setSelected(selected === key ? null : key)}
                >
                  <div className="d">
                    <span>{day.getDate()}</span>
                    {today && <span className="day-tag">Today</span>}
                    {past && blocks.length > 0 && <span className="day-tag past">Done</span>}
                    {!past && !today && blocks.length > 0 && ok > 0 && (
                      <span style={{ fontSize: 10, color: "var(--good)", fontWeight: 700 }}>
                        {ok}/{blocks.length} ok
                      </span>
                    )}
                  </div>
                  {urgent && (
                    <div className="cell-emg">
                      {emergencies.length} emergency
                    </div>
                  )}
                  <div className="n">
                    {blocks.length
                      ? `${blocks.length} closure${blocks.length > 1 ? "s" : ""}`
                      : "—"}
                  </div>
                  {blocks.length > 0 && (
                    <>
                      <div className="th">
                        {hours.toFixed(1)} train-h
                      </div>
                      <div className="dots">
                        {depts.map((d) => (
                          <i key={d} style={{ background: DEPT_VAR[d] }} title={d} />
                        ))}
                      </div>
                    </>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Slide-over Drawer for Selected Calendar Day */}
      {selected && (
        <DayDetailModal
          dayDate={new Date(selected)}
          blocks={chosenDayBlocks}
          onClose={() => setSelected(null)}
        />
      )}

    </>
  );
}
