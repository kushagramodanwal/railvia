# Automatic Block Planning — SIH26027

Coordinated maintenance block scheduling for Indian Railways. Three
departments (ENGG, TRD, S&T) currently request track-blocking windows
independently; this system merges their demands into one schedule that
completes the required maintenance while losing the fewest train-hours.

See [PROJECT_BRIEF.md](PROJECT_BRIEF.md) for full scope and build order.

> **Data provenance is tracked per component.** Maintenance backlogs are
> synthetic — TMS, SMMS and TDMS are internal systems with no public
> equivalent. **Train traffic is real**: section geometry and hourly traffic
> profiles are derived from the published Indian Railways timetable via the
> RailRadar API. Every planning instance records a `SourceKind` for each of
> `sections`, `tasks`, `traffic` and `crew_capacity`, and reports
> `is_synthetic=True` if *any* component is generated.
> See [ASSUMPTIONS.md](ASSUMPTIONS.md).

## Status: all phases complete

| Phase | Scope | State |
|-------|-------|-------|
| 0 | Data model + tiny generator (5 sections, 20 tasks, 7 days) | done |
| 0.5 | Real timetable ingestion (RailRadar) | done |
| 1 | Minimum viable CP-SAT optimiser | done |
| 2 | Real scale (39 sections, 300 tasks), crew + deadline constraints | done |
| 3 | Criticality model + baseline simulator | done |
| 4 | FastAPI + browser UI | done |
| 5 | Scenario re-planning, recorded demo | done |

## The headline

**~35% fewer train-hours lost across a 30-day horizon, on 39 sections with 3
departments, for an identical set of maintenance tasks** — measured over four
runs at a 60-second solver budget, range 28.5% to 41.6%.

Quote the range, not the best run: a time-limited parallel search returns one
of several good schedules. Budget and instance size belong next to the number
every time it is stated. See [ASSUMPTIONS.md](ASSUMPTIONS.md) A-19.

**Say where the gain comes from.** Warm-starting the solver from a greedy
constructive schedule moved the mean from 15.6% to 34.9% and cut the run-to-run
spread from 37.9% to 14.0%. Most of the improvement is therefore the
heuristic's, not CP-SAT's search. On train-hours alone a 0.06-second greedy
beats the solver (461 against 563 on the same tasks); CP-SAT spends those
train-hours removing 226 task-days of lateness, and it is what proves the
constraints hold. A-20 sets out that trade in full — it is the first thing an
OR-literate judge will probe.

Consistent across every run, and far more stable than the percentage:

| | Manual | Ours (same work) |
|---|---|---|
| Blocks shared across departments | 0 | 21–37 |
| Peak-hour blocks | 8 | 0 |
| Separate blocks | 218 | 155–201 |
| Tasks finishing late | 135 | 93–115 |

Separately, given the same month the planner completes **54 more tasks** than
the manual process manages.

Neither column is quoted alone: see [ASSUMPTIONS.md](ASSUMPTIONS.md) A-17 for
exactly what the baseline is allowed to do and why the comparison is
normalised to identical work.

**Remaining variance** comes from the solver stopping well short of proving
optimality — the gap is still ~64%, because the lower bound is weak. A
tighter bound is the next lever.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

Generate an instance and write it to JSON:

```bash
.venv/bin/python scripts/generate.py --seed 42 --tasks 20 --days 7
```

Inspect it in human-readable form — this is the Phase 0 gate:

```bash
.venv/bin/python scripts/inspect_data.py
```

### Reproducing the numbers without an API key

The RailRadar responses and the derived section file are **committed**
(`data/cache/railradar/`, `data/grounded_sections.json`). They are public
timetable data, and tracking them means every figure here can be reproduced
offline by anyone, with no key and no network. `--offline` forces cache-only:

```bash
.venv/bin/python scripts/fetch_timetable.py --from-train 64422,64076,64464,64908 --offline
```

### Fetching fresh timetable data

Get a free sandbox key (1,000 requests/month) at
<https://railradar.in/developers>, then put it in a `.env` file in the repo
root — `.env` is gitignored, so the key is never committed:

```bash
cp .env.example .env
```

Edit `.env` and replace the placeholder with your key. Then confirm the
response shape with one request:

```bash
.venv/bin/python scripts/probe_api.py --station NDLS
```

Then build real section profiles. Deriving the corridor from a train's route
guarantees the station pairs are physically adjacent:

```bash
.venv/bin/python scripts/fetch_timetable.py --from-train 12002 --start NDLS --end GZB
```

Cost is 1 request for the route plus 1 per station. Responses are cached to
disk permanently and never re-fetched, so re-runs are free and the job is
resumable. Then:

```bash
.venv/bin/python scripts/inspect_data.py --grounded
```

### Solve

```bash
.venv/bin/python scripts/optimise.py --grounded
```

Prints the permitted windows per section, the block plan as a text table, and
the train-hours lost. `--percentile` controls how much of each section's day
is open to planned work (default: quietest 25%).

### Before / after — the headline number

```bash
.venv/bin/python scripts/compare.py --grounded --tasks 300 --days 30
```

### Browser UI

```bash
.venv/bin/uvicorn src.api.app:app --port 8077
```

Then open <http://localhost:8077>. Four views: block plan (Gantt, coloured by
department, shared blocks hatched), before/after, criticality with per-task
explanations, and section traffic profiles.

Built on a Data-Dense Dashboard system: light and dark themes from one set of
semantic tokens, Fira Sans/Fira Code with tabular figures so numbers do not
jitter between solves, and a 4px spacing rhythm.

Accessibility was verified in the browser, not assumed:

- Contrast measured in both themes — 6.3:1 to 16.6:1 light, 7.4:1 to 16.5:1
  dark, against a 4.5:1 requirement.
- Every control is at least 44x44px; tabs follow the WAI-ARIA pattern with
  arrow-key navigation and roving `tabindex`.
- Skip link, visible focus rings, `aria-live` status, and
  `prefers-reduced-motion` honoured.
- **Nothing depends on colour alone.** Shared blocks are hatched as well as
  coloured; at the 30-day view bars are only 3-4px wide, so department
  identity is carried by the tooltip and by the full block table rendered
  beneath every Gantt — which is also what a screen reader reads, since an
  SVG chart is not content.

No build step and no JS dependencies, so the demo cannot fail because of a
network. Fonts come from Google with `font-display:swap` behind a full system
fallback: offline the page is typographically plain but entirely functional.
That is a deliberate departure from the brief's "React + Gantt library"; the
trade-off is discussed below.

### Recorded demo (stage backup)

```bash
.venv/bin/python scripts/demo.py --out demo_run.txt
```

Runs every stage and writes a transcript. Deterministic given the seed, so
the recording and a live run produce identical numbers.

Run the tests:

```bash
.venv/bin/python -m pytest -q
```

## Layout

```
src/models/       Pydantic data model — the shared vocabulary
src/ingest/       RailRadar client + timetable -> traffic-profile derivation
src/generator/    Synthetic instance generator (a deliverable, not a shortcut)
src/adapters/     THE BOUNDARY: DataSource interface, synthetic source,
                  hybrid (real traffic + synthetic tasks), and typed stubs
                  for the four real systems
src/optimiser/    CP-SAT model: windows.py (time grid, permitted windows),
                  model.py (solver model), replan.py (disruption re-planning)
src/ml/           Criticality scoring (LightGBM) + explainability
src/baseline/     Manual-process simulator and the before/after comparison
src/api/          FastAPI backend + dependency-free browser UI
scripts/          CLI entry points
tests/            pytest — constraint tests mandatory from Phase 1
```

### The adapter boundary

`src/adapters/base.py` defines `DataSource`. `SyntheticDataSource` is the only
implementation that returns data today; `TMSAdapter`, `SMMSAdapter`,
`TDMSAdapter` and `COAAdapter` declare the integration contract and raise
`NotYetIntegrated` when loaded. They report `[NOT CONNECTED]`, never `[LIVE]`.

`tests/test_adapter_boundary.py` fails the build if anything downstream
imports the generator directly, so "real feeds plug in here" stays true rather
than becoming a slide claim.


## Departures from the brief, and why

Three, each forced by measurement rather than preference:

1. **The peak-hour rule is per-section, not a flat `trains_per_hour > 8`.**
   Real traffic kills the flat rule: Sahibabad–Ghaziabad never drops below
   2.9 trains/hour and offers no contiguous sub-8 window longer than 2 hours,
   so every task over 120 minutes there would have been infeasible. Each
   section's quietest 25% of hours is now the permitted set. (A-14)

2. **NoOverlap applies to blocks, not tasks.** Applied to tasks it would
   forbid two departments working one section at once — precisely the
   coordination the project exists to demonstrate. Tasks nest inside blocks;
   blocks are what cannot overlap.

3. **The UI is plain JS and SVG rather than React.** The brief says "keep it
   simple", and a demo that cannot be broken by a slow CDN or hostile venue
   wifi was worth more than the framework. Everything asked for is there:
   department colour-coding, shared-block highlighting, weekly/monthly
   toggle, KPI dashboard, before/after view — plus light/dark theming and a
   measured accessibility pass.

## Honest limitations

- **Maintenance periodicities are still provisional.** No IRPWM clause
  numbers are cited because none have been read. Fabricating them would be
  the worst thing we could do to our own credibility. (A-01)
- **Freight is invisible.** Goods paths are absent from public timetables, so
  night traffic on real sections is undercounted — the one axis where our
  figures could flatter us. (A-04)
- **The failure hazard the ML model learns is one we wrote.** The model earns
  its place by combining features into an explainable ranking that can be
  retrained on real history, not by discovering the relationship. Held-out
  AUC is 0.68, which is what learning from noisy events should look like.
  (A-08)
- **The improvement scales with backlog density** — sparse work offers fewer
  chances to merge blocks. Always quote the instance size.
- **The headline varies run to run** (9.5–24.5% over four runs) because
  parallel time-limited search is not reproducible, and single-worker or
  deterministic-time alternatives were measured and are unusable. The data is
  fully deterministic; the search is not. (A-19)
- **A filed report does not change the plan you are looking at.** Intake
  records a defect and prices what closing for it would cost; it does not
  re-solve. Plans are solved at build time and served from cache, so an
  accepted report enters the backlog the next run draws from. Saying a report
  had rescheduled the month when it had not would be the easiest lie in the
  system to tell and the hardest to notice.
- **The intake form offers the same activity catalogue the optimiser
  schedules from.** That is why it cannot accept free-text work: a report
  naming an activity the planner has never heard of could never be placed.
  The periodicities in that catalogue are still provisional, and the form
  carries their provenance string rather than presenting them as mandated.
