"use client";

import { useState } from "react";
import { usePlanner } from "@/components/PlannerProvider";
import { BlockRow } from "@/components/BlockRow";
import { Fact, Loading } from "@/components/Common";
import { PeriodPicker } from "@/components/PeriodPicker";
import { Icon, PATH } from "@/components/icons";
import { DEPT_VAR, type Block, type Dept } from "@/lib/types";

/** A run of closures with a heading each time the date changes. Its own
 *  component so the running "current day" resets per list — shared between
 *  two lists it would suppress the first heading of the second. */
function BlockList({ blocks }: { blocks: Block[] }) {
  let currentDay: string | null = null;
  return (
    <>
      {blocks.map((b) => {
        const day = new Date(b.start).toDateString();
        const heading = day !== currentDay ? day : null;
        currentDay = day;
        return (
          <div key={b.section_id + b.start}>
            {heading && (
              <div className="day">
                {new Date(heading).toLocaleDateString(undefined, {
                  weekday: "long", day: "numeric", month: "long", year: "numeric",
                })}
              </div>
            )}
            <BlockRow block={b} />
          </div>
        );
      })}
    </>
  );
}

export default function PlanPage() {
  const { plan, loading, error, approvals } = usePlanner();
  const [deptFilter, setDeptFilter] = useState<Dept | "ALL">("ALL");
  const [searchTerm, setSearchTerm] = useState("");

  if (loading) return <Loading what="Generating optimal block schedule…" />;
  if (error) return <div className="err">Could not load the plan: {error}</div>;
  if (!plan) return null;

  const jobCoverageRate = plan.task_total > 0 ? (plan.scheduled / plan.task_total) * 100 : 0;

  // Filter blocks by search term and department filter
  const filteredBlocks = plan.blocks.filter((b) => {
    const secName = (plan.sections[b.section_id] ?? b.section_id).toLowerCase();
    const matchesSearch =
      secName.includes(searchTerm.toLowerCase()) ||
      b.section_id.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesDept =
      deptFilter === "ALL" ? true : b.departments.includes(deptFilter);
    return matchesSearch && matchesDept;
  });

  /* A month plan is opened in the middle of that month, and the list is in
     date order — so without this the first thing on the page is a fortnight
     of closures that already happened and cannot be acted on. They are not
     hidden, because the record matters, but they go behind the work. */
  const now = new Date().toISOString();
  const upcoming = filteredBlocks.filter((b) => b.start >= now);
  const passed = filteredBlocks.filter((b) => b.start < now);

  return (
    <>
      <div className="page-header">
        <h1>Master Block Plan</h1>
        <PeriodPicker />
      </div>

      <div className="brief">
        <div className="brief-top">
          <h2>
            {new Date(plan.horizon_start + "T00:00:00")
              .toLocaleDateString(undefined, { month: "long", year: "numeric" })} Plan Schedule
          </h2>
          <span style={{ fontSize: 13, color: "var(--text-faint)" }}>
            CP-SAT Optimiser · {plan.block_count} Coordinated Windows
          </span>
        </div>
        <div className="kpi-grid">
          <Fact
            value={String(upcoming.length)}
            label="Closures Still To Come"
          />
          <Fact
            value={`${plan.scheduled}/${plan.task_total}`}
            label="Jobs Scheduled"
            progress={jobCoverageRate}
            tone={jobCoverageRate > 80 ? "win" : undefined}
          />
          <Fact
            value={`${plan.total_saving.toFixed(0)} h`}
            label="Saved by Sharing"
            tone="win"
          />
          <Fact
            value={`${approvals.size}/${plan.block_count}`}
            label="Head Approvals"
          />
          {plan.exceptions.length > 0 && (
            <Fact
              value={String(plan.exceptions.length)}
              label="Need Controller Decision"
              tone="warn"
            />
          )}
        </div>
      </div>

      {/* Exception / Conflict Banner */}
      {plan.exceptions.length > 0 && (
        <details className="exc" open={plan.exceptions.length <= 8}>
          <summary>
            <Icon d={PATH.warn} size={16} />
            {plan.exceptions.length} maintenance tasks unscheduled — requires manual review
          </summary>
          <div className="exc-body">
            {plan.exceptions.slice(0, 40).map((e) => (
              <div className="exc-row" key={e.id}>
                <span className="job">
                  <i style={{ background: DEPT_VAR[e.department] }} />
                  <b style={{ textTransform: "uppercase" }}>{e.department}</b>
                </span>
                <div>
                  <div style={{ fontWeight: 700 }}>
                    {e.activity.replace(/_/g, " ")} on{" "}
                    <span style={{ color: "var(--primary)" }}>
                      {plan.sections[e.section] ?? e.section}
                    </span>
                  </div>
                  <div className="why">Reason: {e.reason}</div>
                  <div className="fix">Recommendation: {e.fix}</div>
                </div>
                <div className="cost">
                  <b style={{
                    fontSize: 12,
                    color: e.overdue ? "var(--bad)" : undefined,
                  }}>
                    {e.overdue ? "OVERDUE" : `due ${e.due.slice(5)}`}
                  </b>
                  <span>Severity {e.severity}</span>
                </div>
              </div>
            ))}
            {plan.exceptions.length > 40 && (
              <div className="exc-row" style={{ fontStyle: "italic", color: "var(--text-faint)" }}>
                …and {plan.exceptions.length - 40} additional unscheduled requests
              </div>
            )}
          </div>
        </details>
      )}

      {/* Search and Filters */}
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
            <i style={{ background: DEPT_VAR.ENGG }} /> ENGG
          </button>
          <button
            type="button"
            className={"dept-chip" + (deptFilter === "TRD" ? " active" : "")}
            onClick={() => setDeptFilter("TRD")}
          >
            <i style={{ background: DEPT_VAR.TRD }} /> TRD
          </button>
          <button
            type="button"
            className={"dept-chip" + (deptFilter === "S&T" ? " active" : "")}
            onClick={() => setDeptFilter("S&T")}
          >
            <i style={{ background: DEPT_VAR["S&T"] }} /> S&T
          </button>
        </div>

        <input
          type="text"
          placeholder="Filter by section code or name…"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          style={{ minWidth: 260 }}
        />
      </div>

      {filteredBlocks.length === 0 ? (
        <div className="empty-state">
          <b>No matching closures found</b>
          Try adjusting your search query or department filter.
        </div>
      ) : (
        <>
          {upcoming.length === 0 ? (
            <div className="empty-state">
              <b>Nothing left to do this month</b>
              Every closure in this plan has already passed. Pick a later month
              to see work that can still be acted on.
            </div>
          ) : (
            <BlockList blocks={upcoming} />
          )}

          {passed.length > 0 && (
            <details className="passed">
              <summary>
                {passed.length} closure{passed.length === 1 ? "" : "s"} already
                passed
              </summary>
              <BlockList blocks={passed} />
            </details>
          )}
        </>
      )}

    </>
  );
}
