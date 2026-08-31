# Cross-simulator validation plan — PREREGISTRATION

> **Historical record — read this first.**
>
> This is the preregistration for the cross-simulator comparison: the
> scenarios, the predictions and the pass/fail tolerance, all fixed **before**
> any Fabrivium model was executed in Plant Simulation. It is published so the
> [results](CROSS_SIMULATOR_VALIDATION_REPORT.md) can be checked against what
> was promised, rather than against a bar set afterwards.
>
> It was written on 2026-08-23, when the product was called FactoryMind and
> the CEC-120 case ran from a 1,058 units/day baseline. The name was replaced
> with *Fabrivium* in this file; nothing else was changed. For today's case
> configuration, see [CEC-120 case provenance](FABRIVIUM_CEC_CASE_PROVENANCE.md).


**Date:** 2026-08-23
**Baseline:** commit `5a9fe53`, tag `competition-strong-finalist-v1`

> ## STATUS AT TIME OF WRITING
>
> **No CEC-120 model has been executed in Plant Simulation.** The only Plant
> Simulation runs performed so far are the independent minimal control model
> (`Source → SingleProc → Drain`) and the horizon-boundary probes, neither of
> which contains any Fabrivium station, cycle time or result.
>
> Every scenario, metric, prediction and tolerance below is fixed **now**, in
> advance of observing any Plant Simulation output for CEC-120.

---

## 1. What is being tested

Whether Siemens Plant Simulation 2404, executing a model **that Fabrivium
generated**, computes the same production output as Fabrivium's own SimPy
engine under matched assumptions.

This is a test of Fabrivium's engineering core against an independent
industrial simulator. It is **not** a claim about a physical factory.

---

## 2. Primary metric

**Finished units over the same production horizon.**

* Fabrivium: `completed_units` from `run_simulation`
* Plant Simulation: `Drain.StatNumIn` after the run terminates

Horizon: 57,600 s (2 shifts × 8 h) for every scenario except where a plan
changes the shift pattern, in which case Fabrivium's own
`production_seconds_per_day` is used for both engines.

## 3. Secondary metrics (reported, not gated)

* limiting / bottleneck station — Fabrivium `system.bottleneck_machine_id`
  vs the Plant Simulation station with the highest `StatWorkingPortion`
* per-station utilisation (`StatWorkingPortion`)
* blocking and waiting portions (`StatBlockingPortion`, `StatWaitingPortion`)
* units admitted (`Source.StatNumOut`) vs units finished

These are reported for insight. They are **not** part of the pass/fail
condition, because Fabrivium and Plant Simulation define utilisation over
different denominators and a mismatch there would not by itself invalidate the
throughput comparison.

---

## 4. Scenarios

### S1 — workforce-neutral parity case (**PRIMARY, gated**)

The CEC-120 concept, identical in every respect except `operators_available`
raised to **12**, where Fabrivium itself reports
`operations_delayed_by_operators = 0` and `operator_constrained = false`.

This is the scenario in which the two engines model **identical physics**:
6 deterministic stations, capacity 1, serial flow, no failures, no setup, and —
as measured in `CROSS_SIMULATOR_SEMANTICS.md` §4 — a completed count that is
provably independent of buffering.

It is chosen because it is the case where the comparison is *semantically
valid*, and this is stated openly as a scope limitation rather than presented
as the competition baseline. It is **not** chosen for producing a nicer number:
the workforce-constrained baseline is also run and reported, in S2.

* Release: `Source.Interval := 30.220116`, `Source.Number := 1900`
* Horizon: `EventController.End := 57600 + 1e-6`
* **Fabrivium reference (already measured): 1104 units**
* **PREDICTION: Plant Simulation returns 1104.**

### S1b — source-representation robustness (reported)

S1 repeated with a saturating source (`Interval := 1`, `Number := -1`).
Because the line is bottleneck-limited and Fabrivium's release rate
(1/30.22 s) already exceeds the bottleneck rate (1/52 s), this must not change
the answer.

* **PREDICTION: Plant Simulation returns 1104, identical to S1.**

If S1 and S1b disagree, the source representation matters and the S1 result
must be re-examined before any claim is made.

### S2 — the actual competition baseline (**REPORTED AS A PREDICTED MISMATCH**)

The CEC-120 baseline exactly as it stands: `operators_available = 8`, 5 wired
buffers of capacity 50.

* **Fabrivium reference (already measured): 1058 units**
* The `.spp` contains neither operators nor buffers.
* **PREDICTION: Plant Simulation returns 1104 — i.e. the operator-free,
  buffer-free result — differing from Fabrivium by +46 units (+4.3%).**

This is registered as an **expected mismatch with a stated cause and a stated
magnitude**. Observing ≈1104 here *confirms* the semantic diagnosis in
`CROSS_SIMULATOR_SEMANTICS.md` §4–§5. It must never be reported as parity.

### S3 — selected plan, delivered output (conditional on S1 passing)

The currently selected CEC-120 plan (delivers 1,900/day). Run in **both**
engines under the plan's own shift pattern and operator count, with the release
mirroring Fabrivium's paced feeder.

Reported only if the plan's own Fabrivium run shows
`operations_delayed_by_operators = 0`. If the plan is workforce-constrained,
S3 is reported as a predicted mismatch in the same manner as S2, with the
magnitude derived from a Fabrivium operator-sensitivity run **before** the
Plant Simulation execution.

### S4 — selected plan, modeled capacity (conditional on S1 passing)

Fabrivium's capacity figure (≈2,033/day) comes from a **saturated** run at
`SATURATION_DEMAND_PER_DAY = 100,000/day` (`capacity.py`). Its Plant Simulation
mirror is a saturated source.

**A demand-capped Plant Simulation result will never be compared against
Fabrivium's capacity figure.** S3 (delivered, capped) and S4 (capacity,
saturated) are separate rows and are never mixed.

### S5 — generalisation, non-CEC line (**gated, same tolerance**)

A minimal line with independently chosen parameters, not derived from CEC-120
(different station count, different cycle times, different horizon), pushed
through the identical harness. Purpose: prove the harness is not fitted to
CEC-120.

---

## 5. Tolerance — fixed in advance

Under S1 both engines are **fully deterministic**, model identical physics, and
— after the `+1e-6` horizon alignment — use identical boundary semantics.
Theory therefore predicts **exact equality**, and the tolerance is set
accordingly rather than generously.

> ### PASS condition (S1, S1b, S5)
>
> ```
> absolute difference  |X − Y|  ≤  1 unit
>          AND
> relative difference  |X − Y| / X  ≤  0.1%
> ```

The ±1 unit allowance is justified by exactly one measured mechanism: an event
landing on the horizon boundary (`CROSS_SIMULATOR_SEMANTICS.md` §1). No other
source of discrepancy is anticipated, and none is granted room.

**Any difference greater than 1 unit is a FAIL** and must be explained
semantically. It will **not** be accommodated by widening this tolerance after
the fact.

### Explicitly excluded remedies

If a mismatch appears, the following are forbidden as responses:

* changing Fabrivium cycle times, capacities, operators, buffers or demand
* changing Plant Simulation `ProcTime`, `Capacity`, `Interval` or `Number`
  away from the values Fabrivium states
* changing the horizon on one side only
* widening this tolerance
* selecting a different scenario until one agrees

The permitted response is: form a hypothesis about the semantic cause, test it
with a controlled experiment, and report the result — matched or not.

---

## 6. Preregistered predictions, in one table

| Scenario | Fabrivium (known) | Plant Simulation (predicted) | Gated? | If confirmed, what it shows |
|---|---:|---:|---|---|
| S1 workforce-neutral | 1104 | **1104** | **yes, ±1** | the engineering core agrees with Siemens |
| S1b saturating source | 1104 | **1104** | reported | result independent of source representation |
| S2 competition baseline | 1058 | **1104** (+46, +4.3%) | no — predicted mismatch | the operator/buffer gap is understood and quantified |
| S3 plan, delivered | TBD from Fabrivium | mirror of Fabrivium's paced run | conditional | plan-level agreement |
| S4 plan, capacity | ≈2033 | saturated-source mirror | conditional | capacity-level agreement |
| S5 non-CEC line | computed fresh | equal within ±1 | **yes, ±1** | harness is not fitted to CEC-120 |

---

## 7. Execution protocol (fixed)

For every gated scenario:

1. regenerate the `.spp` from the current Fabrivium state
2. assert the file exists and exceeds the plausible-size floor
3. `CloseModel`, then `LoadModel` the saved file — **the file is what runs**
4. re-verify stations, cycle times and connections out of the reloaded file
5. apply the three execution settings (`End`, `Interval`, `Number`)
6. `ResetSimulation`
7. `StartSimulation(controller, True)`
8. poll `IsSimulationRunning` to genuine completion; assert `SimTime` reached
   the horizon; assert `HasSimulationError` is false
9. read `Drain.StatNumIn` and the station statistics
10. persist the raw evidence to disk before any comparison is computed

A run that times out, errors, or ends short of the horizon is a **failed run**
and is reported as such — never as a result.

---

## 8. Verdict vocabulary — fixed in advance

Exactly one of:

* **CROSS-SIMULATOR VALIDATION READY**
* **CROSS-SIMULATOR VALIDATION PARTIAL — `<exact limitation>`**
* **CROSS-SIMULATOR VALIDATION FAILED — `<exact blocker>`**

Given the workforce gap is already known and documented, the best outcome
reachable by this phase is **PARTIAL**, with the limitation being that the
comparison holds for the material-flow core and not for workforce-constrained
scenarios. That ceiling is set here, before the results are seen.
