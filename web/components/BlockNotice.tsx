"use client";

import { useEffect, useState } from "react";
import { usePlanner } from "./PlannerProvider";
import { getImpact } from "@/lib/api";
import { DEPT_VAR, type Approval, type Block, type Impact } from "@/lib/types";

/* The document a division actually issues.
 *
 * Proposing a closure and approving it are decisions; issuing it is the act.
 * Until now the workflow stopped at the decision, which is the difference
 * between a planning demo and something a division could use — the people who
 * turn up at the site work from a piece of paper, not a web page.
 *
 * Two things this deliberately is not:
 *
 *   It is not a facsimile of any Railways form. Reproducing an official
 *   layout, or citing clause numbers nobody here has read, would be exactly
 *   the fabrication this project refuses everywhere else.
 *
 *   It is not an authority to work. Authority to occupy a line comes from the
 *   controller on the day, against the traffic actually running. This records
 *   what was planned and who granted it, and says so at the foot.
 */

const two = (n: number) => String(n).padStart(2, "0");

const clock = (iso: string) => {
  const d = new Date(iso);
  return `${two(d.getHours())}:${two(d.getMinutes())}`;
};

const longDate = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, {
    weekday: "long", day: "numeric", month: "long", year: "numeric",
  });

/** Deterministic, so the same closure always carries the same reference —
 *  the number goes in a register and on a message, and one that changed each
 *  time the page rendered would be worthless. */
function reference(block: Block, division: string): string {
  const d = new Date(block.start);
  return [
    "BPN", division, block.section_id,
    `${d.getFullYear()}${two(d.getMonth() + 1)}${two(d.getDate())}`,
    `${two(d.getHours())}${two(d.getMinutes())}`,
  ].join("/");
}

function duration(block: Block): string {
  const mins = Math.round(block.hours * 60);
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return h && m ? `${h} h ${m} min` : h ? `${h} h` : `${m} min`;
}

export function BlockNotice({ block, approval, onClose }: {
  block: Block; approval: Approval | undefined; onClose: () => void;
}) {
  const { plan, division } = usePlanner();
  const [impact, setImpact] = useState<Impact | null>(null);

  useEffect(() => {
    let live = true;
    getImpact(block.section_id, block.start, block.end)
      .then((r) => { if (live) setImpact(r); })
      .catch(() => { /* the traffic panel says it could not be read */ });
    return () => { live = false; };
  }, [block.section_id, block.start, block.end]);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  const sectionName = plan?.sections?.[block.section_id] ?? block.section_id;
  const crews = block.tasks.length;

  return (
    <div className="notice-backdrop" onClick={onClose}>
      <div className="notice-sheet" onClick={(e) => e.stopPropagation()}
        role="dialog" aria-label={`Block permission notice for ${sectionName}`}>

        <div className="notice-actions">
          <button type="button" onClick={() => window.print()}>Print</button>
          <button type="button" onClick={onClose}>Close</button>
        </div>

        <article className="notice">
          <header className="n-head">
            <div>
              <div className="n-mark">RailVia</div>
              <h2>Block permission notice</h2>
            </div>
            <div className="n-ref">
              <span>Reference</span>
              <b>{reference(block, division.id)}</b>
            </div>
          </header>

          <dl className="n-grid">
            <div>
              <dt>Section</dt>
              <dd>{sectionName}<code>{block.section_id}</code></dd>
            </div>
            <div>
              <dt>Division</dt>
              <dd>{division.name} · {division.zone}</dd>
            </div>
            <div>
              <dt>Date</dt>
              <dd>{longDate(block.start)}</dd>
            </div>
            <div>
              <dt>Duration</dt>
              <dd>{duration(block)}</dd>
            </div>
            <div>
              <dt>Line blocked from</dt>
              <dd className="big">{clock(block.start)}</dd>
            </div>
            <div>
              <dt>To</dt>
              <dd className="big">{clock(block.end)}</dd>
            </div>
          </dl>

          <section className="n-block">
            <h3>Departments attending</h3>
            <div className="n-depts">
              {block.departments.map((d) => (
                <span key={d}><i style={{ background: DEPT_VAR[d] }} />{d}</span>
              ))}
            </div>
            {block.shared && (
              <p className="n-note">
                A single handover serving {block.departments.length} departments.
                Booked separately this work would need {block.tasks.length} closures
                on this section, costing {block.separate_cost.toFixed(1)} train-hours
                against {block.train_hours.toFixed(1)}.
              </p>
            )}
          </section>

          <section className="n-block">
            <h3>Work to be carried out</h3>
            <table className="n-table">
              <thead>
                <tr>
                  <th style={{ width: "2.5em" }}>#</th>
                  <th>Department</th>
                  <th>Activity</th>
                  <th className="r">Severity</th>
                </tr>
              </thead>
              <tbody>
                {block.tasks.map((t, i) => (
                  <tr key={t.id}>
                    <td>{i + 1}</td>
                    <td>
                      <i className="dot" style={{ background: DEPT_VAR[t.department] }} />
                      {t.department}
                    </td>
                    <td>
                      {t.activity.replace(/_/g, " ")}
                      {t.overdue && <b className="od"> overdue</b>}
                    </td>
                    <td className="r">{t.severity}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="n-note">{crews} work {crews === 1 ? "item" : "items"} under one possession.</p>
          </section>

          <section className="n-block">
            <h3>Effect on traffic</h3>
            {impact === null ? (
              <p className="n-note">Affected services could not be read.</p>
            ) : impact.affected_count === 0 ? (
              <p className="n-note">
                No scheduled service crosses this section during the block.
              </p>
            ) : (
              <>
                <p className="n-note">
                  <b>
                    {impact.affected_count} scheduled service
                    {impact.affected_count === 1 ? "" : "s"}
                  </b>{" "}
                  cross{impact.affected_count === 1 ? "es" : ""} this section
                  while the line is blocked. Cost to traffic,{" "}
                  <b>{block.train_hours.toFixed(1)} train-hours</b>.
                </p>
                <table className="n-table">
                  <thead>
                    <tr><th>Train</th><th>Name</th><th className="r">Booked</th></tr>
                  </thead>
                  <tbody>
                    {impact.trains.slice(0, 12).map((t) => (
                      <tr key={t.number + t.at}>
                        <td><b>{t.number}</b></td>
                        <td>{t.name}</td>
                        <td className="r">{t.at.slice(11, 16)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {impact.trains.length > 12 && (
                  <p className="n-note">
                    and {impact.trains.length - 12} further services.
                  </p>
                )}
              </>
            )}
          </section>

          <section className="n-block n-auth">
            <h3>Granted by</h3>
            {approval ? (
              <dl className="n-grid tight">
                <div>
                  <dt>Divisional head</dt>
                  <dd>{approval.decided_by}</dd>
                </div>
                <div>
                  <dt>Granted at</dt>
                  <dd>{new Date(approval.decided_at).toLocaleString()}</dd>
                </div>
              </dl>
            ) : (
              <p className="n-pending">
                Not yet granted. This notice records a proposed closure only.
              </p>
            )}
          </section>

          <footer className="n-foot">
            <p>
              <b>Not an authority to work.</b> Authority to occupy a line is
              given by the controller on the day, against the traffic actually
              running. This notice records what was planned and who granted it.
            </p>
            <p>
              Planning document generated by RailVia. Train services and
              section traffic are taken from the published timetable;
              maintenance work is simulated.
            </p>
          </footer>
        </article>
      </div>
    </div>
  );
}
