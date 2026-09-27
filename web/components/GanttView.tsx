"use client";

import { useMemo } from "react";
import type { Block } from "@/lib/types";
import { DEPT_VAR } from "@/lib/types";

interface GanttViewProps {
  blocks: Block[];
  sections: Record<string, string>;
  onSelectBlock?: (block: Block) => void;
}

export function GanttView({ blocks, sections, onSelectBlock }: GanttViewProps) {
  // Group blocks by section_id
  const sectionMap = useMemo(() => {
    const map = new Map<string, Block[]>();
    for (const b of blocks) {
      const list = map.get(b.section_id) ?? [];
      list.push(b);
      map.set(b.section_id, list);
    }
    return map;
  }, [blocks]);

  const sectionKeys = Array.from(sectionMap.keys());
  const hours = Array.from({ length: 24 }, (_, i) => i);

  const getPercentPos = (dateStr: string) => {
    const d = new Date(dateStr);
    const h = d.getHours();
    const m = d.getMinutes();
    return ((h + m / 60) / 24) * 100;
  };

  const getDurationPercent = (hoursDuration: number) => {
    return Math.max(2.5, (hoursDuration / 24) * 100);
  };

  if (blocks.length === 0) {
    return (
      <div className="empty-state" style={{ padding: "var(--s5)" }}>
        <b>No scheduled closures for this period</b>
        Select another month or change department filters.
      </div>
    );
  }

  return (
    <div className="panel" style={{ padding: "var(--s3)" }}>
      <div className="panel-head">
        <h3>Coordinated Block Timeline (24-Hour Schedule)</h3>
        <span style={{ fontSize: 12, color: "var(--text-faint)" }}>
          Showing {blocks.length} closures across {sectionKeys.length} track sections
        </span>
      </div>

      <div className="gantt-wrap">
        <div className="gantt-header">
          <div className="gantt-header-cell" style={{ textAlign: "left", paddingLeft: 12 }}>
            Section Code
          </div>
          {hours.map((h) => (
            <div className="gantt-header-cell" key={h}>
              {String(h).padStart(2, "0")}:00
            </div>
          ))}
        </div>

        {sectionKeys.map((secId) => {
          const secBlocks = sectionMap.get(secId) ?? [];
          const secName = sections[secId] ?? secId;

          return (
            <div className="gantt-row" key={secId}>
              <div className="gantt-sec-name" title={secName}>
                {secId} <span style={{ fontWeight: 400, color: "var(--text-faint)", fontSize: 10 }}>({secBlocks.length})</span>
              </div>

              {hours.map((h) => (
                <div className="gantt-grid-cell" key={h} />
              ))}

              {secBlocks.map((b, idx) => {
                const left = getPercentPos(b.start);
                const width = getDurationPercent(b.hours);
                const primaryDept = b.departments[0] ?? "ENGG";
                const bg = DEPT_VAR[primaryDept] ?? "var(--primary)";

                return (
                  <button
                    type="button"
                    key={`${b.section_id}_${b.start}_${idx}`}
                    className="gantt-bar"
                    style={{
                      left: `calc(160px + ${left}%)`,
                      width: `${width}%`,
                      background: bg,
                    }}
                    onClick={() => onSelectBlock?.(b)}
                    title={`${secName}: ${b.hours}h closure (${b.tasks.length} jobs, ${b.train_hours.toFixed(1)} train-h)`}
                  >
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {b.hours}h ({b.tasks.length} jobs)
                    </span>
                    {b.shared && (
                      <span style={{
                        fontSize: 9, background: "rgba(0,0,0,0.3)", padding: "1px 4px",
                        borderRadius: 3, textTransform: "uppercase"
                      }}>
                        Shared
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}
