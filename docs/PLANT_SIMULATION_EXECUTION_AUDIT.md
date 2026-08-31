# Plant Simulation execution audit — is the generated `.spp` runnable?

> **Historical record — read this first.**
>
> This audit was written on 2026-08-23, and it is the reason the next step
> happened. It found that the generated model was structurally correct but
> would not run: no horizon, no release rate, no release quantity. All three
> were then added to the adapter, and the model was executed in Plant
> Simulation — see
> [the cross-simulator validation report](CROSS_SIMULATOR_VALIDATION_REPORT.md) §3.
>
> The product was called FactoryMind when this was written. That name was
> replaced with *Fabrivium* in this file; nothing else was changed.

**Date:** 2026-08-23
**Baseline:** commit `5a9fe53`, tag `competition-strong-finalist-v1`
**Installation:** Siemens Tecnomatix Plant Simulation 2404, German locale,
`Tecnomatix.PlantSimulation.RemoteControl` (COM/ActiveX, pywin32), late-bound
`win32com.client.Dispatch`.

This document answers one question, with evidence read out of the file rather
than out of the code that wrote it:

> **Is the Fabrivium `.spp` currently an executable production model, or only
> a structurally valid engineering handoff?**

---

## Verdict

### STRUCTURALLY VALID HANDOFF — NOT EXECUTABLE AS-IS

The file contains a complete, correct, connected material-flow topology with
correct deterministic process times. It contains **no execution control**: the
simulation horizon is zero and the source has no generation policy. Loading it
and pressing start produces **zero units**, not a wrong number — the run
terminates before any event.

Three execution elements are missing. All three are *configuration of objects
that already exist*, not new modelling features.

---

## Evidence

Generated from the live CEC-120 concept with the **unmodified** adapter, saved,
closed, reopened, and read back out of the reloaded file
(`scratchpad/spp_audit.py`).

Build result — structure is genuinely complete:

```
stations_transferred          6/6
cycle_times_verified          6/6
flow_connections_verified     7/7
saved_model_verified          true
saved_model_stations_verified 6/6
saved_model_connections_verified 7/7
model_bytes                   3,751,936
errors                        []
```

Execution control, read out of the reopened file:

```
EventController.End       0.0000      <-- run would stop immediately
EventController.SimTime   0.0000
Source.Interval           0.0000      <-- no generation rate
Source.Number             -1          <-- unbounded, no demand cap
Source.StatNumOut         0
Drain.StatNumIn           0
```

Process semantics, read out of the reopened file — all correct:

```
PCB_placement        ProcTime=35.0000  Capacity=1  Setup=0.0000  Avail=100
Cable_connection_2   ProcTime=35.0000  Capacity=1  Setup=0.0000  Avail=100
Screw_fastening_6    ProcTime=52.0000  Capacity=1  Setup=0.0000  Avail=100
Enclosure_closure    ProcTime=35.0000  Capacity=1  Setup=0.0000  Avail=100
Visual_inspection    ProcTime=30.0000  Capacity=1  Setup=0.0000  Avail=100
Packaging            ProcTime=25.0000  Capacity=1  Setup=0.0000  Avail=100
```

Objects absent from the file:

```
Puffer (buffers)        no
Werker (workers)        no
Werkerpool              no
Broker                  no
Arbeitsplatz            no
```

---

## Component classification

| Component | Status | Evidence / note |
|---|---|---|
| Model root / frame | **PRESENT** | `.Modelle.Modell`, German locale detected at run time |
| Source object | **PRESENT** | created, named `Source`, connected |
| Stations | **PRESENT** | 6/6, correct SimTalk-legal names, read back from file |
| Drain object | **PRESENT** | created, named `Drain`, connected |
| Flow connections | **PRESENT** | 7/7 verified via `.succ.Name` out of the reopened file |
| Station `ProcTime` | **PRESENT** | 6/6 exact to 1e-6 |
| Station `Capacity` | **PRESENT** | all 1, matching Fabrivium |
| Layout coordinates | **PRESENT** | transferred; affects nothing in either simulator |
| `EventController` object | **PRESENT** | exists in the file and resolves |
| **Simulation horizon (`End`)** | **MISSING** | stored as `0.0000`; a run ends instantly |
| **Source generation policy (`Interval`)** | **MISSING** | stored as `0.0000` |
| **Production quantity / demand cap (`Number`)** | **MISSING** | stored as `-1` (unbounded) |
| Reset / initialisation | **PRESENT** | `ResetSimulation` verified working on the control model |
| Statistics objects | **PRESENT** | `Drain.StatNumIn`, `StatNumOut`, `Proc.StatWorkingPortion`, `StatBlockingPortion`, `StatWaitingPortion` all readable |
| Termination condition | **MISSING** | follows from `End = 0` |
| Setup / recovery time | **NOT_REQUIRED** | 0 in the file; Fabrivium models neither |
| Failures / availability | **NOT_REQUIRED** | `Availability = 100`, `Failures = 0`; Fabrivium models no breakdowns |
| **Buffers** | **MISSING** | 5 wired 50-capacity buffers exist in the exchange package and reach no Plant Simulation object |
| **Operator / workforce constraint** | **MISSING** | Fabrivium's shared pool of 8 is not represented in any form |
| Shift semantics | **PARTIAL** | shift *count* reaches the horizon length only; no shift calendar, no breaks — matching Fabrivium, which models neither |
| Scrap / changeover / transport | **NOT_REQUIRED** | modelled by neither simulator |

---

## What must be added to execute — and nothing more

Three assignments on objects that already exist:

1. `EventController.End := <horizon> + 1e-6`
2. `Source.Interval := <release interval>`
3. `Source.Number := <units to release>`

The `+ 1e-6` is not a tuning parameter. It is the **same epsilon Fabrivium
already applies** in `simulation.py` (`env.run(until=horizon_seconds + 1e-6)`,
a line that predates this phase), and it exists to give both simulators the
same *inclusive* horizon. See `CROSS_SIMULATOR_SEMANTICS.md` for the measured
boundary behaviour that makes it necessary.

Deliberately **not** added: buffers, workers, brokers, workplaces, shift
calendars, failures, scrap, changeovers, transport times. Buffers and workers
are genuine Fabrivium semantics that do not transfer — that gap is reported
as a limitation, not papered over. The rest Fabrivium does not model at all,
and adding them to one simulator only would manufacture a difference.

---

## Secondary finding — `product_version` reports UNKNOWN under late binding

`_product_version()` reads the COM **type library's** description, which only
exists when pywin32 has generated a makepy wrapper. Under a plain late-bound
`Dispatch` — which is what the adapter gets on this machine — `type(app)` is
`win32com.client.CDispatch` and the version is reported as `null`.

This is the documented, intended behaviour ("None means UNKNOWN and must be
shown as UNKNOWN"), and it is honest. It is recorded here because the earlier
`SIEMENS_HANDOFF_VERIFICATION.md` shows `product_version = Plant Simulation
2404`, which came from a session where the makepy wrapper was present. Both
observations are real; the value depends on the binding, not on the product.
**No claim in this phase depends on it.**
