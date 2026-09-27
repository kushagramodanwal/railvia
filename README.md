<div align="center">

# 🚂 RailVia — Automatic Block Planning
### AI-Powered Multi-Department Maintenance Scheduling & Traffic De-Confliction Engine
**Ministry of Railways — Smart India Hackathon (Problem Statement: SIH26027)**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%20%7C%203.13-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![OR-Tools CP-SAT](https://img.shields.io/badge/solver-Google%20OR--Tools%20CP--SAT-FF6F00.svg)](https://developers.google.com/optimization)
[![LightGBM](https://img.shields.io/badge/ML-LightGBM-brightgreen.svg)](https://lightgbm.readthedocs.io/)
[![Next.js 15](https://img.shields.io/badge/frontend-Next.js%2015-black.svg?logo=next.js&logoColor=white)](https://nextjs.org/)
[![TypeScript](https://img.shields.io/badge/types-TypeScript-3178C6.svg?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Database](https://img.shields.io/badge/storage-Supabase%20PostgreSQL%20(RLS)-3ECF8E.svg?logo=supabase&logoColor=white)](https://supabase.com)
[![Tests](https://img.shields.io/badge/tests-235%20passed-success.svg)]()
[![Docker](https://img.shields.io/badge/container-Docker%20Multi--Stage-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)

<p align="center">
  <strong>RailVia</strong> synchronizes track possession demands across Civil Engineering (<b>ENGG</b>), Electrical Traction (<b>TRD</b>), and Signalling (<b>S&T</b>) against live train timetables — automatically consolidating siloed maintenance requests into optimal shared windows that minimize network-wide passenger and freight delays.
</p>

</div>

---

## 📋 Table of Contents
1. [Executive Summary & Problem Statement](#-executive-summary--problem-statement)
2. [Domain Glossary](#-domain-glossary)
3. [Headline Results & Benchmarks](#-headline-results--benchmarks)
4. [End-to-End System Architecture](#-end-to-end-system-architecture)
5. [Algorithmic Deep Dive: Google OR-Tools CP-SAT](#-algorithmic-deep-dive-google-or-tools-cp-sat)
   - [The Combinatorial Challenge (NP-Hard)](#the-combinatorial-challenge-np-hard)
   - [The "Permitted Run" Breakthrough](#the-permitted-run-breakthrough)
   - [Prefix-Sum Cost Lookups (O(1) Evaluation)](#prefix-sum-cost-lookups-o1-evaluation)
   - [Cost-Per-Block Formulation (Natural Co-Location)](#cost-per-block-formulation-natural-co-location)
   - [Hard & Soft Constraints Modeled](#hard--soft-constraints-modeled)
6. [Machine Learning Pipeline: LightGBM Predictive Urgency](#-machine-learning-pipeline-lightgbm-predictive-urgency)
   - [Feature Engineering & Risk Prioritization](#feature-engineering--risk-prioritization)
   - [Coupling ML Scores into the Optimizer Objective](#coupling-ml-scores-into-the-optimizer-objective)
   - [Explainable AI (Feature Gain Attribution)](#explainable-ai-feature-gain-attribution)
7. [Dynamic Re-Planning & Disruption Handling](#-dynamic-re-planning--disruption-handling)
8. [Web Operations Dashboard](#-web-operations-dashboard)
9. [Role-Based Access Control (RBAC) & Security](#-role-based-access-control-rbac--security)
10. [REST API Reference](#-rest-api-reference)
11. [Repository Layout](#-repository-layout)
12. [Quick Start & Local Setup](#-quick-start--local-setup)
13. [CLI & Development Commands](#-cli--development-commands)
14. [Deployment (Docker & Render Cloud)](#-deployment-docker--render-cloud)
15. [Data Provenance & IRPWM Grounding](#-data-provenance--irpwm-grounding)

---

## 🎯 Executive Summary & Problem Statement

### The Status Quo in Indian Railways
Track maintenance across Indian Railways is managed across three independent departmental silos:
* **ENGG (Permanent Way / Civil)**: Heavy track renewal, tamping, deep screening, rail grinding, and sleeper renewal.
* **TRD (Traction Distribution)**: Overhead catenary wire (OHE) inspection, neutral section overhauls, and power disconnections.
* **S&T (Signal & Telecommunication)**: Point machine overhauls, track circuit testing, axle counters, and electronic interlocking.

Currently, each department requests track-blocking windows through separate legacy systems (**TMS**, **TDMS**, **SMMS**). These demands are submitted to divisional traffic controllers via **BDMS** (Block Demand Management System) and reconciled manually on paper or whiteboards.

### The Consequences of Manual Planning
1. **Redundant Track Closures**: The exact same track section is often shut down three separate times in a single month because departments do not coordinate their windows.
2. **Severe Delay Cascades**: Maintenance blocks granted during traffic surges ripple across busy trunk corridors, forcing express passenger and freight trains to be looped or delayed.
3. **Emergency Bottlenecks & High Cancellation Rates**: Due to timetable pressure, controllers frequently refuse blocks or grant shortened durations, causing dangerous maintenance backlogs and emergency speed restrictions (TSRs).

### The RailVia Solution
**RailVia** replaces fragmented manual scheduling with a unified, mathematical optimization engine. It combines:
1. **LightGBM Predictive Modeling** to score track degradation risk and prioritize safety-critical defects.
2. **Google OR-Tools CP-SAT** to solve the multi-resource, non-overlapping slot allocation problem.
3. **Shadow Block Co-Location**: When ENGG receives a track possession, RailVia automatically nests TRD and S&T tasks inside the same window, transforming 3 separate closures into **1 synchronized block**.
4. **Dynamic Re-Planner**: Real-time recovery for when track machines break down or possessions overrun.

---

## 📖 Domain Glossary

| Term | Description |
|---|---|
| **Block (Traffic Possession)** | A scheduled operational window during which a stretch of track is completely closed to regular trains so maintenance teams can work safely. |
| **Power Block (OHE Disconnection)** | Shutting down the 25kV AC overhead catenary electrical supply for TRD work. Electric trains cannot traverse this stretch during the block. |
| **Section** | A discrete railway block section between two stations/signals (the fundamental spatial unit of scheduling). |
| **Corridor Margin** | Pre-identified off-peak windows in the master working timetable where traffic density falls below operational thresholds. |
| **BDMS** | Block Demand Management System — Indian Railways' portal where departments submit possession requests. |
| **TMS / TDMS / SMMS** | Track Management System (ENGG), Traction Distribution Management System (TRD), and Signal Maintenance Management System (S&T). |
| **COA** | Control Office Application — Indian Railways' central system tracking live train movements and timetable paths. |
| **IRPWM** | Indian Railways Permanent Way Manual — The statutory technical standard dictating maintenance periodicity, gang strength, and machine output. |
| **GMT** | Gross Million Tonnes — The cumulative tonnage of freight and passenger traffic that has passed over a rail section, driving mechanical fatigue. |

---

## 📊 Headline Results & Benchmarks

Benchmarked on **39 real railway sections** across the busy Delhi-Ghaziabad-Kanpur trunk route over a **30-day horizon (2,880 fifteen-minute slots)** with **300+ maintenance backlog tasks**:

| Metric | Manual Process (Baseline) | RailVia (CP-SAT Coordinated) | Operational Significance |
|---|---|---|---|
| **Train-Hours Lost** | Uncoordinated High | **~35% Reduction** *(Range: 28.5% – 41.6%)* | Measured across four 60s solver runs; protects passenger punctuality. |
| **Multi-Dept Co-located Blocks** | **0** (All isolated) | **21 to 37 Shared Blocks** | ENGG, TRD, and S&T work inside the same shadow window. |
| **Peak-Hour Disruptions** | **8 Disruptions** | **0 (Zero peak blocks granted)** | 100% adherence to section traffic curfews. |
| **Tasks Completed** | Standard Backlog | **+54 Additional Tasks Completed** | Maximizes equipment utilization without congesting the corridor. |
| **Late Tasks** | 135 Tasks | **93 to 115 Tasks** (~25% improvement) | Reduced overdue safety-critical track defects. |
| **Solve Latency** | Hours of manual phone calls | **< 5 Seconds (CP-SAT)** | Real-time interactive turnaround for division controllers. |
| **Cached API Response** | N/A | **< 50 Milliseconds** | Instantaneous browser rendering via in-memory cache warming. |

> [!NOTE]
> All benchmarks quote the full measured range across multiple seeds rather than cherry-picking the best run. For full experimental methodology, see [ASSUMPTIONS.md](ASSUMPTIONS.md).

---

## 🏗️ End-to-End System Architecture

```
                    [ INCOMING DATA SOURCES ]
        RailRadar Live Timetable Feeds     IRPWM Statutory Maintenance Rules
      (Real Delhi-Ghaziabad Corridors)    (Machine outputs, periodicities)
                     │                                  │
                     ▼                                  ▼
      ┌─────────────────────────────────────────────────────────────┐
      │               1. RAILWAY ADAPTER LAYER                      │
      │   - Discretizes 30 days into 2,880 15-min slots (TimeGrid)  │
      │   - Tracks provenance: synthetic tasks vs. grounded traffic │
      │   - Enforces IRPWM safety limits & gang resource quotas     │
      └──────────────────────────────┬──────────────────────────────┘
                                     │
                                     ▼
      ┌─────────────────────────────────────────────────────────────┐
      │            2. PREDICTIVE CRITICALITY ENGINE                 │
      │   - LightGBM Regressor models asset failure urgency (0-100) │
      │   - Factors: GMT, rail age, track geometry, weather, dept   │
      │   - Outputs SHAP / gain-based explainability factors        │
      └──────────────────────────────┬──────────────────────────────┘
                                     │ Dynamic Task Penalty Weights
                                     ▼
      ┌─────────────────────────────────────────────────────────────┐
      │         3. GOOGLE OR-TOOLS CP-SAT OPTIMIZATION              │
      │   - "Permitted Run" formulation (pre-computes quiet windows)│
      │   - Prefix-Sum Lookups for O(1) train disruption cost       │
      │   - Cost-Per-Block Formulation (discovers co-location)      │
      │   - Hard Constraints: Non-overlap, crew quota, power blocks │
      └──────────────┬──────────────────────────────┬───────────────┘
                     │                              │
                     ▼                              ▼
      ┌─────────────────────────────┐┌──────────────────────────────┐
      │  4. DYNAMIC RE-PLANNER      ││  5. FASTAPI REST ENGINE      │
      │  - Freezes past execution   ││  - Asynchronous endpoints    │
      │  - Injects machine overruns ││  - Lifespan cache-warming    │
      │  - Re-solves remaining days ││  - Strict Pydantic schemas   │
      └─────────────────────────────┘└──────────────┬───────────────┘
                                                    │
                                                    ▼
      ┌─────────────────────────────────────────────────────────────┐
      │            6. MODERN NEXT.JS 15 WEB DASHBOARD               │
      │   - Interactive 24-Hour Gantt Timeline (Trains vs Blocks)   │
      │   - 30-Day Matrix & Geographic Corridor Bottleneck Map      │
      │   - Disruption Simulator (What-If scenario injection)       │
      │   - Dual-Role Workflow: DRM Sanction vs SE Completion Logs  │
      │   - Cryptographic Supabase PostgreSQL Row-Level Security    │
      └─────────────────────────────────────────────────────────────┘
```

---

## 🧮 Algorithmic Deep Dive: Google OR-Tools CP-SAT

### The Combinatorial Challenge (NP-Hard)
Scheduling 300+ maintenance tasks across 39 sections over 30 days (discretized into 15-minute intervals = 2,880 slots) represents a massive combinatorial search space:
$$\text{Search Space} \approx \prod_{i=1}^{M} (\text{Candidate Start Slots for Task } i)$$
With crew capacity ceilings, machine movement constraints, and train timetable interactions, finding a feasible—let alone optimal—schedule is strongly NP-hard.

---

### The "Permitted Run" Breakthrough
A naive CP-SAT formulation treats each task's start time as an integer variable floating freely across all 2,880 slots:
* It requires pairwise `NoOverlap` interval constraints for every task combination on a section.
* It requires thousands of boolean indicators to prevent tasks from crossing into morning and evening rush hours.
* **The Failure**: On a 39-section instance, CP-SAT presolve expanded into **millions of boolean clauses**, failing to find a single feasible solution in 25 seconds.

**RailVia's Formulation**:
1. We compute **"Permitted Runs"** in preprocessing (`src/optimiser/windows.py`): maximal contiguous stretches of hours where hourly train volume is in the bottom 25th percentile for that section.
2. Runs on any section are **disjoint by construction** (they never overlap).
3. We bind blocks to candidate runs:
   $$\text{Run } r = [\text{start}_r, \text{end}_r)$$
   $$\text{block\_start} \ge \text{start}_r \quad \text{and} \quad \text{block\_end} \le \text{end}_r$$
* **Zero Overlap Constraints Needed**: Because runs on the same section never overlap, candidate blocks assigned to separate runs cannot collide!
* **Zero Peak Straddling**: Work is structurally barred from peak rush hours without a single boolean penalty constraint.
* **Solve time plummeted from >25s (timeout) to <5s**.

---

### Prefix-Sum Cost Lookups ($O(1)$ Evaluation)
Calculating the train disruption cost of a maintenance window $[t_{\text{start}}, t_{\text{end}}]$ normally requires looping through all slots in between and summing traffic. In a solver, this requires hundreds of thousands of auxiliary variables.

RailVia precomputes a **Prefix Sum Array** (`cumulative_train_hours` in [windows.py](file:///Users/hemam/Projects/RailVia/src/optimiser/windows.py#L149-L163)):
$$\text{Cost}(t_{\text{start}}, t_{\text{end}}) = \text{CumulativeTraffic}[t_{\text{end}}] - \text{CumulativeTraffic}[t_{\text{start}}]$$
* Multiplied by an integer scaling factor ($100$) to allow CP-SAT's integer engine to evaluate train-hours to two decimal places with a single subtraction.

---

### Cost-Per-Block Formulation (Natural Co-Location)
Instead of penalizing each individual maintenance task, RailVia calculates traffic disruption **per block**:
$$\text{Objective} = \min \left( \sum_{b \in \text{Blocks}} \text{TrainDisruption}(b) + \sum_{t \in \text{Tasks}} \left( \text{UnscheduledPenalty}(t) + \text{LatenessPenalty}(t) \right) \right)$$
* If ENGG and TRD share block $b$, the train disruption cost is paid **only once**.
* The optimizer naturally groups maintenance tasks into shared multi-department windows without needing ad-hoc bonus heuristics.

---

### Hard & Soft Constraints Modeled

```
+-----------------------------------------------------------------------------------+
| HARD CONSTRAINTS (Never Violated)                                                |
+-----------------------------------------------------------------------------------+
| 1. Non-Overlapping Section Track Possession (Enforced via Permitted Runs)        |
| 2. Department Crew Quota per Day: sum(crews) <= DailyLimit (Cumulative)          |
| 3. Traction Compatibility: TRD catenary power shutdown halts electric traction    |
| 4. Horizon Boundaries: block_start >= 0 and block_end <= HorizonSlots            |
| 5. Mutually Exclusive Machinery: Specialized tamping machines cannot split       |
+-----------------------------------------------------------------------------------+
| SOFT CONSTRAINTS (Priced in Objective)                                           |
+-----------------------------------------------------------------------------------+
| 1. Train Disruption: Train-hours lost across blocked slots                        |
| 2. Task Lateness: Penalized per day past statutory IRPWM inspection deadline      |
| 3. Unscheduled Tasks: Heavily penalized, weighted by LightGBM Criticality Score   |
+-----------------------------------------------------------------------------------+
```

---

## 🤖 Machine Learning Pipeline: LightGBM Predictive Urgency

RailVia combines Machine Learning with Constraint Optimization: **LightGBM decides *what* is critical; CP-SAT decides *when and where* it can safely fit.**

```
[ Track Health & Operational Data ]
  - Cumulative Tonnage (GMT)
  - Asset Age & Rail Metallurgy
  - Historical Ultrasonic Flaw (USFD) Reports
  - Section Traffic Density (Trains/Hour)
  - Department Urgency (ENGG vs TRD vs S&T)
                  │
                  ▼
       [ LightGBM Regressor ]
  - Gradient Boosted Decision Trees
  - Non-linear feature interaction
  - Fast tabular inference (<2ms)
                  │
                  ▼
       [ Criticality Score (0-100) ]
                  │
                  ├───────────────────────────────┐
                  ▼                               ▼
     [ Downstream CP-SAT Weights ]    [ Transparent SHAP Attribution ]
  - Unscheduled Penalty = w_base * Score   - Explains *why* track section
  - Critical tasks prioritized in tight     is at risk to Section Engineers
    crew availability windows.
```

### Feature Engineering & Risk Factors
Located in `src/ml/criticality.py` and `src/ml/features.py`:
* **`gmt_accumulated`**: High cumulative tonnage accelerates rail head fatigue and micro-fractures.
* **`days_since_last_service`**: Tracks statutory overdue status against IRPWM intervals.
* **`traffic_density`**: Sections handling >8 trains/hour receive higher risk ratings due to braking stress.
* **`department_weight`**: Structural rail integrity (ENGG) carries higher baseline risk than routine vegetation trimming.

### Explainable AI (XAI)
Every task scored by the ML pipeline produces a breakdown of feature contributions:
* Section engineers and the Divisional Railway Manager (DRM) can inspect `/api/criticality/{task_id}` to see whether a high score was driven by accumulated GMT, overdue inspection days, or section traffic density.

---

## 🔄 Dynamic Re-Planning & Disruption Handling

A maintenance schedule never survives intact for 30 days:
* A heavy tamping machine blows a hydraulic line.
* An emergency rail fracture occurs on an adjacent main line.
* A possession handover is delayed by 90 minutes.

### The Rolling-Horizon Re-Planner (`src/optimiser/replan.py`)
Rather than forcing operators to scrap the entire schedule, RailVia provides real-time disruption recovery:

```
                  Disruption at Slot T (e.g., Day 4, 02:30 AM)
                                      │
       ┌──────────────────────────────┴──────────────────────────────┐
       ▼                                                             ▼
[ FROZEN PAST (Slots 0 to T) ]                   [ UNCOMMITTED FUTURE (Slots T to End) ]
- Work completed is marked DONE.                 - Tasks in progress have their sections
- Past train delays are locked.                    locked for the duration of the overrun.
                                                 - Pending tasks are dynamically re-solved
                                                   over the remaining horizon.
```

> [!IMPORTANT]
> **Honest Operational Reporting**: Because the remaining time horizon is shorter, re-planning can legitimately result in a slightly higher train-hour cost than the original plan. RailVia reports the **exact `train_hours_delta`** rather than artificially claiming impossible improvements.

---

## 🖥️ Web Operations Dashboard

Built with **Next.js 15**, **React 19**, and **TypeScript**, RailVia provides an operational dashboard tailored for Indian Railways division headquarters:

* **Interactive 24-Hour Gantt Timeline**: Displays live train movements alongside active maintenance blocks. Shows multi-department overlap bars and identifies corridor quiet margins.
* **30-Day Calendar Matrix**: High-level overview of planned closures across all 39 sections, color-coded by department.
* **Network Topology & Bottleneck Map**: Geographic schematic of the railway network highlighting heavily congested junctions (e.g., Ghaziabad Junction, Sahibabad).
* **Disruption Simulator ("What-If" Engine)**: Allows controllers to inject synthetic machine overruns or emergency closures and view the re-planned schedule in seconds.
* **Indian Railways Branding**: Responsive full-screen interface featuring official Indian Railways insignias and high-contrast night modes for Control Office lighting.

---

## 🔒 Role-Based Access Control (RBAC) & Security

RailVia enforces strict authority separation using **PostgreSQL Row-Level Security (RLS)** via Supabase (`src/store/schema.sql`):

| Role | Interface Endpoint | Authorized Operations |
|---|---|---|
| **Divisional Head (DOM / DRM)** | `/api/approvals` | Reviews conflicting block requests, approves/rejects proposed maintenance windows, and executes schedule re-optimizations. |
| **Section Engineer (P-Way / TRD / S&T)** | `/api/completions` | Views sanctioned blocks for their jurisdiction, acknowledges assigned crew windows, and logs field completion timestamps and machine outputs. |

```sql
-- Example Row-Level Security Policy for DRM Approvals
CREATE POLICY "Only divisional controllers can insert approvals"
  ON block_approvals
  FOR INSERT
  WITH CHECK (auth.jwt() ->> 'role' = 'divisional_head');
```

---

## 📡 REST API Reference

RailVia's backend is powered by **FastAPI** (`src/api/app.py`) with automatic schema validation, asynchronous execution, and in-memory plan caching.

| Method | Endpoint | Description | Key Parameters |
|---|---|---|---|
| `GET` | `/api/health` | Service health status, uptime, and cache readiness. | None |
| `GET` | `/api/instance` | Active planning instance metadata, sections, and task counts. | None |
| `GET` | `/api/plan` | Returns the optimized schedule, blocks, task assignments, and KPIs. | `regenerate=false`, `seed=42` |
| `GET` | `/api/comparison` | Benchmark comparison between uncoordinated baseline and RailVia. | `percentile=25` |
| `GET` | `/api/network` | Full station section graph, connectivity, and track parameters. | None |
| `GET` | `/api/traffic` | Hourly train counts and quiet-window classifications per section. | `section_id` |
| `GET` | `/api/criticality` | All maintenance tasks sorted by LightGBM risk score. | `department`, `min_score` |
| `GET` | `/api/criticality/{id}` | Detailed risk score breakdown and SHAP explainability factors. | `task_id` |
| `POST` | `/api/replan` | Executes rolling-horizon re-plan after an operational disruption. | `{at_slot, section_id, overrun_slots}` |
| `GET` | `/api/decisions` | Audit log of all DRM approvals and section completions. | None |
| `POST` | `/api/approvals` | DRM sanction for a scheduled maintenance block. | `{block_id, sanctioned_by}` |
| `POST` | `/api/completions` | Section Engineer execution log for a completed task. | `{task_id, actual_duration}` |

---

## 📂 Repository Layout

```
RailVia/
├── data/                      # Committed timetables & section profiles
│   ├── cache/railradar/       # Real Indian Railways Delhi corridor timetable cache
│   └── grounded/              # 39 calibrated sections with IRPWM parameters
├── deploy/                    # Production deployment templates & configs
├── scripts/                   # CLI entry points and evaluation utilities
│   ├── compare.py             # Baseline vs. CP-SAT comparison benchmark
│   ├── optimise.py            # Standalone CP-SAT solver runner
│   ├── demo.py                # Scenario re-planning & disruption demo
│   └── generate.py            # IRPWM-grounded maintenance backlog generator
├── src/                       # Core system source code
│   ├── adapters/              # Unified DataSource interfaces & data adapters
│   ├── api/                   # FastAPI backend implementation & caching
│   │   ├── app.py             # REST routes and lifespan cache warming
│   │   └── cache.py           # In-memory plan cache with file-backed persistence
│   ├── baseline/              # Greedy manual scheduling baseline simulator
│   ├── generator/             # Grounded synthetic maintenance task generator
│   ├── ingest/                # RailRadar live timetable feed ingestion
│   ├── ml/                    # Machine learning criticality ranking
│   │   ├── criticality.py     # LightGBM training, scoring & SHAP attribution
│   │   └── features.py        # Tabular feature extraction (GMT, age, traffic)
│   ├── models/                # Core Pydantic schemas (PlanningInstance, Block, Task)
│   ├── optimiser/             # Google OR-Tools CP-SAT formulation
│   │   ├── model.py           # "Permitted Run" CP-SAT solver implementation
│   │   ├── windows.py         # TimeGrid, prefix sums & quiet window calculations
│   │   ├── replan.py          # Dynamic disruption re-planning engine
│   │   └── warmstart.py       # Heuristic warm-start solution provider
│   └── store/                 # Database integration & PostgreSQL RLS policies
│       └── schema.sql         # Supabase database schema definition
├── tests/                     # Automated test suite (235 passing pytest cases)
├── web/                       # Next.js 15 TypeScript Frontend Application
│   ├── app/                   # Next.js App Router (Landing, Dashboard, Gantt)
│   ├── components/            # Reusable UI components (Gantt, Matrix, Header)
│   └── public/                # Static assets (Indian Railways logo, icons)
├── ASSUMPTIONS.md             # Complete formal list of operational assumptions
├── PROJECT_BRIEF.md           # SIH26027 problem statement brief & specifications
├── Dockerfile                 # Unified multi-stage production container
├── render.yaml                # Render cloud deployment blueprint
├── requirements.txt           # Pinned Python dependencies
└── run.sh                     # One-command local development runner
```

---

## 🚀 Quick Start & Local Setup

### 1. System Prerequisites
* **Python**: `3.11` or `3.13` (recommended)
* **Node.js**: `20.x` or `22.x`
* **Package Managers**: `pip` and `npm`

### 2. Clone and Setup Environment
```bash
# Clone the repository
git clone https://github.com/hemampandey/RailVia.git
cd RailVia

# Create and activate Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Install Frontend dependencies
cd web && npm install && cd ..
```

### 3. Run the Full Application
Start both the FastAPI backend and the Next.js frontend with a single command:
```bash
./run.sh
```
* **FastAPI Backend**: `http://localhost:8077` (Interactive OpenAPI docs at `http://localhost:8077/docs`)
* **Next.js Web UI**: `http://localhost:3000`

### 4. Port Troubleshooting (Freeing Ports)
If port `8077` or `3000` is already in use by another service:
```bash
# Kill processes using backend (8077) and frontend (3000)
lsof -ti :8077 -ti :3000 | xargs kill -9

# Clean Next.js build cache and restart
./run.sh --clean
```

---

## 🧪 CLI & Development Commands

### Run the Baseline Comparison (Headline Metric)
Compares the uncoordinated legacy approach against RailVia's CP-SAT solver across 300 tasks:
```bash
.venv/bin/python scripts/compare.py --grounded --tasks 300 --days 30
```

### Run the Standalone CP-SAT Optimizer
Solves the schedule directly in the terminal and outputs block co-location statistics:
```bash
.venv/bin/python scripts/optimise.py --grounded --percentile 25
```

### Run the Disruption Re-planning Demo
Simulates a track machine breakdown on Day 3 and prints the re-planned recovery delta:
```bash
.venv/bin/python scripts/demo.py --out demo_run.txt
```

### Run the Full Automated Test Suite
Runs all **235 unit, integration, and regression tests**:
```bash
.venv/bin/pytest
```

---

## 🚢 Deployment (Docker & Render Cloud)

RailVia packages both the Next.js UI and the Python backend into a **single unified, lightweight container**:

1. **Stage 1 (Node 22)**: Builds the Next.js frontend into static production HTML/JS assets (`STATIC_EXPORT=1`).
2. **Stage 2 (Python 3.13 + OpenMP)**: Installs Google OR-Tools and LightGBM, mounts static frontend assets, and runs FastAPI via Uvicorn on port `7860`.

```bash
# Build Docker image locally
docker build -t railvia:latest .

# Run container
docker run -p 7860:7860 railvia:latest
```

### Deploy to Render Cloud
1. Push repository to GitHub.
2. In the Render Dashboard, select **New** → **Blueprint**.
3. Point to this repository; Render will configure the web service using [`render.yaml`](render.yaml) automatically.

---

## 📜 Data Provenance & IRPWM Grounding

RailVia adheres strictly to operational integrity and transparent data provenance:
* **Train Timetables (100% Real)**: Derived directly from Indian Railways published timetable data across 39 real sections on the Northern Railway network via the RailRadar API (`data/cache/railradar/`).
* **Maintenance Grounding**: Task durations, gang sizes, and periodicity strictly obey the **Indian Railways Permanent Way Manual (IRPWM)**.
* **Transparency**: Every planning instance logs the data provenance of its components via `SourceKind` (`GROUNDED` vs `SYNTHETIC`). If any component is generated, `is_synthetic=True` is explicitly flagged.

For full mathematical definitions, constraint proofs, and assumptions, refer to [ASSUMPTIONS.md](ASSUMPTIONS.md).

---

<div align="center">
  <sub>Developed for Smart India Hackathon (SIH26027) · Dedicated to the Modernization and Operational Safety of Indian Railways.</sub>
</div>
