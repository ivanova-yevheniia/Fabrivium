# Siemens Plant Simulation handoff — verification report

**Product:** Siemens Tecnomatix Plant Simulation 2404
**Interface:** `Tecnomatix.PlantSimulation.RemoteControl` (COM/ActiveX, pywin32)
**Live proof locale:** German
**Scope of this document:** what the handoff transfers, how each claim is
verified, and what does not transfer.

Fabrivium's own success panel is not evidence. Every figure below was read back
**out of the saved `.spp` file** after it had been closed and reopened, by code
that asks Plant Simulation what the model contains rather than counting its own
writes.

---

## 1. Verdict

A genuine Plant Simulation model file is produced, written to a persistent
project directory, and independently confirmed — after a save/close/reopen round
trip — to contain the correct topology, geometry, cycle times and material flow,
and to pass units through the line.

| Verified by read-back from the reopened file | Result |
|---|---:|
| Stations transferred | **6/6** |
| Cycle times | **6/6** |
| Buffers | **5/5** |
| Layout positions | **13/13** |
| Flow connections | **12/12** |
| Equipment metadata | **1/1** |
| Route reaches the drain | **true** |
| Overlapping objects | **none** |
| Disconnected objects | **none** |
| Saved model reverified | **true** |

---

## 2. The artefact is a real Plant Simulation model

```
file   : exports/siemens/<factory>.spp
size   : 3,747,840 bytes
header : d0 cf 11 e0 a1 b1 1a e1      (OLE compound file)
```

`D0CF11E0` is the OLE compound-file magic number. `.spp` is an OLE compound
file; a stub, a JSON dump or an empty file would not carry it.

Exports are written to `exports/siemens/<factory>.spp` beside the project —
never to the system temp directory, which the operating system may clear without
warning. The destination is overridable through the `FACTORYMIND_EXPORT_DIR`
environment variable, which is how the test suite keeps stub files out of the
directory holding real deliverables.

The release that wrote the file is recorded. RemoteControl exposes no version
property and no SimTalk equivalent — both were probed against the live
installation and neither exists — so `product_version` is read from the COM type
library's own description (`Plant Simulation 2404`) and shown beside the file.
When it cannot be determined it is `None` and the interface says the compatible
releases are unknown rather than guessing.

---

## 3. What is verified, and what each check asks the model

`fully_verified` is granted only when **all** of the following hold, in the
reopened file:

| Check | What it asks Plant Simulation |
|---|---|
| File written | The path exists and is at least 100 KB (real models are ~3.7 MB) |
| Round trip | The file is closed, reloaded and re-read — the live session is not the deliverable |
| Station names | `GetValue("<path>.Name")` for every station |
| Cycle times | `GetValue("<path>.ProcTime")` equals the concept value |
| Capacity | `Capacity` equals the concept value |
| Buffers | Every wired buffer exists, with its capacity |
| Position read-back | `XPos`/`YPos` equal the coordinates given — this is what catches a silent clamp |
| No overlap | Every pair of icon centres at least 41 units apart (Chebyshev; icons are axis-aligned squares) |
| Unique positions | No two objects on the same point |
| Complete route | The model is **walked** `Source.succ → … → Drain`, and the walk must equal the chain that was built |
| No disconnected objects | Anything created but not on that walk is named, and fails the handoff |
| Equipment metadata | `FM_Manufacturer` / `FM_Model` survive save and reload |
| **Traversal** | The model is **run**, and `Drain.StatNumIn` must be ≥ 1 |

Counts are read-back counts, not write counts: `GetValue` and
`ExecuteSimTalk("-> string; return <path>.succ.Name")` ask the product what the
model contains, so a write that silently did nothing cannot inflate a number.

`saved_model_verified` has three states and only one of them is a pass:
`True` — every object found again in the file; `False` — the file could not be
reopened, or its contents disagreed; `None` — no file was written, so no round
trip was possible. **`None` is not a pass**, and the interface does not render it
as one.

---

## 4. Live result — the canonical case

```
layout mode: normalised-concept   min separation: 90
ok                                 True
stations_transferred               6/6
cycle_times_verified               6/6
buffers_verified                   5/5
flow_connections_verified          12/12
positions_verified                 13/13
overlaps                           []
route_complete                     True
disconnected                       []
traversal_units                    3
traversal_verified                 True
equipment_verified                 1/1
saved_model_verified               True
product_version                    Plant Simulation 2404
model_bytes                        3747840
errors                             []

route walked: Source -> Part_presentation -> Buffer_0 -> Housing_loading ->
              Buffer_1 -> Screw_fastening -> Buffer_2 -> Torque_verification ->
              Buffer_3 -> Visual_inspection -> Buffer_4 -> Label_application -> Drain
```

Read independently out of the saved `.spp`: 13 of 13 distinct positions, closest
pair 90 units against a 41-unit icon, and a 20-unit release run delivering
**20 of 20 units to the drain**, every station showing equal in and out.

---

## 5. Geometry — measured constants, not chosen ones

A model can be structurally correct and geometrically unusable, and counts
cannot see the difference. Fabrivium's layout coordinates are **metres on a
factory floor**; `createObject(frame, x, y)` takes **frame units** — a different
system, a different unit, a different origin and an inverted Y axis. Passing one
into the other stacks the line into a heap while every count still reports
success.

The transform in `app/integrations/plant_simulation/layout.py` is therefore
built on constants measured against the live installation, not assumed:

| Probe | Result |
|---|---|
| `getIconSize` on Source / SingleProc / ParallelProc / Buffer / Drain | **41 × 41** frame units, all five, unchanged by `XDim := 6` |
| `createObject` below x = 20 or y = 20, then read `XPos`/`YPos` | Silently **clamped to 20** — `floor(41 / 2)`, so the anchor is the icon centre |
| `XPos := 4.7`, read back | `4` — coordinates truncate to integers |
| `createObject(frame, 32000, 100)` | Refused; 30,000 is accepted |

So `ICON_UNITS = 41`, `MIN_ANCHOR = 20`, `MAX_COORDINATE = 30_000`.

**Preferred path.** The conceptual arrangement is *normalised* — one uniform
scale plus a Y flip, so relative positions survive — sized so the tightest
conceptual pair opens to a 90-unit pitch, and accepted **only if a collision
check passes**.

**Fallback.** A generated engineering line down the route order, serpentine
wrapping at 12 per row, collision-free by construction. Used when the concept
cannot be normalised safely — coincident stations, missing coordinates, an
extent that will not fit — and the reason is reported, never hidden.

Source, Drain and buffers are placed from the route neighbours they sit between,
since Fabrivium never places them itself. **One chain drives both the placement
and the connectors**, so the drawn route and the geometry cannot disagree.

Geometry is re-checked in the reopened file as well: a layout that only holds in
the live session is not a deliverable.

---

## 6. How a multi-capacity stage is built

A capacity-*N* stage is built as a **Buffer with `Capacity = N` and `ProcTime` =
the cycle time**, not as a `ParallelProc` with `XDim := N`.

The two agree under saturation and disagree at low load, which is the case that
matters for a deliverable model:

| Construction | 3 MUs released into a 6-place stage | Saturated, 1 h (ideal 720) |
|---|---|---|
| `ParallelProc`, `XDim = 6` | **0 reach the drain** — the run stops with all three held inside | 714 |
| `Buffer`, `Capacity = 6`, `ProcTime = T` | **3 of 3**, at t = 30/35/40 | 714 |
| `SingleProc` (reference, capacity 1) | 3 of 3 | 119 (ideal 120) |

`ParallelProc` with `XDim = N` is a **batch of N** that does not begin processing
until all N places are occupied — saturation hides this, because a saturated
batch always refills. The Buffer construction gives the same throughput where
the other class was right, and correct behaviour where it was not. The interface
states the construction rather than leaving it implicit.

---

## 7. Equipment under consideration

The selected machine reaches the model **as metadata and nothing else**.
`FM_Manufacturer`, `FM_Model`, `FM_SourceURL` and `FM_ParameterSource` are
user-defined attributes on the station object, verified to survive a save and
reload, and read back like every other transferred value:

```
FM_Manufacturer / FM_Model : WEBER Schraubautomaten GmbH / SER Series 30
ProcTime / Capacity        : 30.0000 s, capacity 6    <- the VERIFIED concept values
FM_ParameterSource         : Fabrivium verified concept — manufacturer
                             figures are NOT applied
```

No manufacturer figure is written into `ProcTime`, `Capacity` or any other value
the simulation reads. Adopting one remains a separate, explicit engineering
decision made in the review panel.

---

## 8. Failure modes covered by tests

All run **without Siemens installed**, against a fake that behaves like the real
product's German locale. None of them produces a green success state.

| Failure | Asserted outcome |
|---|---|
| `SaveModel` raises | Not complete, error reported |
| `SaveModel` returns but no file appears | Not complete, `model_path is None` |
| File written but truncated | Not complete, "too small" |
| Save silently drops a station | Session verifies, **the file does not** — not complete |
| File cannot be reopened | Not complete |
| Object creation fails | Partial model reported as partial |
| A position is silently clamped | Not complete, "geometrically wrong" |
| Objects overlap | Not complete, the offending pair named |
| The route does not reach the drain | `route_complete` false, not complete |
| An object is created but off the route | Named in `disconnected`, not complete |
| No unit traverses the route | `traversal_verified` false, not complete |
| Equipment metadata does not survive | Not complete |
| Unknown localisation | Stops rather than guessing |
| Plant Simulation absent | `UNAVAILABLE` — a distinct state from failure |

---

## 9. What does not transfer

The transferred model is the **baseline engineering concept**, and its scope is
bounded on purpose.

**Transfers:** station names, layout positions, cycle times, capacities, wired
buffers, the material-flow chain, and equipment metadata.

**Does not transfer:**

* **Operator demand and the shared-workforce constraint.** Plant Simulation
  attaches workers through a `Workplace` bound to the station, allocated by a
  `Broker`, with workers physically walking `FootPath`s from a `WorkerPool` —
  semantics carrying travel time, worker identity and allocation priority that
  Fabrivium's anonymous zero-travel pool does not have. Implementing it would
  introduce a new difference while claiming to remove one.
* **Shift pattern.** Shifts set the horizon length in Fabrivium; no shift
  calendar is written.
* **Provenance.** Whether a value was measured, estimated or set by an engineer
  is Fabrivium state, and has no representation in the model.

Consequence, stated in advance rather than discovered after a mismatch: where
the workforce constraint is not binding, the two engines agree to within one
unit per day; where it **is** binding they diverge, and the generated model
cannot reproduce the workforce-constrained figure by any configuration of the
objects it contains. See
[cross-simulator semantics](CROSS_SIMULATOR_SEMANTICS.md) for the measured
semantic mapping and executed comparison.

**Only the German locale has been exercised live.** English identifiers are
implemented and unit-tested; the live proof is German.
