# Siemens Plant Simulation handoff — what is actually verified

**Date:** 2026-08-21 (geometry, route and traversal verification added 2026-08-24)
**Installation:** Siemens Tecnomatix Plant Simulation 2404, German locale,
`Tecnomatix.PlantSimulation.RemoteControl` (COM/ActiveX, pywin32).

This document exists because the question "does a real, usable `.spp` actually
come out of this?" deserves an answer backed by evidence rather than by a
green panel in the UI. **The UI success state was not trusted.** Every claim
below was checked against the filesystem or against Plant Simulation itself.

---

## Verdict

### REAL AND VERIFIED

A genuine Plant Simulation model file is produced, written to a persistent
project directory, and independently confirmed to contain the correct
topology and cycle times when reopened by Plant Simulation.

---

## Evidence

### 1. The file exists and is a real Plant Simulation model

```
path   : C:\...\factorymind\exports\siemens\electronics_assembly_line.spp
exists : True   size: 3,747,840 bytes
header : b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'   (D0CF11E0 = OLE compound file)
```

`D0CF11E0` is the OLE compound-file magic number. `.spp` is an OLE compound
file; a stub, a JSON dump, or an empty file would not carry it.

### 2. Plant Simulation reopens it and the contents match

Read back by a script that **imports no FactoryMind code**, so the endpoint
cannot attest to its own success:

```
Plant Simulation 2404 opened the file.

CYCLE TIMES READ OUT OF THE FILE
   Assembly_Station           35.00 s   expected   35.00   OK
   Screwdriving_Station       52.00 s   expected   52.00   OK
   Inspection_Station         30.00 s   expected   30.00   OK
   Packaging_Station          25.00 s   expected   25.00   OK

MATERIAL FLOW WALKED FROM THE SOURCE
   Source                   -> Assembly_Station
   Assembly_Station         -> Screwdriving_Station
   Screwdriving_Station     -> Inspection_Station
   Inspection_Station       -> Packaging_Station
   Packaging_Station        -> Drain

stations matched : 4/4
links walked     : 5
```

A six-stage concept was exported separately and produced 6 stations and 7
connections, with all six cycle times confirmed by the same independent
read-back. The counts follow the concept.

### 3. The counts in the UI are read-back counts

`_verify` does not count successful writes. It issues
`GetValue("<path>.Name")`, `GetValue("<path>.ProcTime")` and
`ExecuteSimTalk("-> string; return <path>.succ.Name")` — i.e. it asks Plant
Simulation what the model contains. A write that silently did nothing cannot
inflate the number.

---

## What was wrong, and what changed

Two genuine gaps were found. Both allowed a green success state that the
evidence did not support.

### Gap 1 — "saved" was inferred from a COM call not raising

`SaveModel(path)` was called; if it did not throw, `model_path` was set and
the handoff reported COMPLETE. Nothing ever looked at the filesystem. A save
that returned while writing nothing — or writing a truncated file — reported
success with a path pointing at nothing.

**Now:** after `SaveModel`, the adapter checks the file exists and is at least
`_MIN_PLAUSIBLE_MODEL_BYTES` (100 KB; real models are ~3.7 MB). Failing either
check appends an error and leaves `model_path` unset, so the handoff cannot
report COMPLETE.

### Gap 2 — verification ran against the session, not the file

`_verify` ran *before* `SaveModel`, so it described the live Plant Simulation
session. The artefact the engineer receives is the file, and nothing had ever
read the file.

**Now:** after a verified save, the adapter calls `CloseModel()` (Plant
Simulation refuses `LoadModel` over an open model — "Model already loaded"),
reloads the saved file, and re-reads every station and connection **out of the
reloaded file**. `saved_model_verified` is:

* `True` — every station and link found again in the file;
* `False` — the file could not be reopened, or its contents disagreed;
* `None` — no file was written, so no round trip was possible. **`None` is not
  a pass**, and the UI does not render it as one.

`fully_verified` now requires the round trip whenever a save was requested.

Live result after the fix:

```
status                       COMPLETE
model_path                   ...\exports\siemens\electronics_assembly_line.spp
model_bytes                  3747840
saved_model_verified         True
saved_stations_verified      4
saved_connections_verified   5
product_version              Plant Simulation 2404
errors                       []
```

### Gap 3 — the only usable artefact was written to Temp

Exports went to `tempfile.gettempdir()`. The operating system may delete
anything there without warning; a handoff artefact that disappears on reboot
is not a handoff.

**Now:** `exports/siemens/<factory>.spp` beside the project, overridable with
`FACTORYMIND_EXPORT_DIR` (which is how the test suite keeps its stub files out
of the directory that holds real deliverables).

### Gap 4 — the release that wrote the file was not recorded

An `.spp` is version-bound. RemoteControl exposes no version property and no
SimTalk equivalent — both were probed against the live installation and
neither exists. What Siemens *does* expose is the COM type library's own
description.

**Now:** `product_version` is read from the type library ("Plant Simulation
2404") and shown beside the file. When it cannot be determined it is `None`
and the UI says the compatible releases are unknown, rather than guessing.

---

## Gap 5 — the model was structurally right and geometrically unusable

> **Found 2026-08-24, by opening the generated `.spp` by hand in Plant
> Simulation 2404.** The panel reported 6/6 stations, 6/6 cycle times, 12/12
> flow connections and a verified round trip. The model opened as a heap:
> station representations stacked at nearly the same position, and MUs piling
> into a growing vertical tower instead of travelling a line. Every count was
> true. None of them was about geometry, so none of them could see it.

### Root cause, measured

FactoryMind's layout coordinates are **metres on a factory floor**. They were
passed straight into `createObject(frame, x, y)`, whose coordinates are
**frame units** — a different system, a different unit, a different origin,
and a Y axis that runs the other way. Measured against the live installation:

| Probe | Result |
|---|---|
| `obj.getIconSize(w, h)` on Source / SingleProc / ParallelProc / Buffer / Drain | **41 × 41** frame units, all five, and unchanged by `XDim := 6` |
| `createObject(frame, 4.25, 2.667)` then read `XPos`, `YPos` | **20, 20** |
| Same for x = 9.75, 15.25 | **20, 20** — identical |
| Same for x = 31.75 | 31, 20 |
| `XPos := 4.7` then read back | `4` — coordinates are truncated to integers |
| `createObject(frame, 32000, 100)` | refused: *"Das Objekt würde sich außerhalb des Netzwerks befinden."* (30 000 is accepted) |

So a frame unit is about 1/41 of an object, and **anything below 20 is
silently clamped to 20** — 20 being `floor(41 / 2)`, which also says the
anchor is the icon centre. `concept_builder` lays a six-stage line out on a
5.5 m pitch, so the whole line spanned **16 frame units inside a 41-unit
icon**, with four stations below the clamp boundary landing on one point.

Rebuilding the reported case exactly as the old exporter built it, and asking
the product where everything went:

```
  Source                 asked (1, 6)           -> got (20, 20)
  Part_presentation      asked (4.25, 2.667)    -> got (20, 20)
  Housing_loading        asked (9.75, 2.667)    -> got (20, 20)
  Screw_fastening        asked (15.25, 2.667)   -> got (20, 20)
  Torque_verification    asked (20.75, 2.667)   -> got (20, 20)
  Visual_inspection      asked (26.25, 2.667)   -> got (26, 20)
  Label_application      asked (31.75, 2.667)   -> got (31, 20)
  Drain                  asked (36, 6)          -> got (36, 20)
  Buf0..Buf2             asked (6, 12) (11, 12) (16, 12) -> got (20, 20) ×3

  distinct positions: 5 of 13
  8 objects share (20, 20)
  closest pair: Buf0 / Buf1 at 0 units (an icon is 41)
```

Two further contributors, both real:

* **Buffers were placed by a scheme of their own** (`6 + i × 5, 12`), unrelated
  to the stations they sit between, so they landed on the stations as well.
* **The connector chain and the layout were built separately**, so nothing
  forced the drawn route and the placement to agree.

### Second defect, found by the new verification run

Adding "prove a unit reaches the drain" to the verification immediately failed
on the fixed-geometry model. A capacity-N stage was built as a **ParallelProc
with `XDim := N`**, chosen originally on a *saturated* throughput measurement
where it matched N servers exactly. Re-measured at **low load** it is not N
servers at all — it is a batch of N that does not begin processing until all N
places are occupied:

| Construction | 3 MUs released into a 6-place stage | Saturated, 1 h (ideal 720) |
|---|---|---|
| `ParallelProc`, `XDim = 6` | **0 reach the drain** — the run stops with all three held inside | 714 |
| `Buffer`, `Capacity = 6`, `ProcTime = T` | **3 of 3**, at t = 30/35/40 | 714 |
| `SingleProc` (reference, capacity 1) | 3 of 3 | 119 (ideal 120) |

Saturation hid it because a saturated batch always refills. A multi-capacity
stage is now built as a Buffer with `Capacity = N` and `ProcTime` = the cycle
time: the same throughput where the old class was right, and correct where it
was not. The UI states the construction rather than leaving it implicit.

### The fix

`app/integrations/plant_simulation/layout.py` — a pure, tested transform from
conceptual coordinates to frame coordinates:

* Measured constants, not chosen ones: `ICON_UNITS = 41`, `MIN_ANCHOR = 20`,
  `MAX_COORDINATE = 30_000`.
* **Preferred path:** the conceptual arrangement is *normalised* — one uniform
  scale plus a Y flip, so relative positions survive — sized so the tightest
  conceptual pair opens to a 90-unit pitch, and accepted **only if a collision
  check passes**.
* **Fallback:** a generated engineering line down the route order, serpentine
  wrapping at 12 per row, collision-free by construction. Used when the concept
  cannot be normalised safely (coincident stations, missing coordinates, an
  extent that will not fit), and the reason is reported, never hidden.
* Source, Drain and buffers are placed from the route neighbours they sit
  between — the only honest place for them, since FactoryMind never places them.
* One chain drives both the placement and the connectors, so the two cannot
  disagree again.

### The verification that would have caught it

`fully_verified` now additionally requires all of:

| Check | What it asks the model |
|---|---|
| Position read-back | `XPos`/`YPos` of every object equals the position it was given — this is what catches a silent clamp |
| No overlap | every pair of icon centres at least `ICON_UNITS` apart (Chebyshev; the icons are axis-aligned squares) |
| Unique positions | no two objects on the same point |
| Complete route | the model is **walked** `Source.succ → … → Drain`, and the walk must equal the chain that was built |
| No disconnected objects | anything created but not on that walk is named and fails the handoff |
| Counts | stations, buffers and connections, as before |
| Cycle-time and capacity read-back | as before |
| Equipment metadata read-back | `FM_Manufacturer` / `FM_Model` on the station |
| **Traversal** | the model is RUN and `Drain.StatNumIn` must be ≥ 1 |

Geometry is re-checked in the **reopened file** as well, so a layout that only
holds in the live session is not a deliverable.

### Live result, same case

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
errors                             []

route walked: Source -> Part_presentation -> Buffer_0 -> Housing_loading ->
              Buffer_1 -> Screw_fastening -> Buffer_2 -> Torque_verification ->
              Buffer_3 -> Visual_inspection -> Buffer_4 -> Label_application -> Drain
```

Read independently out of the saved `.spp`: 13 of 13 distinct positions,
closest pair 90 units against a 41-unit icon, and a 20-unit release run
delivering **20 of 20 units to the drain** with every station showing equal
in/out.

### Equipment under consideration

The selected machine now reaches the model, as metadata and nothing else.
`FM_Manufacturer`, `FM_Model`, `FM_SourceURL` and `FM_ParameterSource` are
user-defined attributes on the station object (verified to survive a save and
reload), read back like every other transferred value. Read out of the file:

```
  FM_Manufacturer / FM_Model : WEBER Schraubautomaten GmbH / SER Series 30
  ProcTime / Capacity        : 30.0000 s, capacity 6     <- the VERIFIED concept values
  FM_ParameterSource         : FactoryMind verified concept — manufacturer
                               figures are NOT applied
```

No manufacturer figure is written into `ProcTime`, `Capacity` or any other
value the simulation reads. Adopting one remains a separate, explicit decision
made in the review panel.

---

## Failure modes covered by tests

All run without Siemens installed, against a fake that behaves like the real
product's German locale:

| Failure | Test | Asserted outcome |
|---|---|---|
| `SaveModel` raises | `fail_on="save"` | not complete, error reported |
| `SaveModel` returns, no file appears | `test_a_save_that_produces_no_file_is_not_complete` | not complete, `model_path is None` |
| File written but truncated | `test_a_truncated_save_is_not_complete` | not complete, "too small" |
| Save silently drops a station | `test_a_save_that_silently_loses_a_station_is_not_complete` | session verifies, **file does not**, not complete |
| File cannot be reopened | `test_a_file_that_cannot_be_reopened_is_not_complete` | not complete |
| Object creation fails | `fail_on="create"` | partial model reported as partial |
| Unknown localisation | locale probe | stops rather than guessing |
| Plant Simulation absent | dispatch raises | `UNAVAILABLE`, distinct from failure |
| A position is silently clamped | `fail_on="verify_position"` | not complete, "geometrically wrong" |
| Objects overlap | `collisions()` over the read-back positions | not complete, the pair named |
| The route does not reach the drain | `fail_on="connect"` | `route_complete` false, not complete |
| An object is created but off the route | route walk | named in `disconnected`, not complete |
| No unit traverses the route | `fail_on="drain_empty"` | `traversal_verified` false, not complete |
| Equipment metadata does not survive | `fail_on="verify_equipment"` | not complete |

None of these produce a green success state.

---

## What is still NOT verified

> **Superseded in part, 2026-08-23.** The model is now genuinely EXECUTED in
> Plant Simulation and its throughput compared against FactoryMind's. See
> `CROSS_SIMULATOR_VALIDATION_REPORT.md` for the results, the preregistered
> tolerance and the remaining limitations. Two defects described there —
> station capacity was written but never read back, and buffers did not
> transfer — were found and fixed after this document was written, so the
> "4/4 stations, 5 links" counts above belong to the pre-fix model. Buffers are
> now transferred and verified too.

* **Plant Simulation does not reproduce the competition baseline of 1,058
  units/day.** It returns 1,104, because FactoryMind's shared-workforce
  constraint does not transfer and is binding on that case. Where the
  workforce is not binding the two engines agree to within one unit per day.
* **Operator demand, shifts and provenance do not transfer.** Station names,
  positions, cycle times, capacities, wired buffers and the flow chain reach
  the model; the workforce does not. The UI lists both sets separately.
* **Only the German locale has been exercised live.** English identifiers are
  implemented and unit-tested; the live proof is German.
