"use client";

import { usePlanner } from "./PlannerProvider";
import { isoDate, monthParams } from "@/lib/api";

/** Choose which month to plan.
 *
 * A month at a time: block plans are drawn up monthly, and a week is too
 * short a view to see a section's work spread out.
 */
const MONTHS_AHEAD = 9;
const MONTHS_BACK = 2;

const monthLabel = (d: Date) =>
  d.toLocaleDateString(undefined, { month: "long", year: "numeric" });

export function PeriodPicker() {
  const { params, setParams, plan } = usePlanner();

  const current = plan
    ? new Date(plan.horizon_start + "T00:00:00")
    : new Date(params.horizonStart + "T00:00:00");
  const anchor = new Date(current.getFullYear(), current.getMonth(), 1);

  const options: Date[] = [];
  const base = new Date();
  base.setDate(1);
  for (let i = -MONTHS_BACK; i <= MONTHS_AHEAD; i++) {
    options.push(new Date(base.getFullYear(), base.getMonth() + i, 1));
  }

  const go = (first: Date) => setParams(monthParams(first));
  const shift = (by: number) =>
    go(new Date(anchor.getFullYear(), anchor.getMonth() + by, 1));

  return (
    <div className="period">
      <button type="button" className="step" onClick={() => shift(-1)}
        aria-label="Previous month">‹</button>

      <label className="vh" htmlFor="month">Month</label>
      <select id="month" value={isoDate(anchor)}
        onChange={(e) => go(new Date(e.target.value + "T00:00:00"))}>
        {options.map((d) => (
          <option key={isoDate(d)} value={isoDate(d)}>{monthLabel(d)}</option>
        ))}
      </select>

      <button type="button" className="step" onClick={() => shift(1)}
        aria-label="Next month">›</button>
    </div>
  );
}
