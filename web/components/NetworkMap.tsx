"use client";

import { useMemo } from "react";
import type { Block, Network } from "@/lib/types";

/** The corridors as they run on the ground.
 *
 * Station positions are the real latitudes and longitudes carried in the
 * timetable data, projected equirectangularly — over a single division the
 * distortion is invisible, and it keeps the drawing honest: this is where the
 * track actually goes, not a schematic.
 *
 * Two things the line carries, and nothing else does:
 *   weight is traffic, so the busy trunk reads as busy at a glance;
 *   colour is state — closed, selected, or open.
 */
/* The viewBox is computed from the data, not fixed.
 *
 * A fixed 900x560 frame left this division — which runs almost due
 * north-south — as a thin strip down the middle of a wide, empty box. The
 * frame now fits the projected extent, and the CSS constrains it by height,
 * so the drawing fills what it is given at whatever shape the corridors
 * actually are. */
const SPAN = 560;   // the long axis, in user units
const MAP_HEIGHT = 560;  // drawn height in CSS pixels
const PAD = 40;

export function NetworkMap({
  network, blocks, selected, onSelect,
}: {
  network: Network;
  blocks: Block[];
  selected: string | null;
  onSelect: (sectionId: string | null) => void;
}) {
  const { project, closureCount, busiest, W, H } = useMemo(() => {
    const pts = Object.values(network.stations)
      .filter((s) => s.lat != null && s.lng != null) as { lat: number; lng: number }[];
    const lats = pts.map((p) => p.lat);
    const lngs = pts.map((p) => p.lng);
    const minLat = Math.min(...lats), maxLat = Math.max(...lats);
    const minLng = Math.min(...lngs), maxLng = Math.max(...lngs);

    // A degree of longitude is shorter than a degree of latitude, by the
    // cosine of the latitude — about 0.88 at Delhi. Without it the division
    // comes out stretched east-west and the corridors no longer run the way
    // they run on the ground.
    const kx = Math.cos(((minLat + maxLat) / 2) * Math.PI / 180);
    const dx = Math.max((maxLng - minLng) * kx, 1e-6);
    const dy = Math.max(maxLat - minLat, 1e-6);

    // One scale for both axes — the long side gets SPAN, the short side
    // whatever the true proportion gives it.
    const scale = SPAN / Math.max(dx, dy);
    const spanX = dx * scale;
    const spanY = dy * scale;

    const counts = new Map<string, number>();
    for (const b of blocks) {
      counts.set(b.section_id, (counts.get(b.section_id) ?? 0) + 1);
    }
    return {
      project: (lat: number, lng: number) => ({
        x: PAD + (lng - minLng) * kx * scale,
        y: PAD + (maxLat - lat) * scale,
      }),
      closureCount: counts,
      busiest: Math.max(...network.sections.map((s) => s.daily_trains), 1),
      W: spanX + PAD * 2,
      H: spanY + PAD * 2,
    };
  }, [network, blocks]);

  const at = (code: string) => {
    const s = network.stations[code];
    if (!s || s.lat == null || s.lng == null) return null;
    return project(s.lat, s.lng);
  };

  const closedCount = [...closureCount.keys()].length;

  return (
    /* Both dimensions stated, from the data.
     *
     * Neither `width: auto` nor `aspect-ratio` works here: an <svg> resolves
     * auto width to 100%, so the element kept filling the panel and centring
     * the drawing inside it — the dead space moved from the viewBox into the
     * element rather than going away. Height is authoritative because this
     * division is tall; width follows from the true proportion. */
    <svg viewBox={`0 0 ${W.toFixed(1)} ${H.toFixed(1)}`} className="map" role="img"
      style={{ height: MAP_HEIGHT, width: Math.round(MAP_HEIGHT * (W / H)) }}
      aria-label={
        `${Object.keys(network.stations).length} stations across `
        + `${network.sections.length} sections. ${closedCount} sections carry a `
        + `closure this month. Line weight is daily traffic.`
      }>
      {network.sections.map((s) => {
        const p = at(s.a), q = at(s.b);
        if (!p || !q) return null;
        const closures = closureCount.get(s.id) ?? 0;
        const isSelected = selected === s.id;
        const width = 1.5 + (s.daily_trains / busiest) * 5.5;
        return (
          <g key={s.id} className="map-sec">
            <line x1={p.x} y1={p.y} x2={q.x} y2={q.y}
              stroke={isSelected ? "var(--primary)"
                : closures ? "var(--bad)" : "var(--text-faint)"}
              strokeWidth={isSelected ? width + 3.5 : width}
              strokeLinecap="round"
              opacity={isSelected ? 1 : closures ? 0.9 : 0.3} />
            {/* The drawn line is far too thin to hit. Every section is
                selectable, closed or not — "why was nothing planned here?"
                is as fair a question as "what does this closure stop?". */}
            <line x1={p.x} y1={p.y} x2={q.x} y2={q.y}
              stroke="transparent" strokeWidth={18} style={{ cursor: "pointer" }}
              onClick={() => onSelect(isSelected ? null : s.id)}>
              <title>
                {s.name}
                {"\n"}{s.daily_trains.toFixed(0)} trains/day
                {closures ? `\n${closures} closure${closures === 1 ? "" : "s"} this month` : "\nno closure planned"}
              </title>
            </line>
          </g>
        );
      })}

      {Object.entries(network.stations).map(([code, st]) => {
        const p = at(code);
        if (!p) return null;
        const onClosed = network.sections.some(
          (s) => closureCount.has(s.id)
            && (s.a === code || s.b === code));
        return (
          <circle key={code} cx={p.x} cy={p.y} r={onClosed ? 4 : 3}
            fill="var(--surface)"
            stroke={onClosed ? "var(--bad)" : "var(--text-faint)"}
            strokeWidth={1.8}>
            <title>{st.name} ({code})</title>
          </circle>
        );
      })}

      {/* Labelled only where there is room — corridor ends and junctions.
          Labelling every station on a 39-section division is illegible. */}
      {Object.entries(network.stations).map(([code, st]) => {
        const p = at(code);
        if (!p) return null;
        const degree = network.sections.filter(
          (s) => s.a === code || s.b === code).length;
        if (degree === 2) return null;
        return (
          <text key={"l" + code} x={p.x + 7} y={p.y + 3.5} className="map-label">
            {code}
            <title>{st.name}</title>
          </text>
        );
      })}
    </svg>
  );
}
