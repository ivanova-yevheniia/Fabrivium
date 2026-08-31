# Cross-simulator semantics — what "units/day" means in each engine

**Engines:** Fabrivium's deterministic core (SimPy) and Siemens Tecnomatix
Plant Simulation 2404.
**Purpose:** establish, before any throughput is compared, whether the two
numbers measure the same thing.

Two simulators can disagree because one of them is wrong, or because they are
answering different questions. This document separates those. Everything marked
**measured** was established experimentally against the live installation or the
live Fabrivium engine; no value here was taken from memory or documentation.

**Fabrivium does not claim parity with Plant Simulation.** It claims a bounded,
documented correspondence, and names the boundary.

---

## 1. The horizon boundary — the two engines differ by one event

### Measured, Plant Simulation

A minimal control model — `Source → SingleProc → Drain`, `ProcTime = 10 s`,
saturating source — was run across eight horizons. `strict` counts completions
with `k·10 < End`; `inclusive` counts `k·10 ≤ End`.

| `End` | `Drain.StatNumIn` | strict | inclusive | verdict |
|---:|---:|---:|---:|---|
| 100 | **9** | 9 | 10 | strict |
| 101 | 10 | 10 | 10 | both agree |
| 105 | 10 | 10 | 10 | both agree |
| 110 | **10** | 10 | 11 | strict |
| 3600 | **359** | 359 | 360 | strict |
| 3600.001 | 360 | 360 | 360 | both agree |
| 3601 | 360 | 360 | 360 | both agree |
| 57600 | **5759** | 5759 | 5760 | strict |

**Conclusion — confirmed, 8/8 cases: Plant Simulation counts completions
strictly before `EventController.End`.** A completion scheduled at exactly
`t = End` is not executed before the run terminates. This is deterministic,
fully explained, and is not a defect in either simulator.

### Fabrivium is inclusive, and always has been

`backend/app/services/simulation.py`, on a line that predates this comparison:

```python
# Run until just past the nominal horizon by a tiny epsilon so that events
# scheduled at exactly t == horizon_seconds ... are processed before the
# simulation stops.
env.run(until=horizon_seconds + 1e-6)
```

### Resolution — alignment, not tuning

**Measured:** Plant Simulation stores `End` at far higher precision than its
four-decimal display, and every epsilon from `1e-9` upward flips the control
model from 359 to 360.

| epsilon added to 3600 | `End` displayed | `Drain.StatNumIn` |
|---|---|---|
| 0 | `1:00:00.0000` | 359 |
| **1e-6** | `1:00:00.0000` | **360** |
| 1e-4 | `1:00:00.0001` | 360 |
| 0.01 | `1:00:00.0100` | 360 |

Setting `EventController.End := horizon + 1e-6` gives Plant Simulation the
**identical inclusive horizon Fabrivium already uses, with the same numeric
epsilon** — copied from the existing Fabrivium line rather than chosen. There is
no free parameter here: the value is fixed by Fabrivium, not fitted to a Plant
Simulation result.

The alignment is applied for semantic correctness. On a case where no completion
lands exactly on the horizon, it changes nothing.

---

## 2. Semantic mapping

| Aspect | Fabrivium (SimPy) | Plant Simulation 2404 | Match? |
|---|---|---|---|
| Production horizon | `shifts × hours × 3600` | `EventController.End` | **matched** by assignment |
| Horizon boundary | inclusive (`until = h + 1e-6`) | strictly before `End` — *measured* | **matched** by setting `End = h + 1e-6` |
| Finished unit | completed final route step within horizon | `Drain.StatNumIn` | **matched** |
| Unfinished WIP at horizon | counted as `work_in_progress`, excluded from completions | remains in the line, never reaches the Drain | **matched** |
| Initial state | empty line, WIP = 0, `t = 0` | empty after `ResetSimulation` | **matched** |
| Warm-up | none — measured from `t = 0` | none — measured from `t = 0` | **matched** |
| Cycle time | deterministic `ProcessStep.cycle_time` | deterministic `ProcTime` | **matched** |
| Station capacity | SimPy `Resource(capacity = machine.capacity)` | `Capacity` | **matched** |
| Setup / recovery | not modelled | `SetupTime = 0`, `RecoveryTime = 0` | **matched** |
| Failures / availability | not modelled | `Availability = 100`, `Failures = 0` | **matched** |
| Scrap, changeover, transport | not modelled | not added | **matched** |
| Determinism | fixed times, no random variables | fixed times, no random variables | **matched** |
| Release policy | paced feeder, see §3 | `Source.Interval` + `Source.Number` | **matched** by assignment |
| Demand cap | `target_units` released, then release stops | `Source.Number` | **matched** by assignment |
| Queue before first station | unbounded | Source blocks when the line is full | **differs** — see §4 |
| Intermediate buffers | wired, with capacity | present in the model | **matched** |
| Blocking | outbound-buffer-full blocks the machine still holding the unit | inherent in a serial line | differs in mechanism, see §4 |
| Starvation | modelled | modelled | **matched** |
| **Shared operators** | **shared pool, seized per operation** | **not represented** | **DIFFERS — material, see §5** |
| Shift calendar / breaks | not modelled (shifts set horizon length only) | not modelled | **matched** |

---

## 3. Release is paced, not saturated

This is the single easiest thing to get wrong. Fabrivium's baseline run is
**not** a saturated-source capacity run.

```
target_units        = ceil(demand_per_day)
nominal_route_time  = Σ cycle_time over the route
latest_release_time = horizon − nominal_route_time
release_interval    = latest_release_time / (target_units − 1)
```

Unit 0 is released at `t = 0`, unit *k* at `t = k × release_interval`. Release is
**not throttled by capacity** — when arrivals outrun the bottleneck, queues and
WIP grow, and are measured. The Plant Simulation mirror is therefore
`Source.Interval := release_interval` and `Source.Number := target_units`, not a
saturating source.

### Two Fabrivium quantities that must never be compared to each other

| Quantity | How Fabrivium produces it | Plant Simulation mirror |
|---|---|---|
| **Delivered output** | paced release of exactly `ceil(target)` units | `Interval = release_interval`, `Number = target_units` |
| **Modeled capacity** | a separate run at `SATURATION_DEMAND_PER_DAY` (`capacity.py`) | saturating source, unbounded `Number` |

`capacity.py` exists precisely because these two disagree. A demand-capped Plant
Simulation result must never be compared against Fabrivium's capacity figure, or
the reverse.

---

## 4. Buffers and blocking

Buffers are transferred to the model with their capacities, so the structural
difference that once existed here is closed.

The remaining difference is the unbounded input queue versus a blocking source.
Under a bottleneck-limited deterministic line both admit units at the bottleneck
rate: with no variability there is no blocking loss, and the bottleneck sets the
rate. **Measured** by varying only the buffer-capacity input in Fabrivium's own
engine with the workforce constraint relaxed, completed units are completely
insensitive to buffering across capacities from 1 to 1,000 and with buffering
removed entirely.

That insensitivity holds **only while the workforce is not binding**. When it is,
buffering and operators are coupled — larger buffers let units accumulate
upstream, where they consume scarce operators and starve the bottleneck — and
buffer size changes the answer substantially. A workforce-constrained figure is
therefore a joint consequence of the operator pool *and* the buffer sizes, and
neither the pool nor that coupling exists in the `.spp`.

---

## 5. The workforce constraint — the material semantic gap

### Fabrivium's model

* one shared pool of interchangeable operators (`simpy.Container`, because one
  operation consumes N at once);
* per operation: seize the **machine** first, then the required operators —
  all-or-nothing, blocking;
* operators released the instant processing ends, before the unit moves on;
* **zero travel time, no worker identity, no allocation preference.**

Where the pool is binding, Fabrivium reports it explicitly:
`operator_constrained`, `peak_operators_in_use`, `operator utilisation` and
`operations_delayed_by_operators` are all KPI outputs. The constraint becomes
provably non-binding at the operator count where
`operations_delayed_by_operators` reaches 0 — which is measured per scenario, not
assumed.

### Can Plant Simulation represent it? — investigated

The resource library exists — `.Ressourcen.Werker`, `.Werkerpool`, `.Broker`,
`.Arbeitsplatz`, `.Schichtkalender` — but a `SingleProc` exposes **no**
worker-requirement attribute: every candidate (`Services`, `ProcService`,
`NumberOperators`, `Importer`, `Broker`, …) returns *Unbekannter Bezeichner*.

Plant Simulation attaches workers through a `Workplace` bound to the station,
allocated by a `Broker`, with workers **physically walking** `FootPath`s from a
`WorkerPool`. That mechanism carries semantics Fabrivium does not have: travel
time, worker identity and broker allocation priority. Implementing it would not
reproduce Fabrivium's anonymous zero-travel pool — it would **introduce a new
difference while claiming to remove one**, and it would add simulation features
Fabrivium itself does not model.

### Decision — bound the claim rather than fake the parity

Cross-simulator comparison is performed on scenarios where the workforce
constraint is **demonstrably non-binding**, with Fabrivium itself reporting
`operations_delayed_by_operators = 0`. Workforce-constrained scenarios are
reported as a **predicted mismatch of known cause and pre-stated magnitude** —
not as parity, and not quietly omitted. The comparison rule and tolerance were
fixed before any model was executed in Plant Simulation.

---

## 6. What this supports, and what it does not

**Supported:**

* The two engines model the same material-flow physics, with the differences
  above enumerated rather than assumed.
* Where the workforce constraint is not binding, they agree on line capacity to
  within one unit per day.
* The horizon convention is aligned by a value copied from Fabrivium, not fitted
  to a Plant Simulation result.

**Not supported:**

* **No full-parity claim.** Workforce-constrained scenarios diverge by
  construction, and demand-paced *delivered* runs carry a systematic start-up
  offset. Both are documented rather than tuned away.
* **The semantics are bounded to what both engines model.** Failures,
  availability, scrap, changeover, transport, shift calendars and breaks are
  modelled by neither, so agreement between them says nothing about a line where
  those matter.
* **The live proof is the German locale, on Plant Simulation 2404.**

Executed results and their bounded interpretation are recorded in this document.
What reaches the model at all:
[Siemens handoff verification](SIEMENS_HANDOFF_VERIFICATION.md).

---

## Appendix — the execution API, from the live type library

Enumerated from the interface rather than assumed:

```
LoadModel  LoadModelWithoutState  NewModel  CloseModel  SaveModel
ExecuteSimTalk  GetValue  GetTableCell  SetValue  SetTable
StartSimulation  StopSimulation  ResetSimulation  StepSimulation
IsSimulationRunning  HasSimulationError  SetStopSimulationOnError
Quit  QuitAfterTime  SetPathContext  SetTrustModels  SetNoMessageBox
SetVisible  SetLicenseType  SetSuppressOpenGL  SetSuppressStartOf3D
OpenConsoleLogFile  SetCrashStackFile  GetJTExport  TransferModel
GetCurrentProcessId
```

Statistics confirmed readable: `Drain.StatNumIn`, `Drain.StatNumOut`,
`<station>.StatNumIn`, `.StatNumOut`, `.StatWorkingPortion`,
`.StatBlockingPortion`, `.StatWaitingPortion`, `Source.StatNumOut`,
`EventController.SimTime`.
