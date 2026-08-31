# Cross-simulator validation report — Fabrivium vs Siemens Plant Simulation 2404

> **Historical record — read this first.**
>
> This report was written on 2026-08-23. Two things have changed since then.
>
> 1. **The product was called FactoryMind.** That name was replaced with
>    *Fabrivium* throughout this file. Nothing else in the text was changed.
> 2. **The CEC-120 case was configured differently.** This report works from a
>    1,058 units/day baseline. The published case study starts at 1,435
>    units/day, because an engineer makes two decisions that this run did not
>    make. Both figures come from the same product and the same code — see
>    [CEC-120 case provenance](FABRIVIUM_CEC_CASE_PROVENANCE.md).
>
> The finding of this report is that two simulation engines agree with each
> other. That finding does not depend on which CEC-120 configuration was used.
>
> One section of the internal version discussed the project's competition
> standing rather than its engineering. It is omitted here. No engineering
> result, failure or limitation was removed.


**Date:** 2026-08-23
**Baseline:** commit `5a9fe53`, tag `competition-strong-finalist-v1`
**Installation:** Siemens Tecnomatix Plant Simulation 2404, German locale,
`Tecnomatix.PlantSimulation.RemoteControl` (COM/ActiveX, pywin32, late-bound).

Preregistration: `CROSS_SIMULATOR_VALIDATION_PLAN.md`, written and committed to
disk **before any CEC-120 model was executed in Plant Simulation**.
Semantics: `CROSS_SIMULATOR_SEMANTICS.md`. Model audit:
`PLANT_SIMULATION_EXECUTION_AUDIT.md`.

---

# FINAL VERDICT

> ## CROSS-SIMULATOR VALIDATION PARTIAL
>
> **— the two engines agree on line capacity and material-flow physics to
> within 1 unit/day; they do NOT agree on workforce-constrained scenarios,
> because the workforce does not transfer, and demand-paced *delivered* runs
> carry a systematic start-up offset that exceeded the preregistered tolerance
> on one of two gated cases.**

Plant Simulation now genuinely **executes** a Fabrivium-generated model and
returns throughput. That is new, and it is real. What it does **not** yet do is
reproduce Fabrivium's workforce constraint, which is load-bearing in the
competition baseline.

---

## 1. Results table

| # | Scenario | Fabrivium | Plant Simulation | Δ | Δ% | Gated | Verdict |
|---|---|---:|---:|---:|---:|---|---|
| S1 | CEC-120, workforce-neutral (12 operators) | **1104** | **1104** | **0** | **0.000%** | yes | **PASS** |
| S1b | S1 with a saturating source | 1104 | 1104 | 0 | 0.000% | no | consistent |
| S2 | CEC-120 competition baseline (8 operators) | 1058 | 1104 | +46 | +4.348% | no | **predicted mismatch** |
| S3 | Selected plan, delivered (demand-capped) | 1900 | 1899 | −1 | −0.053% | yes | **PASS** |
| S4a | Selected plan, capacity, as planned (10 operators) | 2033 | 2462 | +429 | +21.1% | no | **predicted mismatch** |
| S4b | Selected plan, capacity, workforce-neutral (14 operators) | **2463** | **2462** | **−1** | **−0.041%** | yes | **PASS** |
| S5 | Non-CEC line, delivered (generalisation) | 700 | 698 | −2 | −0.286% | yes | **FAIL** |

**Gated: 4 · passing: 3 · failing: 1.**

Preregistered tolerance, unchanged since before the first run:
`|X−Y| ≤ 1 unit` **and** `|X−Y|/X ≤ 0.1%`. It was **not** widened to
accommodate S5.

Every Plant Simulation figure came from a run that started, reached its
horizon, reported no error, and was read back from `Drain.StatNumIn` out of a
model that had been **saved, closed, reopened and re-verified** first. Raw
evidence: `exports/cross_simulator/cross_simulator_evidence.json`.

---

## 2. Was execution actually achieved? Yes — proved independently first

Before any Fabrivium model was run, a minimal control model
(`Source → SingleProc → Drain`, ProcTime 10 s, horizon 3600 s) was built and
executed through the same COM interface, importing no Fabrivium code:

```
Source.StatNumOut      360
Proc.StatNumIn         360
Proc.StatNumOut        359
Drain.StatNumIn        359
Proc.StatWorkingPortion  1     (100% busy)
SimTime            1:00:00     (advanced from 0)
IsSimulationRunning  False
HasSimulationError   False
```

This separated *"COM execution works"* from *"the Fabrivium model is
executable"* — and it immediately produced the first finding.

### Finding 1 — Plant Simulation's horizon is exclusive; Fabrivium's is inclusive

359, not 360. Tested over eight horizons (`CROSS_SIMULATOR_SEMANTICS.md` §1):
**Plant Simulation counts completions strictly before `EventController.End`,
in 8/8 cases.** Fabrivium already ran `env.run(until=horizon + 1e-6)` — a
line predating this phase — making its horizon inclusive.

Resolution: set `End := horizon + 1e-6`, **the same epsilon, copied from
Fabrivium's own source**, not fitted to any result. Plant Simulation stores
`End` far more precisely than its 4-decimal display, so 1e-6 is represented
faithfully (measured: every epsilon from 1e-9 up flips 359→360).

For CEC-120 specifically this changes nothing — completions land at `212 + 52k`
and none falls exactly on the horizon — but the semantics are now identical
rather than coincidentally compatible.

---

## 3. Was the `.spp` executable? No — it was a structurally valid handoff

Audited by generating a CEC-120 model with the **unmodified** adapter, then
closing, reopening and reading the file (`PLANT_SIMULATION_EXECUTION_AUDIT.md`):

```
stations 6/6   cycle times 6/6   connections 7/7   round trip verified
EventController.End   0.0000   <- a run would end instantly
Source.Interval       0.0000   <- no generation rate
Source.Number            -1    <- no demand cap
buffers / workers / brokers / workplaces:  none
```

**Answer: structurally valid engineering handoff, not an executable production
model.** Three settings were missing, all configuration of objects that already
existed: horizon, release interval, release quantity. Those three — and nothing
else — are what `PlantSimulationAdapter.execute()` now applies.

---

## 4. The workforce gap — measured, not assumed

Fabrivium models a shared pool of interchangeable operators seized per
operation (machine first, then N operators, released the instant processing
ends, zero travel).

On the CEC-120 baseline it is **hard-binding**:

```
operators_available               8
operators_required_peak          12
utilization                  0.9987
operations_delayed_by_operators 4712
operator_constrained           true
```

Sensitivity (only the input varied): 8 → 1058, 9 → 1058, **10 → 1104**, and
1104 thereafter, with `operations_delayed_by_operators = 0` from 10 upward.
**The workforce is worth 46 units/day (4.3%).**

### Can Plant Simulation represent it? Investigated, and deliberately declined

`.Ressourcen.Werker`, `.Werkerpool`, `.Broker`, `.Arbeitsplatz` all exist. But a
`SingleProc` exposes **no** worker-requirement attribute — every candidate
(`Services`, `ProcService`, `NumberOperators`, `Importer`, …) returns
*Unbekannter Bezeichner*. Plant Simulation attaches workers via a `Workplace`
bound to the station, allocated by a `Broker`, with workers **physically
walking** along `FootPath`s.

That carries travel time, worker identity and allocation priority — none of
which Fabrivium models. Implementing it would **introduce** a difference
while claiming to remove one, and this phase's own rules forbid adding
transport delays that Fabrivium does not model.

**Decision: path B.** Comparison is gated only on scenarios where Fabrivium
itself reports `operations_delayed_by_operators = 0`, and the
workforce-constrained cases (S2, S4a) are reported as predicted mismatches with
their magnitude stated in advance. The workforce gap is **not** silently
omitted — it is the headline limitation.

**S2 confirmed the diagnosis exactly.** Preregistered prediction: *"Plant
Simulation returns 1104, differing from Fabrivium by +46 units (+4.3%)."*
Observed: **1104, +46, +4.348%.**

---

## 5. Two defects this phase found in the frozen baseline

### Defect A — station capacity was written but never read back

`_verify()` read `Name`, `ProcTime` and `succ` — **never `Capacity`**. A stage
whose capacity did not survive transfer still reported as verified. This
contradicted the adapter's own governing rule ("nothing is reported as
transferred because a COM call returned without raising").

It surfaced because the selected plan sets screwdriving to capacity 2, and the
live product answered:

```
Could not create station 'Screw fastening ×6': Die Kapazität kann nicht geändert werden.
```

A `SingleProc` **refuses** `Capacity := N`. Measured across the class library:
`Einzelstation` refuses, `Parallelstation` refuses `Capacity` directly but
accepts `XDim`/`YDim`, from which `Capacity` is derived. Verified behaviourally
— `XDim = 1, 2, 3` produced 1107, 2214, 3321 units against an ideal of
1107/2215/3323.

**Fixed:** a stage with capacity 1 is still an `Einzelstation`, built by
exactly the SimTalk it always was; a stage with capacity > 1 is now a
`Parallelstation` with `XDim = capacity`. `Capacity` is now read back, and a
mismatch fails the handoff.

### Defect B — omitting buffers did not omit buffering; it added blocking

The `.spp` carried no buffers. Fabrivium's stations sit behind **unbounded**
input queues, so a Plant Simulation model without buffers is a zero-buffer
**blocking** line — a materially different system.

This was invisible on the baseline and severe on the plan:

| line | no buffers | any buffer ≥ 1 | slowest stage implies |
|---|---:|---:|---|
| CEC-120 baseline (screwdriving cap 1) | 1658 | 1658 | 1662 |
| Selected plan (screwdriving cap 2) | **1413** | **2462** | 2469 |

The baseline is immune because one stage dominates at 52 s and stays saturated
(`StatWorkingPortion = 0.9988`). The plan doubles that stage, no single stage
dominates, and the blocking loss becomes **43%**.

The buffer hypothesis was tested against Fabrivium first and **refuted** as
an explanation of Fabrivium's numbers — Fabrivium delivers 1900 with
buffers removed entirely — which is precisely what identified the asymmetry:
buffers are non-binding in Fabrivium and decisive in Plant Simulation.

**Fixed:** the wired buffers Fabrivium already declares are now transferred
(`Puffer`, declared capacity, `ProcTime = 0`) and woven into the material flow
between the stations they connect, with capacity read back.

Both defects existed in the frozen baseline and would have shipped a model that
verified green while simulating something else.

---

## 6. The one gated failure — S5, and why it was not tolerated away

S5 is an independently specified line (4 stations, cycle times 18/41/23/12.5 s,
a capacity-3 stage, one 7.5 h shift, target 700) chosen to prove the harness is
not fitted to CEC-120.

**Fabrivium 700, Plant Simulation 698. Δ = −2, −0.286%. FAIL.**

It is a real, systematic effect, not noise:

* Both engines report **zero blocking** and admit all 700 units.
* Utilisation is far below 1 (limiting stage 0.595) — neither line is
  capacity-limited.
* The shortfall is entirely at the horizon edge.

**Mechanism.** Fabrivium's paced feeder is built so the final unit finishes
*exactly* at the horizon (`latest_release = horizon − nominal_route_time`),
assuming zero waiting. Plant Simulation's blocking Source introduces a start-up
offset: on the selected plan the last unit is delivered at **86,435 s** against
Fabrivium's 86,400 s — measured by bisecting the horizon — and the first unit
arrives about one release interval late. The cost is
`⌈offset / release_interval⌉` units: **1** on the CEC plan (interval 45.39 s),
**2** on the non-CEC line (interval 38.49 s). The offset is bounded by
measurement to roughly 38–45 s in both cases.

This affects **only demand-paced delivered runs**. Saturated capacity runs are
unaffected (S1, S1b exact; S4b −1), because there is no schedule to fall off
the end of.

The tolerance was **not** widened. S5 stands as a FAIL, and it is the reason
the verdict is PARTIAL rather than READY.

### A harness bug found on the way, and fixed

`SimulationResult.release_interval_seconds` is `round(interval, 6)`. Driving
Plant Simulation with the rounded value adds 3.7e-7 s per release, which over
1,899 releases pushes the final unit past the horizon and costs a whole unit:
**1898 with the rounded interval, 1899 with the exact one.** The harness now
recomputes the interval at full precision. This was a defect in the comparison,
not in either simulator.

---

## 7. Limiting-stage agreement — independent and exact

| | Fabrivium | Plant Simulation | agree |
|---|---|---|---|
| CEC-120 baseline | `m-screwdriving` | `Screw fastening ×6` (0.9988 working, 0 blocking) | **yes** |
| Selected plan | `m-assembly` | `PCB placement` (highest working portion) | **yes** |
| Non-CEC line | `gx-weld` | `Robot weld` (0.5954) | **yes** |

Plant Simulation's own statistics identify the same limiting stage in all three
cases, via explicit station mapping (`simtalk_identifier`). The baseline
signature is textbook: bottleneck saturated, upstream blocked (0.326),
downstream starved (0.328 / 0.424 / 0.521).

---

## 8. Delivered output is never compared against capacity

`capacity.py` measures capacity with a **saturated** run at 100,000/day;
`completed_units` answers a different question. They are kept apart:

* **S3** — delivered, demand-capped in both engines (`Interval = release
  interval`, `Number = target`).
* **S4a / S4b** — capacity, saturated in both engines.

S4a is reported and **not gated**: Fabrivium's 2,033/day capacity figure is
itself workforce-constrained (`operator_constrained = true` at 10 operators),
so comparing it with a workforce-free model is meaningless. Raising the
workforce until Fabrivium reports it non-binding gives **2463 vs 2462** —
agreement to one unit. The competition figure of 2,033/day is therefore
**correct as Fabrivium defines it** and is *not* the number Plant Simulation
produces, for a reason that is now measured rather than guessed.

---

## 9. Fabrivium's reference outputs were not changed

The CEC-120 reference reproduces from the real pipeline, unchanged:

```
stations 6   operators 8   2 x 8 h
target 1900   completed 1058   gap 842   bottleneck m-screwdriving
arena: 57 simulations, 6 strategies, 1 reaching target
selected: Plan F — delivers 1900/day, capacity 2033/day, headroom +7.0%
```

`app/services/simulation.py` was **not modified** in this phase — not one
executable line, and not its docstring. No golden value moved. Every
Fabrivium number in this report came from running the existing engine with a
different *input* (operator count, buffer capacity, demand), which is
measurement, not tuning.

---

## 9b. Known inconsistency left in place, deliberately

`PlantSimulationAdapter.run()` — the older method the
`/handoff/plant-simulation` endpoint calls when `run_simulation=true` — still
sets `Source.Interval := 1` (a **saturating** source) and
`EventController.End := horizon` **without** the epsilon. By this phase's own
findings that combination measures *capacity*, not delivered output, and drops
any completion landing exactly on the horizon.

It was **not** changed here. Doing so would alter what an existing endpoint
field (`simulated_units`) means — a product decision, not a validation one, and
outside this phase's scope. It is recorded rather than quietly left:

* the validated path is `execute()`, which takes the release policy explicitly;
* `run()`'s number is not used in any claim in this report;
* the endpoint's existing documentation already states that its figure is not
  claimed to match Fabrivium's.

Recommended follow-up: route the endpoint through `execute()` and decide
explicitly whether it should report delivered output or capacity.

---

## 10. Files changed

| File | Change |
|---|---|
| `backend/app/integrations/plant_simulation/adapter.py` | `HORIZON_EPSILON`; `ExecutionResult`; `execute()` + `_read_execution_statistics()`; `Capacity` read-back on `StationCheck`; `ParallelProc` for capacity > 1; `BufferCheck` + buffer transfer and verification; `_product_version` no longer raises |
| `backend/app/integrations/plant_simulation/localization.py` | `parallel_station` identifier (`Parallelstation` / `ParallelProc`) |
| `backend/scripts/cross_simulator_validation.py` | **new** — the live harness implementing the preregistered protocol |
| `backend/tests/test_cross_simulator_validation.py` | **new** — 33 tests, no Siemens required |
| `backend/tests/test_plant_simulation_adapter.py` | fake made class-aware (refuses `Capacity != 1` on a SingleProc, derives it from `XDim`); buffer/link counts updated |
| `docs/PLANT_SIMULATION_EXECUTION_AUDIT.md` | **new** |
| `docs/CROSS_SIMULATOR_SEMANTICS.md` | **new** |
| `docs/CROSS_SIMULATOR_VALIDATION_PLAN.md` | **new** (preregistration) |
| `docs/CROSS_SIMULATOR_VALIDATION_REPORT.md` | **new** (this file) |

Nothing was committed.

---

## 11. Tests

`backend/tests/test_cross_simulator_validation.py` — **33 tests, all passing,
none requiring Plant Simulation.** Coverage: execution-result schema and JSON
persistence; timeout; simulation error; horizon not reached; unreadable drain;
unconnected adapter; the epsilon actually written into the model; demand-capped
vs capacity distinguishable; the preregistered tolerance at its boundary
(1904/1899 passes, 700/698 fails, 500/499 fails on the relative bound, 1058/1104
nowhere near); station capacity read-back; ParallelProc selection for
multi-unit stages; buffer transfer, chain placement and capacity verification;
limiting-station derivation.

Separation is explicit: **unit/contract tests** run anywhere; the **live
validation** is a script, not a pytest module.

---

## 11b. Regression

Run after every change in this phase.

| Suite | Result |
|---|---|
| **Backend** | **2,170 passed · 0 failed · 0 errors · 37 skipped**, all 58 test modules |
| **Frontend** | **693 passed / 61 files** |
| `tsc --noEmit` | clean |
| `vite build` | OK (28.55 s) |

All 37 skips are the live IBM modules, unchanged and confirmed module by
module: `test_phase7b_watsonx_live` (13), `test_phase7c_conversation_live`
(11), `test_phase8a_live_granite` (5), `test_phase8b_live_granite` (8).
**No IBM quota was consumed.**

The backend suite was run in segments rather than as one invocation — two
attempts at a single full run were killed externally at ~70 minutes, and the
suite takes roughly two hours in total (`test_phase7c_conversation.py` alone
takes 41 minutes). The segments partition the 58 modules exactly: each file was
run once, none twice, none omitted.

**Targeted suites, re-run after each adapter change:** `test_plant_simulation_adapter.py`
(34), `test_handoff_api.py` (22), `test_cross_simulator_validation.py` (33).

**Fabrivium reference outputs were not changed to match Plant Simulation.**
`app/services/simulation.py` was not modified. The CEC-120 journey still
produces 1,058 units/day baseline, bottleneck `m-screwdriving`, 57 simulations
/ 6 strategies, Plan F delivering 1,900/day at 2,033/day capacity.

---

## 12. The safe claim

> Fabrivium generates a Siemens Plant Simulation 2404 model through the
> product's own automation interface, saves it, reopens it, verifies its
> stations, cycle times, capacities, buffers and topology out of the reopened
> file, **executes it**, and compares its production output against
> Fabrivium's own simulation under matched assumptions.
>
> On the tested CEC-120 cases the two engines agreed **exactly** on line
> capacity where Fabrivium's workforce constraint is not binding
> (1104 vs 1104; 2463 vs 2462), and identified the **same limiting station** in
> every case.
>
> The comparison covers material flow — cycle times, station capacity,
> buffering, routing, blocking and the production horizon. It does **not**
> cover the shared workforce, which Fabrivium models and the generated model
> does not carry; in workforce-constrained scenarios the two engines differ by
> a known, measured amount.

Not claimed, and not true: that Siemens proves Fabrivium correct; that
Fabrivium is validated for all factories; that this says anything about a
physical factory. This is one simulator agreeing with another on a shared
subset of physics.

---

