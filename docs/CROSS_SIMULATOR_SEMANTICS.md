# Cross-simulator semantics — what "units/day" means in each engine

**Date:** 2026-08-23
**Baseline:** commit `5a9fe53`, tag `competition-strong-finalist-v1`
**Purpose:** establish, *before any CEC-120 throughput is compared*, whether the
two numbers measure the same thing.

Everything marked **measured** was established experimentally against the live
installation or the live FactoryMind engine, with the probe script named. No
value in this document was taken from memory or documentation.

---

## 1. The horizon boundary — why the control model returned 359, not 360

### The observation

Minimal control model, `Source → SingleProc → Drain`, `ProcTime = 10 s`,
saturating source, `EventController.End = 3600`:

```
Source.StatNumOut  360
Proc.StatNumIn     360
Proc.StatNumOut    359
Drain.StatNumIn    359      <-- ideal steady-state capacity is 360
Proc.StatWorkingPortion 1   (100% busy — nothing was lost to idling)
```

### Hypothesis

Completions land at `t = 10, 20, … , 3600`. The completion scheduled at
**exactly** `t = End` is not executed before the run terminates, so the Drain
counts completions **strictly before** the horizon.

### The test — `scratchpad/boundary_probe.py`, **measured**

`ProcTime = 10 s` throughout. `strict` = number of `k` with `k·10 < End`;
`inclusive` = number with `k·10 ≤ End`.

| `End` | `Drain.StatNumIn` | strict | inclusive | verdict |
|---:|---:|---:|---:|---|
| 100 | **9** | 9 | 10 | strict |
| 101 | 10 | 10 | 10 | (both agree) |
| 105 | 10 | 10 | 10 | (both agree) |
| 110 | **10** | 10 | 11 | strict |
| 3600 | **359** | 359 | 360 | strict |
| 3600.001 | 360 | 360 | 360 | (both agree) |
| 3601 | 360 | 360 | 360 | (both agree) |
| 57600 | **5759** | 5759 | 5760 | strict |

### Conclusion — CONFIRMED, 8/8 cases

**Plant Simulation counts completions strictly before `EventController.End`.**
A completion scheduled at exactly `t = End` is not counted. This is
deterministic, fully explained, and is *not* a defect in either simulator.

### FactoryMind does the opposite — and always has

`backend/app/services/simulation.py`, a line that **predates this phase**:

```python
# Run until just past the nominal horizon by a tiny epsilon so that events
# scheduled at exactly t == horizon_seconds ... are processed before the
# simulation stops.
env.run(until=horizon_seconds + 1e-6)
```

FactoryMind's horizon is therefore **inclusive**. The two engines differ by
exactly one boundary event.

### Resolution — and why it is not tuning

`scratchpad/epsilon_probe.py`, **measured**: Plant Simulation stores `End` at
far higher precision than its 4-decimal display. Every epsilon from `1e-9`
upward flips the count from 359 to 360.

| epsilon added to 3600 | `End` displayed | `Drain.StatNumIn` |
|---|---|---|
| 0 | `1:00:00.0000` | 359 |
| **1e-6** | `1:00:00.0000` | **360** |
| 1e-4 | `1:00:00.0001` | 360 |
| 0.01 | `1:00:00.0100` | 360 |

So setting `EventController.End := horizon + 1e-6` gives Plant Simulation the
**identical inclusive horizon FactoryMind already uses**, with the *same
numeric epsilon*, copied from the existing FactoryMind line rather than chosen.
There is no free parameter here: the value is fixed by FactoryMind, not fitted
to a Plant Simulation result.

> **Note for the CEC-120 case specifically:** completions land at
> `212 + 52k` seconds, and `(57600 − 212)/52 = 1103.6…` is not an integer, so
> **no completion falls exactly on the horizon** and the strict/inclusive
> distinction changes nothing for this case. The alignment is applied for
> semantic correctness, not because it moves the number.

---

## 2. Side-by-side semantic mapping

| Aspect | FactoryMind (SimPy) | Plant Simulation 2404 | Match? |
|---|---|---|---|
| Production horizon | `shifts × hours × 3600` = **57,600 s** | `EventController.End` | **matched** by assignment |
| Horizon boundary | **inclusive** (`until = h + 1e-6`) | **strictly before** `End` — *measured* | **matched** by setting `End = h + 1e-6` |
| Finished unit | completed final route step within horizon → `completed_units` | `Drain.StatNumIn` | **matched** |
| Unfinished WIP at horizon | counted as `work_in_progress`, **excluded** from `completed_units` | remains in the line, never reaches Drain | **matched** |
| Initial state | empty line, WIP = 0, `t = 0` | empty after `ResetSimulation` | **matched** |
| Statistics start / warm-up | none — measured from `t = 0` | none — measured from `t = 0` | **matched** |
| Cycle time | deterministic `ProcessStep.cycle_time` | deterministic `ProcTime` | **matched** |
| Station capacity | SimPy `Resource(capacity = machine.capacity)` | `Capacity` | **matched** (all 1 here) |
| Setup / recovery | not modelled | `SetupTime = 0`, `RecoveryTime = 0` | **matched** |
| Failures / availability | not modelled (`failure_rate` sits unread) | `Availability = 100`, `Failures = 0` | **matched** |
| Scrap, changeover, transport | not modelled | not added | **matched** |
| Determinism | fixed times, no random variables | fixed times, no random variables | **matched** |
| Release / source policy | paced feeder, see §3 | `Source.Interval` + `Source.Number` | **matched** by assignment |
| Demand cap | `target_units = ceil(demand_per_day)` units released, then stops | `Source.Number` | **matched** by assignment |
| Queue before first station | **unbounded** | Source **blocks** when line is full | **differs** — see §4 |
| Intermediate buffers | 5 wired, capacity 50 | **none in the model** | **differs** — see §4 |
| Blocking | outbound-buffer-full blocks the machine that is still held | inherent in a zero-buffer serial line | differs in mechanism, see §4 |
| Starvation | modelled | modelled | matched |
| **Shared operators** | **shared pool of 8, seized per operation** | **not represented** | **DIFFERS — material, see §5** |
| Shift calendar / breaks | not modelled (shifts only set horizon length) | not modelled | **matched** |

---

## 3. FactoryMind's release schedule — paced, not saturated

This is the single most important thing to get right, and it is easy to get
wrong. FactoryMind's baseline run is **not** a saturated-source capacity run.

From `simulation.py`:

```
target_units        = ceil(demand_per_day)                      = 1900
nominal_route_time  = Σ cycle_time = 35+35+52+35+30+25          = 212 s
latest_release_time = horizon − nominal_route_time              = 57388 s
release_interval    = latest_release_time / (target_units − 1)  = 30.220116 s
```

Unit 0 is released at `t = 0`; unit *k* at `t = k × 30.220116`. Release is
**not throttled by capacity** — when arrivals outrun the bottleneck, queues and
WIP grow and are measured.

Confirmed in the live reference run: `release_interval_seconds = 30.220116`.

The Plant Simulation mirror is therefore `Source.Interval := 30.220116` and
`Source.Number := 1900`, **not** a saturating source.

### Two distinct FactoryMind quantities, which must never be compared to each other

| Quantity | How FactoryMind produces it | Plant Simulation mirror |
|---|---|---|
| **Delivered output** | paced release of exactly `ceil(target)` units | `Interval = release_interval`, `Number = target_units` |
| **Modeled capacity** | one extra run at `SATURATION_DEMAND_PER_DAY = 100,000/day` (`capacity.py`) | saturating source, `Number` unbounded or 100,000 |

`capacity.py` exists precisely because these two disagree. A demand-capped
Plant Simulation result must never be compared against FactoryMind's capacity
figure, and vice versa.

---

## 4. Buffers and blocking — measured, and shown not to matter *where it counts*

The exchange package carries 5 wired buffers of capacity 50; the `.spp` carries
none. Rather than argue about whether that matters, it was measured with
FactoryMind's own engine, varying only the buffer-capacity **input**
(`scratchpad/diag_buffers.py`).

**With the workforce constraint relaxed (operators = 12), completed units are
completely insensitive to buffering:**

| buffer capacity | 1 | 2 | 5 | 10 | 50 | 200 | 1000 | **none** |
|---|---|---|---|---|---|---|---|---|
| completed units | 1104 | 1104 | 1104 | 1104 | 1104 | 1104 | 1104 | **1104** |

This is the expected result for a deterministic serial line: with no
variability there is no blocking loss, and the bottleneck sets the rate. It
means **the `.spp`'s omission of buffers is harmless in the workforce-neutral
case** — the comparison is valid despite the structural difference.

**With the workforce constraint active (operators = 8), buffering and
operators are coupled, and buffer size changes the answer a great deal:**

| buffer capacity | 1 | 2 | 5 | 10 | **50** | 200 | 1000 | none |
|---|---|---|---|---|---|---|---|---|
| completed units | 1083 | 1082 | 1081 | 1078 | **1058** | 984 | 817 | 982 |

Larger buffers let more units accumulate upstream, where they consume scarce
operators and starve the bottleneck. **1,058 is a joint consequence of the
operator pool *and* the 50-unit buffers.** Neither is in the `.spp`, so the
generated model cannot reproduce 1,058 by any configuration of the objects it
contains. This is stated in advance, not discovered after a mismatch.

The unbounded-queue-vs-blocking-source difference (§2) is subsumed by the same
argument: under a bottleneck-limited deterministic line both admit units at the
bottleneck rate, and the workforce-neutral row above shows the completed count
does not move.

---

## 5. The workforce constraint — the material semantic gap

### FactoryMind's model (`_OperatorPool`, `_run_step`)

* one shared pool of `operators_available` interchangeable operators
  (`simpy.Container`, because one operation consumes N at once)
* per operation: seize the **machine** first, then `operators_required`
  operators — all-or-nothing, blocking
* operators released the instant processing ends, before the unit moves on
* **zero travel time, no identity, no allocation preference**

### Is it binding on CEC-120? — measured, `scratchpad/diag_operators.py`

Reference run KPI:

```
operators_available              8
operators_required_peak          12
peak_operators_in_use            8
utilization                      0.9987
operations_delayed_by_operators  4712
operator_constrained             true
```

Sensitivity (only the `operators_available` input varied):

| operators | 8 | 9 | **10** | 11 | 12 | 16 | 24 | 48 |
|---|---|---|---|---|---|---|---|---|
| completed | 1058 | 1058 | **1104** | 1104 | 1104 | 1104 | 1104 | 1104 |
| `operator_constrained` | true | true | **false** | false | false | false | false | false |
| ops delayed | 4712 | 4712 | **0** | 0 | 0 | 0 | 0 | 0 |

**The workforce constraint is hard-binding at 99.87% utilisation and is worth
46 units/day (4.3%).** It becomes provably non-binding at ≥ 10 operators, where
FactoryMind itself reports `operations_delayed_by_operators = 0`.

### Can Plant Simulation represent it? — investigated, `scratchpad/worker_probe*.py`

The resource library exists: `.Ressourcen.Werker`, `.Ressourcen.Werkerpool`,
`.Ressourcen.Broker`, `.Ressourcen.Arbeitsplatz`, `.Ressourcen.Schichtkalender`.

But a `SingleProc` exposes **no** worker-requirement attribute — every candidate
(`Services`, `ProcService`, `NumberOperators`, `Importer`, `Broker`, …) returns
*Unbekannter Bezeichner*. Plant Simulation attaches workers through a
`Workplace` bound to the station, allocated by a `Broker`, with workers
**physically walking** along `FootPath`s from a `WorkerPool`.

That mechanism carries semantics FactoryMind does not have: travel time,
worker identity, and broker allocation priority. Implementing it would not
reproduce FactoryMind's anonymous zero-travel pool — it would **introduce a new
difference** while claiming to remove one, and it is explicitly ruled out by
this phase's own constraint ("do not add simulation features that FactoryMind
itself does not model… no transport delays").

### Decision — path B, with the limitation made load-bearing

Cross-simulator comparison is performed on a scenario where the workforce
constraint is **demonstrably non-binding** (FactoryMind reporting
`operations_delayed_by_operators = 0`), and the workforce-constrained baseline
is reported as a **predicted mismatch of known cause and pre-stated magnitude**
— not as parity, and not quietly omitted.

The prediction is registered in `CROSS_SIMULATOR_VALIDATION_PLAN.md` **before**
any CEC-120 model was executed in Plant Simulation.

---

## 6. Discovered execution API (exact, from the live type library)

`scratchpad/probe_com.py` enumerated the interface rather than assuming it:

```
LoadModel  LoadModelWithoutState  NewModel  CloseModel  SaveModel
ExecuteSimTalk  GetValue  SetValue  GetTableCell  SetTable
StartSimulation  StopSimulation  ResetSimulation  StepSimulation
IsSimulationRunning  HasSimulationError  SetStopSimulationOnError
Quit  QuitAfterTime  SetPathContext  SetTrustModels  SetNoMessageBox
SetVisible  SetLicenseType  SetSuppressOpenGL  SetSuppressStartOf3D
OpenConsoleLogFile  SetCrashStackFile  GetJTExport  TransferModel
GetCurrentProcessId
```

Used by the validation harness: `NewModel`, `LoadModel`, `CloseModel`,
`SaveModel`, `ExecuteSimTalk`, `GetValue`, `ResetSimulation`,
`StartSimulation(controller, True)`, `IsSimulationRunning`,
`HasSimulationError`, `SetStopSimulationOnError`, `Quit`.

Statistics confirmed readable: `Drain.StatNumIn`, `Drain.StatNumOut`,
`<station>.StatNumIn`, `.StatNumOut`, `.StatWorkingPortion`,
`.StatBlockingPortion`, `.StatWaitingPortion`, `Source.StatNumOut`,
`EventController.SimTime`.
