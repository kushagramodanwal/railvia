"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePlanner } from "@/components/PlannerProvider";
import { NetworkMap } from "@/components/NetworkMap";
import { Fact, Loading } from "@/components/Common";
import { PeriodPicker } from "@/components/PeriodPicker";
import { getImpact, getNetwork } from "@/lib/api";
import { DEPT_VAR, type Block, type Impact, type Network } from "@/lib/types";

/* The division, geographically.
 *
 * The plan and the calendar answer "when". This answers "where" — which
 * stretches of the division are being handed over this month, how busy each
 * is, and which named services a given closure holds.
 *
 * Laid out as map beside detail rather than map above detail: selecting a
 * section used to push its trains below the fold, so the click and its answer
 * were never on screen together.
 */

const hhmm = (iso: string) =>
  new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

const dayLabel = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, {
    weekday: "short", day: "numeric", month: "short",
  });

export default function MapPage() {
  const { plan, loading, error } = usePlanner();
  const [network, setNetwork] = useState<Network | null>(null);
  const [netError, setNetError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [chosen, setChosen] = useState<Block | null>(null);
  const [impact, setImpact] = useState<Impact | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getNetwork().then((n) => { setNetwork(n); setNetError(null); })
      .catch((e: unknown) =>
        setNetError(e instanceof Error ? e.message : String(e)));
  }, []);

  /* Every closure on a section is its own question — different night,
     different trains. The list is shown and one is chosen, rather than
     silently answering for the first and saying so in small print. */
  const closuresHere = useMemo(
    () => (plan?.blocks ?? [])
      .filter((b) => b.section_id === selected)
      .sort((a, b) => a.start.localeCompare(b.start)),
    [plan, selected]);

  const load = useCallback(async (block: Block | null) => {
    setChosen(block);
    setImpact(null);
    if (!block) return;
    setBusy(true);
    try { setImpact(await getImpact(block.section_id, block.start, block.end)); }
    catch { setImpact(null); }
    finally { setBusy(false); }
  }, []);

  const onSection = (sectionId: string | null) => {
    setSelected(sectionId);
    const first = (plan?.blocks ?? [])
      .filter((b) => b.section_id === sectionId)
      .sort((a, b) => a.start.localeCompare(b.start))[0] ?? null;
    void load(first);
  };

  if (loading) return <Loading what="Reading the division…" />;
  if (error) return <div className="err">Could not load: {error}</div>;
  if (!plan) return null;

  const closedSections = new Set(plan.blocks.map((b) => b.section_id));
  const section = network?.sections.find((s) => s.id === selected);
  const busiest = network?.sections.reduce(
    (a, b) => (b.daily_trains > a.daily_trains ? b : a), network.sections[0]);

  return (
    <>
      <div className="page-header">
        <h1>The Division</h1>
        <PeriodPicker />
      </div>

      <div className="brief">
        <div className="kpi-grid">
          <Fact value={`${closedSections.size}/${network?.sections.length ?? "…"}`}
            label="Sections Handed Over" />
          <Fact value={String(plan.block_count)} label="Closures This Month" />
          <Fact value={`${plan.train_hours_lost.toFixed(0)} h`}
            label="Train-Hours Lost" tone="warn" />
          <Fact value={busiest ? busiest.daily_trains.toFixed(0) : "…"}
            label={busiest ? `Busiest — ${busiest.a}–${busiest.b}` : "Busiest Section"} />
        </div>
      </div>

      <div className="mapgrid">
        <div className="panel">
          <div className="panel-head">
            <h3>
              {network ? Object.keys(network.stations).length : "…"} stations,{" "}
              {network?.sections.length ?? "…"} sections
            </h3>
          </div>

          {netError ? (
            <div className="empty-state">
              <b>Map data unavailable</b>
              {netError}
            </div>
          ) : !network ? (
            <div className="status"><div className="spin" />Loading the network…</div>
          ) : (
            <div className="map-wrap">
              <NetworkMap network={network} blocks={plan.blocks}
                selected={selected} onSelect={onSection} />
              {/* Under the drawing, not beside the heading: in the head it
                  sat on one line with the station count and squeezed both,
                  and it widened the column past the map it describes. */}
              <div className="map-key">
                <span><i className="k-closed" />closure this month</span>
                <span><i className="k-open" />open</span>
                <span className="k-weight">weight = trains/day</span>
              </div>
            </div>
          )}
        </div>

        <aside className="panel mapside">
          {!selected ? (
            <div className="map-empty">
              <b>Select a section</b>
              <span>
                Red sections are handed over at least once this month. Any
                section can be selected — an open one is worth asking about
                too.
              </span>
            </div>
          ) : (
            <>
              <div className="panel-head">
                <h3>{section?.name ?? selected}</h3>
                <button type="button" className="collapse-toggle"
                  aria-label="Clear selection" onClick={() => onSection(null)}>
                  <span aria-hidden="true">✕</span>
                </button>
              </div>

              <div className="ms-body">
                <div className="ms-stats">
                  <div>
                    <span>Daily trains</span>
                    <b>{section?.daily_trains.toFixed(0) ?? "—"}</b>
                  </div>
                  <div>
                    <span>Peak trains/h</span>
                    <b>{section?.peak.toFixed(0) ?? "—"}</b>
                  </div>
                  <div>
                    <span>Closures</span>
                    <b>{closuresHere.length}</b>
                  </div>
                </div>

                {closuresHere.length === 0 ? (
                  <div className="map-empty">
                    <b>No closure planned here</b>
                    <span>
                      Nothing was due on this section this month, or the work
                      that was could not be fitted — the plan&rsquo;s
                      exceptions say which.
                    </span>
                  </div>
                ) : (
                  <>
                    <h4 className="ms-h">
                      {closuresHere.length === 1
                        ? "The closure"
                        : `${closuresHere.length} closures — pick one`}
                    </h4>
                    <div className="ms-picks">
                      {closuresHere.map((b) => (
                        <button key={b.start} type="button"
                          className={"ms-pick" + (chosen?.start === b.start ? " on" : "")}
                          aria-pressed={chosen?.start === b.start}
                          onClick={() => void load(b)}>
                          <b>{dayLabel(b.start)}</b>
                          <span className="mono">{hhmm(b.start)}–{hhmm(b.end)}</span>
                          <em>{b.train_hours.toFixed(1)} train-h</em>
                        </button>
                      ))}
                    </div>

                    {chosen && (
                      <div className="jobs ms-jobs">
                        {chosen.tasks.map((t) => (
                          <span className={"job" + (t.overdue ? " od" : "")} key={t.id}>
                            <i style={{ background: DEPT_VAR[t.department] }} />
                            <b>{t.department}</b> · {t.activity.replace(/_/g, " ")}
                          </span>
                        ))}
                      </div>
                    )}

                    {busy && (
                      <div className="status">
                        <div className="spin" />Finding affected services…
                      </div>
                    )}

                    {impact && !busy && (
                      impact.affected_count === 0 ? (
                        <div className="map-empty good">
                          <b>No service is held</b>
                          <span>
                            This closure sits in a genuinely empty window —
                            the cheapest kind there is.
                          </span>
                        </div>
                      ) : (
                        <>
                          <h4 className="ms-h">
                            {impact.affected_count} service
                            {impact.affected_count === 1 ? "" : "s"} held
                          </h4>
                          <div className="scroll ms-trains">
                            <table>
                              <thead>
                                <tr><th>Due</th><th>Train</th><th>Service</th></tr>
                              </thead>
                              <tbody>
                                {impact.trains.map((t) => (
                                  <tr key={t.number + t.at}>
                                    <td className="mono">{t.at.slice(11, 16)}</td>
                                    <td className="mono">{t.number}</td>
                                    <td>
                                      {t.name}
                                      <small>{t.type}</small>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </>
                      )
                    )}
                  </>
                )}
              </div>
            </>
          )}
        </aside>
      </div>
    </>
  );
}
