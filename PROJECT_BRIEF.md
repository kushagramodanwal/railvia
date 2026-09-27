# PROJECT_BRIEF.md — Automatic Block Planning (SIH26027)

> Drop this file in the repo root. Claude Code should read it before every work session
> and treat it as the source of truth for scope, constraints, and build order.
>
> Problem statement: SIH26027, Ministry of Railways.
> Idea submission deadline: 20 September 2026.

---

## 1. Domain glossary — read this first

Nobody on the team is a railway engineer. These terms appear constantly.

| Term | Meaning |
|------|---------|
| **Block** | A scheduled window during which a stretch of track is taken out of service so maintenance can happen. Trains cannot run through it. |
| **Disconnection** | Similar, for signalling/electrical equipment rather than track itself. |
| **Section** | A stretch of track between two points. The unit we schedule against. |
| **Corridor** | A pre-identified window where blocks are easier to grant (low traffic). |
| **ENGG** | Engineering department — track, ballast, rails, bridges. |
| **TRD** | Traction Distribution — overhead electrical wires. |
| **S&T** | Signal & Telecommunications — signalling gear, cables. |
| **BDMS** | Block Demand Management System. Where each department requests blocks today, manually and independently. |
| **TMS / SMMS / TDMS** | Track / Signalling / Traction maintenance systems. Three separate defect and task databases, one per department. |
| **COA** | Control Office Application. Holds the train timetable and corridor availability. |
| **IRPWM** | Indian Railways Permanent Way Manual. Public document specifying how often each maintenance activity must be done. **This is our main grounding source for realistic data.** |

**The core problem in one sentence:** three departments request track-blocking windows
independently, so the same section gets blocked three times when one shared block would
have done, and nobody optimises against the train timetable.

---

## 2. What we are building

A system that ingests maintenance tasks from all three departments plus the train
timetable, and produces a single coordinated block schedule that completes the required
maintenance while losing the fewest train-hours.

```
Synthetic data generator ─┐
  TMS defects (ENGG)      │
  SMMS defects (S&T)      ├─→ Adapter layer ─→ Unified data model
  TDMS defects (TRD)      │        ↑
  COA timetable           │   (real feeds plug in here)
  Goods train forecast   ─┘        │
                                   ▼
                    ML criticality & urgency scoring
                                   │
                    CP-SAT optimiser  ← THE CORE
                                   │
                 Weekly + monthly block plans
                                   │
              Gantt UI · conflict view · KPI dashboard
                                   │
              Baseline comparison ← THE HEADLINE NUMBER
```

---

## 3. The honesty constraint — non-negotiable

**There is no dataset provided.** TMS, SMMS, TDMS and COA are internal Railways systems
we cannot access. We generate synthetic data.

This is the single biggest credibility risk in the project. Handle it as follows:

1. The **data generator is a deliverable**, not a shortcut. It gets its own module, its
   own documentation, and a slide in the deck.
2. Every distribution and parameter must be **grounded in a citable public source** —
   IRPWM maintenance intervals, published zonal timetables, real section names from a
   real division. Record the source in a comment next to every constant.
3. Maintain `ASSUMPTIONS.md` listing every modelling assumption with its justification.
4. The **adapter layer is a visible architectural boundary**, so we can say precisely
   where real TMS/SMMS/TDMS feeds would connect.

Never present synthetic data as real. State it plainly and show the integration point.
Judges punish teams that hide this and respect teams that own it.

---

## 4. Tech stack — decided, do not re-litigate

| Layer | Choice | Notes |
|-------|--------|-------|
| Language | Python 3.11+ | |
| Optimiser | **Google OR-Tools, CP-SAT solver** | Apache-2.0. The correct tool for this problem class. |
| ML scoring | scikit-learn or LightGBM | Small tabular ranking problem. Nothing deep. |
| Data | pandas, pydantic models | |
| Backend | FastAPI | |
| Frontend | React + a timeline/Gantt library | Keep it simple. `vis-timeline` or `frappe-gantt`. |
| Storage | SQLite | Sufficient. Do not introduce Postgres. |
| Testing | pytest | Constraint tests are mandatory, see §9 |

**Explicit anti-requirement:** do NOT use a neural network to generate schedules
directly. Scheduling is a constraint satisfaction problem with a provably correct
formulation. A learned scheduler will perform worse and will be torn apart by any judge
with an operations research background. ML belongs only in criticality scoring (§6).

---

## 5. Data model

Keep this small and explicit. Pydantic models in `src/models/`.

```python
Section:       id, name, division, length_km, traffic_density_profile[24h]
Task:          id, department (ENGG|TRD|S&T), section_id, activity_type,
               duration_minutes, crew_required, last_done_date,
               interval_days (from IRPWM), due_date, defect_severity,
               is_overdue, co_locatable (bool)
TrafficWindow: section_id, hour_of_day, day_of_week, trains_per_hour,
               is_goods_forecast (bool)
Block:         id, section_id, start, end, task_ids[], departments[]
CrewCapacity:  department, date, available_crews
```

`traffic_density_profile` is what makes the optimiser interesting — blocking a section
at 03:00 costs far fewer train-hours than blocking it at 09:00. This must be modelled
per section per hour, not as a flat constant.

---

## 6. Where ML belongs

**One job only: score each pending task for criticality and urgency.**

- **Input features:** defect severity, days overdue, activity type, section traffic
  density, days since last maintenance, historical failure rate for that activity type,
  time to next mandated inspection.
- **Output:** a priority weight in [0, 1] used by the optimiser's objective function.
- **Model:** gradient-boosted ranking (LightGBM) or a simple regressor. Train on the
  synthetic history the generator produces.
- **Must be explainable.** Produce SHAP or feature-importance output. A judge will ask
  why one task outranked another, and "the model decided" is a losing answer.

Everything else is optimisation, not learning.

---

## 7. The optimiser — core specification

CP-SAT model in `src/optimiser/`.

**Decision variables**
- One optional interval variable per task: `start`, `duration` (fixed per task), `end`,
  `is_present` (bool — allows a task to go unscheduled at a penalty).
- Block assignment: tasks on the same section with overlapping intervals are merged
  into one block.

**Constraints**
1. `NoOverlap` per section — two blocks cannot occupy the same section simultaneously.
2. Forbidden windows — no block during peak traffic hours above a configurable
   threshold (start with: no blocks where `trains_per_hour > 8`).
3. Crew capacity — `Cumulative` constraint per department per day; cannot schedule more
   simultaneous tasks than crews available.
4. Deadline — any task with `is_overdue` or a `due_date` inside the horizon must be
   scheduled before its due date, or incur a heavy penalty.
5. Horizon bounds — all intervals within the planning window (7 days or 30 days).

**Objective — minimise**
```
  Σ over blocks:  block_duration_hours × traffic_density(section, time_window)
+ Σ over unscheduled tasks:  criticality_weight × UNSCHEDULED_PENALTY
+ Σ over late tasks:  days_late × criticality_weight × LATE_PENALTY
```

The first term is **train-hours lost**. That is the number we report.

**Co-location reward:** merging two departments' tasks into one shared block halves the
train-hours cost of that work. This falls out naturally from the objective — do not
hardcode a bonus, let the optimiser discover it. Then point it out in the deck, because
this is exactly the coordination failure the problem statement describes.

**Solve limits:** cap at 60 seconds wall time. Accept the best feasible solution found.
CP-SAT will run for hours on a large instance otherwise, and a live demo cannot wait.

---

## 8. The baseline simulator — do not skip this

**This produces the single most important number in the entire project.**

Simulate the current manual process: each department independently requests blocks for
its own overdue tasks, first-come-first-served, with no cross-department coordination and
no traffic-aware placement.

Then compare:

| Metric | Manual baseline | Our system |
|--------|-----------------|------------|
| Total train-hours lost | X | Y |
| Number of separate blocks | | |
| Overdue tasks completed | | |
| Blocks shared across departments | 0 | N |
| Peak-hour blocks | | |

The headline claim on slide 2 of the deck is the reduction in train-hours lost, stated
with the section count and horizon — for example: *"31% fewer train-hours lost across a
4-week horizon on a 120 km section with 3 departments."*

A working optimiser with no baseline comparison is worth far less than an average
optimiser with a rigorous one.

---

## 9. Build order — strict phases, stop at every gate

Do not scaffold the whole system up front. Each phase must run and be verified before
the next begins.

### Phase 0 — Data model + tiny generator
Pydantic models. Generator producing **5 sections, 20 tasks, 1 week horizon**. Hardcoded
traffic profile. Output to JSON.
**GATE:** we can inspect the generated data and it looks structurally sane.

### Phase 1 — Minimum viable optimiser
CP-SAT model on that tiny instance. Constraints 1, 2, 5 only. Objective: train-hours
only. Print the resulting schedule as a text table.
**GATE:** solver returns FEASIBLE, and constraint tests pass. This is the highest-risk
gate — if CP-SAT modelling stalls here, say so immediately rather than working around it.

**Constraint tests are mandatory from this phase onward.** For every constraint, a
pytest that constructs a violating schedule and asserts the model rejects it. Silent
constraint bugs are the number one way this project fails invisibly — the solver returns
a schedule, it looks plausible, and it is wrong.

### Phase 2 — Realistic scale + full constraints
Generator grounded in IRPWM intervals and a real division's section list. Scale to
~40 sections, ~300 tasks. Add crew capacity and deadline constraints. Add the 30-day
horizon.

### Phase 3 — Criticality model + baseline
LightGBM criticality scorer feeding objective weights. Explainability output. Baseline
simulator per §8. First real comparison numbers.

### Phase 4 — API + UI
FastAPI endpoints. React frontend: Gantt timeline of blocks colour-coded by department,
conflict view, KPI dashboard, weekly/monthly toggle, before/after comparison view.

### Phase 5 — Polish
Goods-train forecast uncertainty. Scenario re-planning (a task overruns, re-optimise).
Performance tuning. Recorded demo run as stage backup.

---

## 10. Engineering standards

- **Adapter layer is a real boundary.** A `DataSource` interface with
  `SyntheticDataSource` plus stub `TMSAdapter` / `SMMSAdapter` / `TDMSAdapter` /
  `COAAdapter`. The optimiser must never import the generator directly.
- **Every magic constant carries a source comment.** `INTERVAL_DAYS = 90  # IRPWM §4.2.1`
- **Determinism.** Seed the generator. Reproducible runs, or the numbers in the deck
  cannot be defended.
- **Log solver output** — status, objective value, wall time, optimality gap.
- **No premature UI work.** Phase 4 exists for a reason. A beautiful Gantt chart showing
  a bad schedule loses to an ugly table showing a 31% improvement.

---

## 11. How to work with me on this

- Work **one phase at a time**. Do not generate Phases 0–5 in a single pass.
- After each phase, **stop and tell me what to run and what output confirms success.**
- When formulating CP-SAT constraints, **explain the formulation in plain language
  before writing code.** Nobody on this team has used OR-Tools before, and we need to
  answer judge questions about the model ourselves.
- If a constraint could be modelled several ways, **state the trade-off** (solve time vs
  solution quality) and let me choose.
- When I paste a solver error or an INFEASIBLE status, diagnose the specific constraint
  conflict — do not rewrite the whole model.
- Prefer boring, verifiable solutions over clever ones. This ships in three weeks.

---

## 12. Definition of done

- [ ] Generator produces IRPWM-grounded data for ≥40 sections, ≥300 tasks, 3 departments
- [ ] `ASSUMPTIONS.md` documents every modelling assumption with a public source
- [ ] CP-SAT optimiser solves the full instance within 60 seconds
- [ ] Constraint tests pass for all five constraints
- [ ] Criticality model trained, with feature-importance output
- [ ] Baseline simulator implemented; before/after comparison table produced
- [ ] Weekly and monthly horizons both supported
- [ ] Gantt UI with department colour-coding, conflict view, KPI dashboard
- [ ] Adapter layer clearly separates synthetic source from real-feed stubs
- [ ] Headline metric measured and reproducible: **% reduction in train-hours lost**
- [ ] Recorded demo run available as stage backup