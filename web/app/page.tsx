import Link from "next/link";
import {
  CountUp, Lift, MotionRoot, RailProgress, Reveal, Stagger, StaggerItem,
} from "@/components/landing-motion";

/* The landing page. Public — a judge should be able to understand what this
   is without an account.

   The hero is the product's actual argument rather than a claim about it:
   three separate closures on one section collapsing into one. The section,
   the jobs and both figures are real, taken from the planner's own output for
   Faridabad Nw Tn – Ballabgarh. */

/* Today's three closures on FDN–BVH, as the manual process produces them:
   each department asks separately, so the track is handed over three times. */
const TODAY = [
  { x: 96,  w: 104, dept: "S&T",  colour: "var(--lp-snt)", job: "cable megger test",       hours: 6.25 },
  { x: 236, w: 78,  dept: "S&T",  colour: "var(--lp-snt)", job: "track circuit adjustment", hours: 7.25 },
  { x: 470, w: 128, dept: "ENGG", colour: "var(--lp-engg)", job: "usfd rail testing",       hours: 11.0 },
];

/* The three departments, each with a photograph of what it actually
   maintains. They were cards once — a tag, a line of text and a system name —
   which said the same thing three times over and showed nothing. A picture of
   the rail, the wire and the signal does the work those cards were trying to
   do, and makes the point the page is built on: this is all the same track. */
const DEPARTMENTS = [
  {
    code: "ENGG",
    name: "Permanent way",
    colour: "var(--lp-engg)",
    image: "/images/departments/engg.webp",
    alt: "Track under maintenance — rails, sleepers and ballast",
    holds: "Rails, sleepers, ballast, points and crossings.",
    needs:
      "Tamping, destressing and ultrasonic testing all need the line clear "
      + "and the machines on it. This is the longest work of the three.",
    system: "TMS",
  },
  {
    code: "TRD",
    name: "Traction distribution",
    colour: "var(--lp-trd)",
    image: "/images/departments/trd.webp",
    alt: "Overhead line equipment above the track",
    holds: "The overhead line the trains draw power from.",
    needs:
      "Nothing may be worked on live. An isolation and an earth are needed "
      + "before anyone goes near the wire — including other departments.",
    system: "TDMS",
  },
  {
    code: "S&T",
    name: "Signal & telecom",
    colour: "var(--lp-snt)",
    image: "/images/departments/snt.webp",
    alt: "Lineside signalling equipment",
    holds: "Signals, point machines, track circuits, cabling.",
    needs:
      "A point machine cannot be opened while trains are being signalled "
      + "over it, so this work waits for the same quiet hours as the rest.",
    system: "SMMS",
  },
];

export default function Landing() {
  return (
    <MotionRoot>
    <div className="lp">
      {/* Framer bakes its `initial` state into the static export, so every
          revealed block ships as opacity:0. With scripts blocked nothing
          would ever put them back, and this public page — the one a judge
          opens first — would render blank. */}
      <noscript>
        <style>{"[data-reveal]{opacity:1!important;transform:none!important}"}</style>
      </noscript>
      <div className="lp-wrap">
        <RailProgress />
        <header className="lp-top">
          <div className="lp-brand">
            <span className="lp-mark lp-mark-img">
              <img src="/images/logo.png" alt="RailVia Logo" width={50} height={50} />
            </span>
            <span>RailVia</span>
          </div>
          <div className="lp-top-right">
            <img
              src="/images/indian_railways.png"
              alt="Indian Railways"
              title="Indian Railways / भारतीय रेल"
              className="lp-ir-logo"
              width={80}
              height={80}
            />
          </div>
        </header>

        {/* ── hero ── */}
        <section className="lp-hero">
          <Stagger>
          <StaggerItem>
          <div className="lp-eyebrow">
            <span>Ministry of Railways</span>
          </div>
          </StaggerItem>

          <StaggerItem>
          <h1>One closure.<br /><em>Not three.</em></h1>
          </StaggerItem>

          <StaggerItem>
          <p className="lp-lede">
            Track, signalling and overhead-line teams each book the same
            stretch of railway separately, so it closes three times when once
            would do — and nobody checks the timetable before choosing when.
            RailVia plans all three together.
          </p>
          </StaggerItem>

          <StaggerItem>
          <div className="lp-cta">
            <Lift><Link className="lp-btn" href="/calendar">Open the planner</Link></Lift>
            <Lift><Link className="lp-btn ghost" href="/map">See the network</Link></Lift>
          </div>
          </StaggerItem>

          {/* ── the signature: the merge, on real data ── */}
          <StaggerItem>
          <div className="lp-demo lp-anim">
            <div className="lp-demo-head">
              <b>Faridabad Nw Tn – Ballabgarh</b>
              <span>three maintenance jobs, one week, real timetable traffic</span>
            </div>

            <figure>
              <svg viewBox="0 0 900 208" role="img"
                   aria-label="Three separate track closures on the Faridabad to Ballabgarh section, costing 24.5 train-hours in total, merging into a single shared closure costing 5.0 train-hours.">
                {/* the section, drawn as track */}
                <g stroke="var(--lp-line)" strokeWidth="1">
                  {Array.from({ length: 45 }, (_, i) => (
                    <line key={i} x1={90 + i * 18} y1="104" x2={90 + i * 18} y2="120" />
                  ))}
                </g>
                <line x1="84" y1="112" x2="884" y2="112"
                      stroke="var(--lp-steel)" strokeWidth="2" />

                {/* time axis */}
                <g fontFamily="var(--lp-mono)" fontSize="11" fill="var(--lp-ink-3)">
                  <text x="84" y="150">Mon 00:00</text>
                  <text x="360" y="150">Tue</text>
                  <text x="636" y="150">Wed</text>
                </g>

                {/* today: three closures, each handed over on its own */}
                <g className="merge-out">
                  <text x="0" y="46" fontFamily="var(--lp-label)" fontSize="12"
                        fontWeight="700" fill="var(--lp-waste)" letterSpacing="1.2">
                    TODAY
                  </text>
                  {TODAY.map((b) => (
                    <g key={b.job}>
                      <rect x={b.x} y="62" width={b.w} height="34" rx="4"
                            fill={b.colour} opacity="0.92" />
                      <text x={b.x + 8} y="83" fontFamily="var(--lp-label)"
                            fontSize="11.5" fontWeight="700" fill="#fff">
                        {b.dept}
                      </text>
                      <text x={b.x} y="172" fontFamily="var(--lp-body)" fontSize="12"
                            fill="var(--lp-ink-3)">
                        {b.job}
                      </text>
                      <text x={b.x} y="190" fontFamily="var(--lp-mono)" fontSize="11.5"
                            fill="var(--lp-waste)" fontWeight="600">
                        {b.hours.toFixed(2)} train-h
                      </text>
                    </g>
                  ))}
                  <text x="700" y="46" fontFamily="var(--lp-mono)" fontSize="15"
                        fontWeight="600" fill="var(--lp-waste)">
                    24.50 train-hours lost
                  </text>
                </g>

                {/* railvia: the same work, one handover */}
                <g className="merge-in">
                  <text x="0" y="46" fontFamily="var(--lp-label)" fontSize="12"
                        fontWeight="700" fill="var(--lp-win)" letterSpacing="1.2">
                    RAILVIA
                  </text>
                  <rect x="96" y="62" width="128" height="34" rx="4"
                        fill="var(--lp-win)" opacity="0.94" />
                  <text x="104" y="83" fontFamily="var(--lp-label)" fontSize="11.5"
                        fontWeight="700" fill="#fff">
                    ENGG + S&amp;T
                  </text>
                  <text x="96" y="172" fontFamily="var(--lp-body)" fontSize="12"
                        fill="var(--lp-ink-3)">
                    all three jobs, one handover, Monday 00:00–03:00
                  </text>
                  <text x="96" y="190" fontFamily="var(--lp-mono)" fontSize="11.5"
                        fontWeight="600" fill="var(--lp-win)">
                    5.00 train-h
                  </text>
                  <text x="700" y="46" fontFamily="var(--lp-mono)" fontSize="15"
                        fontWeight="600" fill="var(--lp-win)">
                    5.00 train-hours lost
                  </text>
                </g>
              </svg>

              <figcaption>
                The same three jobs, the same crews, the same week. Booked
                separately they close the line three times and cost{" "}
                <b>24.5 train-hours</b>; planned together they close it once,
                in the quietest window that section has, and cost{" "}
                <b>5.0</b>. Nothing in the planner rewards sharing — cost is
                charged per closure, so merging is simply cheaper and the
                optimiser finds it.
              </figcaption>
            </figure>
          </div>
          </StaggerItem>
          </Stagger>
        </section>

        {/* ── the problem ── */}
        <section className="lp-section">
          <Reveal>
          <h2>Three departments, three systems, one piece of track</h2>
          <p>
            Each maintains something different on the same rails, each keeps
            its own defect list, and each raises its own request for the line
            to be closed. There is no shared queue, so the overlap is invisible
            to all of them.
          </p>
          </Reveal>
          {/* ── what a closure actually is ──
              Side elevation of one stretch of line: rails, the overhead
              line above, a signal, and a train held at it. All three
              departments' equipment sits on the same track — the page's
              argument drawn rather than asserted. */}
          <figure className="lp-scene">
            <div className="scene-scroll">
            <svg viewBox="0 0 900 268" role="img"
                 aria-label="A stretch of railway under possession: a train held at a red signal on the left, and beyond it a closed section where the track, the overhead line and the signalling equipment all sit on the same rails.">
              <defs>
                <pattern id="ballast" width="7" height="7" patternUnits="userSpaceOnUse">
                  <circle cx="1.5" cy="1.5" r="0.9" fill="var(--lp-line)" />
                  <circle cx="5" cy="4.5" r="0.7" fill="var(--lp-line)" />
                </pattern>
              </defs>

              {/* formation and ballast */}
              <path d="M0 232 L900 232 L900 250 L0 250 Z" fill="url(#ballast)" />
              <line x1="0" y1="232" x2="900" y2="232" stroke="var(--lp-line)" strokeWidth="1" />

              {/* sleepers */}
              <g stroke="var(--lp-steel)" strokeWidth="4" opacity="0.32">
                {Array.from({ length: 44 }, (_, i) => (
                  <line key={i} x1={12 + i * 20} y1="222" x2={12 + i * 20} y2="234" />
                ))}
              </g>

              {/* the rails themselves — ENGG */}
              <line x1="0" y1="220" x2="900" y2="220" stroke="var(--lp-engg)" strokeWidth="2.5" />
              <line x1="0" y1="226" x2="900" y2="226" stroke="var(--lp-engg)" strokeWidth="1.6" opacity="0.5" />
              {/* the rail lifted for work, inside the possession */}
              <path d="M556 220 L586 206 L626 206 L656 220"
                    fill="none" stroke="var(--lp-engg)" strokeWidth="2.5"
                    strokeLinejoin="round" />

              {/* overhead line equipment — TRD */}
              <g stroke="var(--lp-trd)" strokeWidth="1.8" fill="none">
                {[330, 500, 670, 840].map((x) => (
                  <g key={x}>
                    <line x1={x} y1="222" x2={x} y2="40" />
                    <line x1={x} y1="40" x2={x - 34} y2="40" />
                    <line x1={x - 34} y1="40" x2={x - 34} y2="56" />
                  </g>
                ))}
                <line x1="0" y1="56" x2="900" y2="56" strokeWidth="2" />
                <line x1="0" y1="40" x2="900" y2="40" strokeWidth="1" opacity="0.45" />
              </g>

              {/* signal at danger — S&T */}
              <g>
                <line x1="286" y1="222" x2="286" y2="120" stroke="var(--lp-snt)" strokeWidth="3" />
                <rect x="272" y="96" width="28" height="30" rx="5"
                      fill="var(--lp-surface)" stroke="var(--lp-snt)" strokeWidth="2" />
                <circle cx="286" cy="111" r="7" fill="var(--lp-waste)" />
              </g>

              {/* possession limit boards */}
              <g>
                {[[352, "start"], [862, "end"]].map(([x]) => (
                  <g key={String(x)}>
                    <line x1={Number(x)} y1="222" x2={Number(x)} y2="168"
                          stroke="var(--lp-ink-3)" strokeWidth="2" />
                    <rect x={Number(x) - 15} y="150" width="30" height="20" rx="3"
                          fill="var(--lp-waste)" />
                  </g>
                ))}
                <line x1="352" y1="160" x2="862" y2="160" stroke="var(--lp-waste)"
                      strokeWidth="1.4" strokeDasharray="7 5" />
                <text x="607" y="146" textAnchor="middle" fontFamily="var(--lp-label)"
                      fontSize="12.5" fontWeight="700" fill="var(--lp-waste)"
                      letterSpacing="1.4">
                  LINE BLOCKED
                </text>
              </g>

              {/* the work party */}
              <g stroke="var(--lp-ink-2)" strokeWidth="1.8" fill="none">
                <circle cx="592" cy="186" r="5" />
                <path d="M592 191 L592 204 M586 196 L598 196 M592 204 L587 214 M592 204 L597 214" />
                <circle cx="628" cy="186" r="5" />
                <path d="M628 191 L628 204 M622 197 L634 194 M628 204 L623 214 M628 204 L633 214" />
                <line x1="634" y1="194" x2="644" y2="212" strokeWidth="2.2" />
              </g>

              {/* the train, held */}
              <g>
                {/* pantograph, down to the contact wire */}
                <g stroke="var(--lp-trd)" strokeWidth="1.6" fill="none">
                  <path d="M118 128 L100 88 L136 88 L118 128" />
                  <line x1="92" y1="88" x2="146" y2="88" strokeWidth="2.4" />
                </g>
                {/* body */}
                <path d="M24 214 L24 140 Q24 130 34 130 L212 130 Q226 130 234 142 L246 168 L246 214 Z"
                      fill="var(--lp-surface)" stroke="var(--lp-ink)" strokeWidth="2.2"
                      strokeLinejoin="round" />
                {/* cab window and body glazing */}
                <path d="M206 140 L226 140 Q232 140 236 148 L242 162 L206 162 Z"
                      fill="var(--lp-rail-soft)" stroke="var(--lp-ink)" strokeWidth="1.6" />
                <g fill="var(--lp-rail-soft)" stroke="var(--lp-ink)" strokeWidth="1.4">
                  <rect x="44" y="146" width="30" height="20" rx="3" />
                  <rect x="86" y="146" width="30" height="20" rx="3" />
                  <rect x="128" y="146" width="30" height="20" rx="3" />
                  <rect x="170" y="146" width="24" height="20" rx="3" />
                </g>
                {/* solebar */}
                <line x1="24" y1="196" x2="246" y2="196" stroke="var(--lp-ink)" strokeWidth="1.4" />
                {/* bogies */}
                <g fill="var(--lp-surface)" stroke="var(--lp-ink)" strokeWidth="2">
                  <circle cx="62" cy="212" r="10" />
                  <circle cx="94" cy="212" r="10" />
                  <circle cx="180" cy="212" r="10" />
                  <circle cx="212" cy="212" r="10" />
                </g>
                {/* headlight, lit but going nowhere */}
                <circle cx="240" cy="176" r="3.5" fill="var(--lp-amber)" />
              </g>

              {/* who owns what */}
              <g fontFamily="var(--lp-label)" fontSize="11.5" fontWeight="700"
                 letterSpacing="1.1">
                <text x="286" y="88" textAnchor="middle" fill="var(--lp-snt)">S&amp;T</text>
                <text x="806" y="34" fill="var(--lp-trd)">TRD</text>
                <text x="700" y="248" fill="var(--lp-engg)">ENGG</text>
              </g>
            </svg>
            </div>
            <figcaption>
              One stretch of line, and everything on it belongs to somebody
              different: the rails to <b>ENGG</b>, the overhead line to{" "}
              <b>TRD</b>, the signal holding that train to <b>S&amp;T</b>.
              Each asks for the track separately, so it is handed over three
              times — and each time, that train waits.
            </figcaption>
          </figure>
        </section>

        {/* ── the three departments, one at a time ── */}
        <section className="lp-section lp-depts">
          <Reveal>
          <h2>Each one holds a different part of the same track</h2>
          <p>
            None of them is wrong to want the line. Every one of these jobs is
            mandated, and every one needs the track clear to do. The problem
            is only that they ask separately.
          </p>
          </Reveal>

          <div className="lp-dept-rows">
            {DEPARTMENTS.map((d, i) => (
              <Reveal key={d.code} className="lp-dept-row" delay={0.05}>
                <figure className="lp-dept-img">
                  <img src={d.image} alt={d.alt} width={1200} height={670}
                       loading="lazy" decoding="async" />
                  <span className="lp-dept-edge" style={{ background: d.colour }} />
                </figure>
                <div className="lp-dept-body">
                  <span className="lp-dept-code" style={{ color: d.colour }}>
                    <i style={{ background: d.colour }} />{d.code}
                  </span>
                  <h3>{d.name}</h3>
                  <p className="lp-dept-holds">{d.holds}</p>
                  <p>{d.needs}</p>
                  <div className="lp-dept-sys">
                    raises its work through <b>{d.system}</b>
                    <span>— which the other two cannot see</span>
                  </div>
                </div>
              </Reveal>
            ))}
          </div>
        </section>

        {/* ── what it does ── */}
        <section className="lp-section">
          <Reveal>
          <h2>It plans against the real timetable</h2>
          <p>
            Closing Sahibabad–Ghaziabad at 08:00 stops twenty-one trains.
            Closing it at 03:00 stops far fewer. RailVia knows the difference
            because it counts the actual services — by name and by hour — from
            the published timetable, for every section it plans.
          </p>
          <p>
            It then solves the whole month at once, against what a division
            actually has: crews, mandated intervals, and one track.
          </p>
          </Reveal>

          {/* The three numbers are the argument, so they land rather than
              simply being present. Each waits for the one before it. */}
          <div className="lp-figures">
            <Reveal className="lp-fig">
              <b><CountUp to={39} /></b>
              <span>sections across four Delhi-division corridors</span>
            </Reveal>
            <Reveal className="lp-fig" delay={0.12}>
              <b><CountUp to={7267} /></b>
              <span>real train movements counted from the timetable</span>
            </Reveal>
            <Reveal className="lp-fig win" delay={0.24}>
              <b><CountUp to={35} prefix="~" suffix="%" /></b>
              <span>fewer train-hours lost, for identical work</span>
            </Reveal>
          </div>
          <Reveal className="lp-caveat" delay={0.36}>
            <b>Measured, with the range stated.</b> 28.5% to 41.6% over four
            runs at a 60-second budget, against a simulation of today's
            process doing the same set of jobs.
          </Reveal>
        </section>

        {/* ── close ── */}
        <section className="lp-section lp-close">
          <Reveal>
          <h2>Look at next month's closures</h2>
          <p>
            The planner opens on the current month: what is proposed, what it
            costs, which jobs could not be fitted and why. A divisional head
            approves; a section engineer reports work done.
          </p>
          <div className="lp-cta">
            <Lift><Link className="lp-btn" href="/calendar">Open the planner</Link></Lift>
            <Lift><Link className="lp-btn ghost" href="/map">See the network</Link></Lift>
          </div>
          </Reveal>
        </section>

        <footer className="lp-foot">
          <span>RailVia · Automatic block planning · SIH26027</span>
          <span>Timetable data via RailRadar, an aggregator of public NTES data</span>
        </footer>
      </div>
    </div>
    </MotionRoot>
  );
}
