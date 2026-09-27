"use client";

import type { Block } from "@/lib/types";
import { BlockRow } from "./BlockRow";
import { Icon, PATH } from "./icons";

interface DayDetailModalProps {
  dayDate: Date;
  blocks: Block[];
  onClose: () => void;
}

export function DayDetailModal({ dayDate, blocks, onClose }: DayDetailModalProps) {
  const formattedDate = dayDate.toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  const totalTrainHours = blocks.reduce((acc, b) => acc + b.train_hours, 0);
  const totalSavings = blocks.reduce((acc, b) => acc + b.saving, 0);
  const sharedBlocks = blocks.filter((b) => b.shared).length;

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
      <aside className="drawer" aria-label={`Closures for ${formattedDate}`}>
        <div className="drawer-head">
          <div>
            <h3>{formattedDate}</h3>
            <span style={{ fontSize: 12, color: "var(--text-faint)" }}>
              {blocks.length} closure{blocks.length === 1 ? "" : "s"} scheduled
            </span>
          </div>
          <button
            type="button"
            className="collapse-toggle"
            onClick={onClose}
            aria-label="Close panel"
          >
            <Icon d={PATH.cross} size={14} />
          </button>
        </div>

        <div className="drawer-body">
          {blocks.length > 0 && (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr 1fr",
                gap: 8,
                padding: "10px 14px",
                background: "var(--surface-2)",
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--border-soft)",
                fontSize: 12,
              }}
            >
              <div>
                <span style={{ color: "var(--text-faint)", display: "block" }}>Train-Hours Lost</span>
                <b style={{ fontSize: 16 }}>{totalTrainHours.toFixed(1)}h</b>
              </div>
              <div>
                <span style={{ color: "var(--text-faint)", display: "block" }}>Hours Saved</span>
                <b style={{ fontSize: 16, color: "var(--good)" }}>{totalSavings.toFixed(1)}h</b>
              </div>
              <div>
                <span style={{ color: "var(--text-faint)", display: "block" }}>Shared Window</span>
                <b style={{ fontSize: 16, color: "var(--primary)" }}>{sharedBlocks}</b>
              </div>
            </div>
          )}

          {blocks.length === 0 ? (
            <div className="empty-state">
              <b>No closures scheduled</b>
              There are no track maintenance blocks assigned for this date.
            </div>
          ) : (
            blocks.map((b) => (
              <BlockRow key={b.section_id + b.start} block={b} />
            ))
          )}
        </div>
      </aside>
    </>
  );
}
