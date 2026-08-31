# Generalization validation — pre-registration

Written **before** any of the three cases was run through FactoryMind.
Nothing in this file was edited after the first run; every deviation between
what is predicted here and what actually happened is reported as a finding in
`docs/GENERALIZATION_VALIDATION_REPORT.md` rather than corrected here.

Baseline: commit `5a9fe53` / tag `competition-strong-finalist-v1`, plus the
uncommitted estimate-contract work already present in the tree at the start of
this phase (see the report's *Baseline* section).

Language model: **off**. Every case runs the deterministic path, the same one
the competition demo runs on, because the account's watsonx quota is exhausted
(`ibm-granite-quota`). No case result depends on a model being reachable.

---

## Case A — different product, different process

**Product document:** `case_a_lt8_gearbox_housing.txt`
LT-8 gearbox housing sub-assembly. Chosen to differ from CEC-120 on every axis
the pipeline could plausibly have learned:

| | CEC-120 | Case A |
|---|---|---|
| Material | Moulded ABS | Cast aluminium + steel |
| Fastener | 6 screws | 12 bolts at 24 Nm |
| Electrical content | PCB + 2 cables | none |
| Distinctive operation | screwdriving | bearing press-fit, wash/degrease |
| Inspection | visual | pressure/leak test + rotation check |
| Packaging | bag + carton + leaflet | oiled paper + returnable steel crate |

**Requirements brief (exact text sent to the pipeline):**

> We build the LT-8 for a conveyor manufacturer. We need 900 units per day
> from a single cell. We run two 8-hour shifts and have six operators
> available for this cell. The available floor area is 22 by 14 meters. A
> budget for one additional station has been approved if it is needed.

**Predicted behaviour (pre-registered):**

1. Facts extracted: bolt count 12, cover/lid present, enclosure present,
   dimensions, inspection required, packaging required.
2. Material is stated twice with different values (aluminium, steel) — the
   extractor has one `material.enclosure` slot, so a CONFLICT is expected, and
   the correct behaviour is to keep both readings rather than pick one.
3. Sections 4 (wash/degrease) and 5 (bearing press-fit) name real
   manufacturing work that no extraction rule covers. **Prediction: they are
   dropped silently** — no fact, no operation, no gap. If so, that is a
   generic defect, not a Case-A defect.
4. Cycle times must come back UNKNOWN from the concept builder and be
   resolvable only through the Phase 18B estimator or an engineer's typed
   value. No CEC-120 number (52 s, 35 s, 30 s, 25 s, 1,900/day, €1,058, 2,033)
   may appear anywhere in the Case A output.
5. Takt at 900/day over two 8-hour shifts = 57,600 s ÷ 900 = **64.0 s**. A
   four-station line whose stations estimate in the 30–90 s band is expected to
   be *nearly* feasible — the interesting question is whether FactoryMind finds
   the right bottleneck and a lever for it, not whether it is green.

## Case B — incomplete engineering information

**Product document:** `case_b_ft9_filter_head.txt`
FT-9 in-line filter head, issued at concept stage with quantities deliberately
open:

* no overall dimensions ("envelope study is still open")
* no material ("two candidates are being evaluated")
* screws stated, **count not stated** (on an unreleased drawing)
* cables stated, **count not stated** (depends on sensor variant)
* leak test stated, **acceptance limit not agreed**

**Requirements brief (exact text sent to the pipeline):**

> We plan to make the FT-9 on a new manual cell. The customer forecast is 600
> units per day. The shift pattern and the staffing for this cell have not
> been agreed yet, and the cell footprint has not been allocated.

**Predicted behaviour (pre-registered):**

1. Every missing quantity stays UNKNOWN. Nothing is substituted with 0, with a
   catalogue default, or with a CEC-120 value.
2. Missing dimensions and missing material must appear as declared
   information gaps.
3. **Open question, deliberately not predicted:** a stated fastening operation
   whose count is absent. Either FactoryMind records the operation with an
   unknown repeat count (correct), or it drops the operation entirely
   (a defect). Which one happens is the point of this case.
4. Shifts, hours, operators and floor come back UNKNOWN from the brief, so the
   concept must be reported as NOT simulation-ready until an engineer resolves
   them. A default shift pattern appearing here would be a favourable
   substitution and a failure of this case.

## Case C — intentionally infeasible constraint set

**Product document:** `case_c_gr7_guard_assembly.txt`
GR-7 bench grinder guard. Ordinary four-station line: clip, fasten, inspect,
pack.

**Constraint set, fixed before the run:**

| Constraint | Value |
|---|---|
| Production target | 6,000 units/day |
| Shift pattern | one 8-hour shift, no second shift available |
| Workforce | four operators, no additional hiring |
| Equipment | no new machines |
| Capital | no capital spend this year |
| Floor | 24 by 12 metres |

**Requirements brief (exact text sent to the pipeline):**

> We need 6,000 units per day of the GR-7 from one cell. We run one 8-hour
> shift and have four operators. Do not buy any new machines and do not add
> any new machines. There is no capital budget this year. The floor area is
> 24 by 12 meters.

**Why this cannot be met — arithmetic fixed before the run:**

One 8-hour shift is 28,800 seconds. 28,800 ÷ 6,000 = **4.8 s takt**.
FactoryMind's own documented reference bands
(`app/data/engineering_reference_data.py`) put *handling alone* — presenting
the unit at the station and taking it away again — at 5–12 s for
screwdriving and packaging, 5–10 s for inspection and 12–25 s for assembly,
before any per-operation content is added. No station in any covered family
can reach a 4.8 s takt. The only lever that could compensate is parallel
capacity, and the constraint set forbids both buying machines and spending
capital.

**Required behaviour:** `NO VERIFIED FEASIBLE PLAN FOUND`, carrying the best
evaluated result, the remaining gap and the binding reason. A green
recommendation here is a failure of the case regardless of how it is
justified.

**What is being tested beyond the verdict:** whether the prose constraints
("no second shift", "no additional hiring") actually reach the optimizer as
hard constraints, or whether they are silently dropped and the optimizer uses
a lever the customer forbade. Either outcome is reported.
