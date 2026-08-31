# Simulation scope and limitations

**Date:** 2026-08-22
**Engine:** SimPy, discrete-event, fully deterministic.
**Purpose of this document:** so that nobody has to guess, and so that no
claim about the simulation outruns what it models.

---

## Why deterministic

FactoryMind compares alternatives. A deterministic engine makes that
comparison clean: two plans that differ by one machine differ in the result by
exactly the effect of that machine, with no sampling noise to argue about, and
repeated runs are bit-identical.

That is a genuine engineering trade, not a shortcut. Deterministic
line-balancing answers "does this configuration reach the target, and which
stage stops it?" — the question the concept stage asks. It does not answer
"what is the 95th-percentile daily output?", and FactoryMind does not claim it
does.

---

## Classification

| Phenomenon | Status | Evidence |
|---|---|---|
| Deterministic cycle times | **IMPLEMENTED** | every duration fixed; runs are bit-identical |
| Route / process steps | **IMPLEMENTED** | `ProcessStep.cycle_time` is what the engine reads |
| Parallel resources | **IMPLEMENTED** | Phase 2B pool dispatcher, deterministic tie-break by machine id |
| Buffers | **IMPLEMENTED** | `simpy.Container` per wired buffer |
| Blocking | **IMPLEMENTED** | `BufferKPI.upstream_blocked_seconds`, `blocking_observed` |
| Starvation | **IMPLEMENTED** | a stage waits when its upstream buffer is empty |
| Workforce / operator constraints | **IMPLEMENTED** | shared pool from `Factory.operators_available`; a station seizes `operators_required` while running |
| Shifts and hours | **IMPLEMENTED** | horizon = `shifts_per_day × hours_per_shift` |
| Machine capacity (units in process) | **IMPLEMENTED** | `simpy.Resource` capacity |
| Operator breaks | **NOT IMPLEMENTED** | the horizon is continuous production time |
| Equipment availability / MTBF | **NOT IMPLEMENTED** | no failure model exists |
| Failures and repair | **NOT IMPLEMENTED** | — |
| Changeovers / setup time | **NOT IMPLEMENTED** | one product per run, so no changeover arises |
| Scrap | **NOT IMPLEMENTED** | every started unit completes |
| Rework | **NOT IMPLEMENTED** | — |
| Stochastic cycle-time variation | **NOT IMPLEMENTED** | deliberate; see above |
| Transport / conveyor delay | **NOT IMPLEMENTED** | handover is instantaneous |
| Multiple product types per run | **NOT IMPLEMENTED** | one product per run |
| Shared non-operator resources (tools, fixtures) | **NOT IMPLEMENTED** | — |

---

## What this means for the numbers

**Throughput is an upper bound under the stated assumptions.** A real line
with the same cycle times will produce less, because breaks, failures and
variation all subtract. FactoryMind's figure is "what this configuration
achieves if nothing goes wrong", and every comparison between plans is made
under identical assumptions, which is what makes the comparison meaningful
even though the absolute number is optimistic.

The honest one-line statement, and the one the UI should make:

> Throughput under the stated model assumptions — deterministic cycle times,
> no downtime, no scrap.

---

## A correction made while writing this

The simulator's own module docstring listed *"No operator resource
constraints"* among its assumptions. That stopped being true when Phase 8A
added the shared operator pool: `run_simulation` now seizes operators per
station and refuses a configuration whose station demands more than the pool
can ever supply.

A stale assumption list is worse than no list — a reader who checks one entry,
finds it wrong, and stops checking has been misled by accuracy elsewhere. The
docstring is corrected and now also states what the engine *does* model.

---

## What would be worth adding, in order

Judged by credibility gained per unit of risk to the verified core:

1. **Availability / MTBF** — the single largest gap between this and a
   production estimate, and expressible as a per-machine uptime fraction
   without touching the event loop's structure.
2. **Operator breaks** — a shift-calendar effect; mostly a horizon change.
3. **Scrap / yield** — meaningful for the inspection stage in particular,
   since a reject that is not reworked changes what reaches packaging.
4. **Stochastic cycle times** — deliberately last. It would make single
   results noisier and comparisons harder, and would require replications to
   say anything the deterministic run does not already say. It should be
   added as an *option* alongside the deterministic mode, never as a
   replacement for it.
