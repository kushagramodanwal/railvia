"use client";

import { usePlanner } from "@/components/PlannerProvider";
import { Fact, Loading, SetupBanner } from "@/components/Common";
import { DEPT_VAR } from "@/lib/types";

export default function CompletedPage() {
  const { plan, store, loading, error, completions } = usePlanner();

  if (loading) return <Loading what="Loading completed maintenance records…" />;
  if (error) return <div className="err">Could not load: {error}</div>;
  if (!plan) return null;

  if (!store?.connected) {
    return (
      <>
        <div className="page-header">
          <h1>Completed Maintenance</h1>
        </div>
        <SetupBanner />
      </>
    );
  }

  const done = plan.blocks.flatMap((b) =>
    b.tasks.filter((t) => completions.has(t.id)).map((t) => ({ task: t, block: b })));
  const overdueCleared = done.filter((d) => d.task.overdue).length;
  const remainingScheduled = Math.max(0, plan.scheduled - done.length);

  return (
    <>
      <div className="page-header">
        <h1>Completed Maintenance</h1>
      </div>

      <div className="brief">
        <div className="brief-top">
          <h2>Field Completion Logs</h2>
          <span style={{ fontSize: 13, color: "var(--text-faint)" }}>
            Real-Time Engineer Execution Audit
          </span>
        </div>
        <div className="kpi-grid">
          <Fact
            value={String(done.length)}
            label="Jobs Completed"
            tone="win"
          />
          <Fact
            value={String(remainingScheduled)}
            label="Scheduled, Pending Field Work"
          />
          <Fact
            value={String(overdueCleared)}
            label="Overdue Defects Cleared"
            tone={overdueCleared ? "win" : undefined}
          />
        </div>
      </div>

      {done.length === 0 ? (
        <div className="empty-state">
          <b>No completed tasks recorded yet</b>
          Maintenance engineers can click “Mark done” on active blocks once field work is completed.
        </div>
      ) : (
        <div className="panel">
          <div className="panel-head">
            <h3>Execution Audit Log</h3>
          </div>
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>Activity / Task</th>
                  <th>Department</th>
                  <th>Track Section</th>
                  <th>Timestamp Completed</th>
                </tr>
              </thead>
              <tbody>
                {done.map(({ task, block }) => {
                  const c = completions.get(task.id)!;
                  return (
                    <tr key={task.id}>
                      <td style={{ fontWeight: 600 }}>
                        {task.activity.replace(/_/g, " ")}
                        {task.overdue && (
                          <span style={{
                            marginLeft: 8, fontSize: 10, color: "var(--bad)",
                            background: "var(--bad-soft)", padding: "2px 6px",
                            borderRadius: 4, textTransform: "uppercase", fontWeight: 700
                          }}>
                            Overdue Cleared
                          </span>
                        )}
                      </td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        <span className="job">
                          <i style={{ background: DEPT_VAR[task.department] }} />
                          {task.department}
                        </span>
                      </td>
                      <td>
                        {plan.sections[block.section_id] ?? block.section_id}
                        <code style={{ marginLeft: 6, fontSize: 11, color: "var(--text-faint)" }}>
                          {block.section_id}
                        </code>
                      </td>
                      <td className="mono" style={{ fontSize: 12 }}>
                        {new Date(c.completed_at).toLocaleString()}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
