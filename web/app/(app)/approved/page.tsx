"use client";

import { usePlanner } from "@/components/PlannerProvider";
import { BlockRow } from "@/components/BlockRow";
import { Fact, Loading, SetupBanner } from "@/components/Common";

export default function ApprovedPage() {
  const { plan, store, loading, error, isApproved } = usePlanner();

  if (loading) return <Loading what="Loading divisional approvals…" />;
  if (error) return <div className="err">Could not load: {error}</div>;
  if (!plan) return null;

  if (!store?.connected) {
    return (
      <>
        <div className="page-header">
          <h1>Approved Closures</h1>
        </div>
        <SetupBanner />
      </>
    );
  }

  const approved = plan.blocks.filter(isApproved);
  const hours = approved.reduce((a, b) => a + b.train_hours, 0);
  const jobs = approved.reduce((a, b) => a + b.tasks.length, 0);
  const approvalPercent = plan.block_count > 0 ? (approved.length / plan.block_count) * 100 : 0;

  return (
    <>
      <div className="page-header">
        <h1>Approved Closures</h1>
      </div>

      <div className="brief">
        <div className="brief-top">
          <h2>Divisional Head Approvals</h2>
          <span style={{ fontSize: 13, color: "var(--text-faint)" }}>
            Official Sanctioned Maintenance Windows
          </span>
        </div>
        <div className="kpi-grid">
          <Fact
            value={String(approved.length)}
            label="Closures Approved"
            progress={approvalPercent}
            tone="win"
          />
          <Fact
            value={`${hours.toFixed(1)} h`}
            label="Train-Hours Committed"
          />
          <Fact
            value={String(jobs)}
            label="Jobs Covered"
          />
        </div>
      </div>

      {approved.length === 0 ? (
        <div className="empty-state">
          <b>No closures sanctioned yet</b>
          Divisional Heads can approve proposed block windows directly from the Plan or Calendar view.
        </div>
      ) : (
        approved.map((b) => (
          <BlockRow key={b.section_id + b.start} block={b} showDate />
        ))
      )}
    </>
  );
}
