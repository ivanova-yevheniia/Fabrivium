# Fabrivium generalization audit — Golden-Run coupling

**Gate A of the product generalization pass.** Audit only; no production
behaviour was changed to produce this document.

**Baseline:** `HEAD = 5a9fe53` (`competition-strong-finalist-v1`), plus an
uncommitted working tree of 198 modified and 144 new files carrying earlier
phases' work. Both are captured in the checkpoint below.

**Safety checkpoint:** tag `fabrivium-checkpoint-pre-generalization` →
commit `3ca8c29`, a real commit whose tree is the **entire working tree
including untracked files** (1,017 files), parented on `5a9fe53`. It was
written through a temporary index, so creating it did not stage, stash, or
modify a single file. Recover the exact pre-generalization state with:

```
git checkout fabrivium-checkpoint-pre-generalization -- .
```

---

## The question, and the two ways of answering it badly

The question is whether Fabrivium behaves differently because the product
happens to be CEC-120.

A `grep` answers a weaker question — *does the string appear?* — and its
answer is yes, 8,299 times. Reading that as coupling would condemn a
docstring that cites a measured run. The opposite error is to wave every hit
through as "just a comment" without establishing that it is one.

So this audit is mechanical, and it turns on one fact a grep cannot supply:
for each occurrence in production code, **is that line executable?** For
Python the answer is exact — the file is run through `tokenize` and every
`COMMENT` and docstring token's line span is recorded, so a Golden-Run
literal inside a *non-docstring* string (a UI message, a lookup key) is
correctly treated as executable data rather than prose. For TypeScript it is
a small scanner over `//`, block comments and JSDoc continuation, whose one
blind spot — a comment opener inside a string literal or regex — is stated
here rather than hidden.

The scan is reproducible:

```
cd backend && python -m scripts.fabrivium_coupling_audit            # summary
                                                    --json          # per-hit
                                                    --markdown      # tables
```

It exits non-zero if any class E or F occurrence exists, so it can gate a
build. Source: `backend/scripts/fabrivium_coupling_audit.py`.

---

## Result

The table below is the state **as audited**, before anything was changed.
It is kept as the finding rather than rewritten, because an audit that
reports the state after its own fixes is a press release.

**State now, after §5 items 1-3**, run against the published tree:

```
$ cd backend && python -m scripts.fabrivium_coupling_audit ; echo "exit $?"
scanned 496 files
  A TEST FIXTURE                   1672
  B EXAMPLE DATA                   4697
  C COMPETITION COPY               386
  D DOMAIN DEFAULT                 76
exit 0
```

**Classes E and F print no line at all, because the script lists only classes
that have hits.** Zero is shown by their absence and by the exit code: the
script exits `1` if a single class E or F occurrence exists, and `0` here.

The published tree is smaller than the tree that was audited — 496 files
against 658 — because the recording, presentation and export directories are
not part of the repository. The table below is the audited tree, at
8,299 occurrences classified.

| Class | Meaning | Count |
|---|---|---:|
| **A** TEST FIXTURE | Safe | 1,746 |
| **B** EXAMPLE DATA | Safe if isolated | 5,084 |
| **C** COMPETITION COPY | Safe if presentation-only | 1,369 |
| **D** DOMAIN DEFAULT | Review | 78 |
| **E** PRODUCTION HARD-CODING | Must remove | **22** |
| **F** HIDDEN GOLDEN-RUN COUPLING | Critical | **0** |

**No production branch is keyed on the demo, the golden case, or a product
identity.** The class F probes look for `if …demo/golden/cec-120…`, for
`product_name == "…"`, and for a station-count assumption
(`operations.length === 7`). All three return nothing. The count probe
deliberately ignores `=== 0`, because an emptiness check is an empty-state
guard and assumes nothing about how many operations a product has; matching
it would have buried the real findings under 3 hits of empty-state noise.

Every CEC-120 occurrence in `backend/app` and `frontend/src` is a comment or
docstring citing the measured run as a worked example — nine of them, each
verified individually. The four golden figures (1,900 / 1,435 / 1,058 /
2,033) appear in production exclusively in commentary, in test fixtures, and
in UI example-prompt copy. None is read by a decision.

**But a clean token scan is not the same as a general product**, and §3 is
where this audit disagrees with a purely token-based reading of the
codebase. The tokens are clean; three structural couplings are not.

---

## 1. Class E — production hard-coding (22)

### E-1 Demo Mode scaffolding, carried in production state (19 occurrences)

| File | Lines | Coupling |
|---|---|---|
| `frontend/src/components/playback/DemoModeStrip.tsx` *(since deleted)* | 4, 6, 31, 59, 60, 66, 71, 85 | An eight-step guided presentation strip |
| `frontend/src/state/types.ts` | 282, 292, 519, 577 | `DemoStage` union, `DEMO_STAGES`, `AppState.demoStage` |
| `frontend/src/state/appReducer.ts` | 16, 94, 262, 751 | `SET_DEMO_STAGE` action and its reducer arm |
| `frontend/src/state/AppContext.tsx` | 26, 101, 488 | `setDemoStage` on the app context |
| `frontend/src/index.css` | 2013, 2020, 2031 | `.demo-mode-strip` rules |

`DemoModeStrip` is **imported by nothing**. Its only consumers are its own
tests and a mock in `testUtils.tsx`. `TopBar.tsx:15-24` says so explicitly
and gives the reason it is unmounted: four of its eight steps have no
consumer, two only move a 3D camera during a 2D demo, and one is a no-op.

The component being unshipped is the right call. Keeping its *state* is not:
`AppState` carries a `demoStage` field, the reducer carries an action to set
it, and the context exposes a setter — an eight-stage presentation script
sitting in the application's core state shape, serving nothing.

**Required action:** delete the component, the `DemoStage` type,
`DEMO_STAGES`, `AppState.demoStage`, the `SET_DEMO_STAGE` action, the
context method, the CSS block, and the tests whose only subject is those.
This is Phase 30 (*remove demo magic*) and it is the whole of it in the
frontend.

### E-2 Golden figures inside three Pydantic field descriptions (3)

| File | Line | Coupling |
|---|---|---|
| `backend/app/models/strategy.py` | 156 | `"…e.g. {'CAPEX': 0.0, 'OPEX_PER_DAY': 18000.0}…"` |
| `backend/app/models/strategy.py` | 316 | `description="Short human name, e.g. 'Plan A'."` |
| `backend/app/models/conversation.py` | 331 | `description="Short human label, e.g. 'Plan A'."` |

Prose in an executable position. A `Field(description=…)` is not a comment:
it ships in the OpenAPI schema and, for models used in structured-output
prompting, it is read by the language model as the field's documentation.
So the golden run's OPEX figure and its plan labels are, weakly, part of the
system's instructions to itself.

Nothing branches on them and no value is derived from them; the cost of the
finding is that `18000.0` is the exact figure the demo reports, offered to a
model as the example of what this field looks like.

**Required action:** reword to a neutral example. One-line change, no
behaviour.

---

## 2. Class D — domain defaults (78)

None of these is coupling to CEC-120. Every one is a **list**, and the
finding is about the list's *size* — which is Phase 4's question (domain
context), not Phase 1's.

| Location | Contents | Why it is D and not E |
|---|---|---|
| `data/screwdriving_candidates.json` (17) | Researched equipment for one process category | Looked up by category; any other category returns an empty shortlist plus a note. Coverage, not a branch. |
| `data/engineering_reference_data.py` (9) | Reference cycle-time bands, with their declared anchor dataset | The anchor values are recorded so the bands can be checked against measurement. They are never returned as an estimate; a test pins this. |
| `services/process_planning.py` (5) | Fact → operation rule table (`component.pcb` → "PCB placement") | Keyed by fact key. A product stating no PCB gets no PCB rule. |
| `utils/assetResolution.ts` (5) | 3D asset lookup by process family | Generic fallback for an unknown family. |
| `services/concept_builder.py` (3) | `_STAGE_VOCABULARY` — twelve process families and aliases | A list, not a branch. |
| `services/product_extraction.py` (3) | Fact vocabularies (countables, inspection phrases) | Phrase matching over what a specification may say. |
| …22 further files (36) | Equipment datasets, capability maps, estimator keyword tables | Same shape. |

The honest summary of class D: **the pipeline is not tuned to CEC-120, but
several of its vocabularies are sized to the class of product CEC-120
belongs to** — small bench-assembled goods. That is a declared coverage
limit. §3.4 is where it stops being merely declared and starts being a
defect.

---

## 3. Structural couplings — what the token scan cannot see

These are the findings that matter, and none of them would appear in any
search for a string.

### S-1 · OPERATION == PHYSICAL STATION at concept build — **RESOLVED**

`concept_validation.concept_to_factory` (line 334) maps the concept to the
simulable `Factory` with a single loop:

```
for stage in draft.stages:
    machines.append(Machine(id=stage.id, …))
    route.append(ProcessStep(machine_id=stage.id, …))
```

One stage → exactly one machine → exactly one route step. A concept
therefore cannot express any of:

* several parallel resources performing one operation, **at build time**;
* one resource performing several operations (a complete-assembly cell);
* a U-cell, or any hybrid manual/automatic grouping;
* a shared test station serving two points in the route.

**Nuance that must not be lost.** Parallelism *is* representable downstream:
`Machine.parallel_of_machine_id` and `services/machine_pool.py` model a
service pool properly, the simulator honours it, and
`candidate_generator._add_parallel_candidate` uses it to build interventions.
So one operation can end up served by N machines — but only as the *result*
of an intervention on an already-serial baseline, never as the architecture
the engineer chose up front.

What has no representation anywhere is the converse: **one resource, several
operations**. There is no cell, no operation grouping, no shared resource.

**Resolved after this audit.** `ConceptOperationGroup` lets an engineer put
a contiguous run of operations on one resource; the compiler emits one
machine and one route step whose work content is the sum of the members',
remaps boundary buffers and drops internal ones, and the grouped concept
simulates. An ungrouped concept compiles exactly as it always did, which is
asserted directly rather than assumed. See
[the roadmap](FABRIVIUM_ROADMAP.md), step 1, for what deliberately remains:
Fabrivium proposes no groupings, and the only execution mode is
`SEQUENTIAL`.

### S-2 · No production-architecture representation

There is no `ProductionArchitecture`, no `SERIAL_LINE / PARALLEL_RESOURCES /
CELLULAR / HYBRID`, and nowhere to put an architecture candidate's rationale
or provenance. The route's order is the architecture, implicitly and only.
Phase 15.

### S-3 · Units are implicit throughout

There is no unit type and no conversion boundary. Seconds, units/day, metres
and EUR are conventions carried in field names, docstrings and display
strings:

* `cycle_time: PositiveFloat` — seconds, by comment only;
* `demand_per_day` — the period is welded into the field name, so a target
  expressed per hour, per shift or per week has nowhere to live;
* `"EUR"` is a hardcoded literal in `branch_comparison.py:31,94` and in
  every cost surface. There is no currency field, and therefore no place a
  currency mismatch could be detected — which is safe today only because
  everything is EUR by assumption.

Phase 13, and it is a precondition for Phase 14: a demand of "1,900" cannot
be re-expressed against a different period while the period is part of the
attribute's name.

### S-4 · The process-family vocabulary is hardcoded in the UI, twice, inconsistently — **real defect**

The canonical vocabulary is `concept_builder._STAGE_VOCABULARY`: **twelve**
families — assembly, screwdriving, inspection, packaging, welding,
soldering, painting, machining, cleaning, labelling, curing, palletizing.

Two frontend components each hardcode their own subset, and the two do not
agree with each other or with the backend:

| Component | Offers |
|---|---|
| `ProcessDraftEditor.tsx:606-613` | assembly, screwdriving, inspection, **labeling**, packaging, **testing** |
| `RequirementCoverage.tsx:155` | assembly, screwdriving, inspection, packaging, **labelling** |

Three separate consequences, in increasing order of severity:

1. **Seven families are unreachable from the UI.** Welding, soldering,
   painting, machining, cleaning, curing and palletizing exist in the
   backend and cannot be selected — precisely the families a mechanical,
   packaging or medical-device project needs.
2. **The same operation gets a different `process_type` depending on which
   screen created it** — `labelling` from one, `labeling` from the other.
3. **Two of `ProcessDraftEditor`'s six entries silently lose reference
   data.** The reference bands in `engineering_reference_data.py` key on
   `labelling`; `labeling` matches nothing. `testing` is not a family at all
   — it is an *alias* of `inspection` — so a stage created as `testing`
   carries a `process_type` no band, no equipment map and no asset resolver
   recognises.

The component's own comment states the list exists so that "the list says
what is actually supported rather than accepting free text that quietly
degrades". Two of its six entries do exactly what it says it prevents.

**Required action:** serve the canonical vocabulary from the backend and
render both selects from it. Phases 9 and 10 (*UI renders from contracts*),
and independently a bug fix.

### S-5 · No domain / project-context abstraction

There is no `ManufacturingDomain`, no `ProjectContext`, and no
`GENERIC_MANUFACTURING` fallback. Domain knowledge is spread across the
vocabularies in class D with nothing naming which domain any of them serves,
so nothing can be scoped, swapped, or declared absent. Phase 4, and the
prerequisite for Phases 22 and 23.

### S-6 · The project lifecycle is a single string

`ProjectState.stage: str = "PRODUCT"` (`models/project.py:339`) is the whole
lifecycle model — a route pointer, documented as such. There are no stages
with status, requirements, blocking conditions or completion evidence, so
the five-stage spine (UNDERSTAND → ENGINEER → VERIFY → IMPROVE → HANDOFF)
lives only in the frontend's arrangement of screens. Phase 8.

**What is genuinely strong here, and must not be rebuilt:** the revision and
invalidation model in the same file. Inputs are split into channels
(`SIMULATION_INPUTS`, `LAYOUT`, `EQUIPMENT`, `COMMERCIAL`), each
independently versioned; every derived artifact records the revisions it was
produced at; staleness is computed, transitively, from that. Moving a
station does not invalidate a throughput result and changing a cycle time
does. Phase 18 is, in substance, already done and done well.

### S-7 · IBM Bob is a claim, not an integration

`ArchitecturePanel.tsx:211` renders "IBM Bob · development", and the
component's own comment (line 28) states Bob is "deliberately NOT a
pipeline" participant. That is currently accurate and honest.

For Phase 5 the position is: **no Bob API contract is resolvable from this
environment.** There is no `BOB_*` variable in `backend/.env`, none in the
process environment, no Bob endpoint, key, team id or SDK anywhere in the
repository, and no vendor documentation in the tree. The only configured
language provider is watsonx (`FACTORYMIND_LLM_PROVIDER=watsonx`), itself
externally blocked by the account's Lite-plan token quota.

Per the brief's own instruction — *"If the exact Bob API contract cannot be
resolved: create the provider interface and adapter boundary, but STOP
before inventing HTTP details"* — this is reported as a blocker. See
`FABRIVIUM_IBM_BOB_RUNTIME.md` for what exists and exactly what is needed to
finish it.

The good news is that the boundary Phase 5 asks for is already built:
`app/llm/provider.py` is a template-method base where a provider implements
one method, `_generate_raw`, and inherits bounded retry, JSON parsing and
mandatory Pydantic validation. Adding a real Bob transport is one file.

### S-8 · Public repository surface is empty

`README.md` is **0 bytes**. `.env.example` documents watsonx only. Phases 31
and 35.

---

## 4. What this audit clears

Stated positively, so the next phase does not re-litigate it:

* **No production code branches on the product, the demo, or the golden
  case.** Verified mechanically, gate-able, 0 occurrences.
* **No golden figure is read by any decision.** Every occurrence in
  production is commentary, a test fixture, or UI example copy.
* **`concept_example_data`** — the one function that can write CEC-120's
  measured numbers into another product's concept — runs only on an explicit
  user action, tags every value `ValueSource.EXAMPLE_DATA`, and is never
  reached from the product path. The three-case generalization run
  (`GENERALIZATION_VALIDATION_REPORT.md`) asserts no case's concept contains
  a single `EXAMPLE_DATA` value, and found none.
* **Provenance and unknown-handling are real** and are the strongest part of
  the system. `SourcedFloat`/`SourcedInt` make "unknown" a first-class state
  that cannot be confused with zero, and `concept_to_factory` refuses to
  convert rather than invent a missing cycle time.
* **Channel-based staleness** (S-6) already implements Phase 18.

---

## 5. Required actions, in dependency order

| # | Action | Phase | Blocking |
|---|---|---|---|
| 1 | Serve the canonical process-family vocabulary; render both selects from it | 9, 10 | — |
| 2 | Delete the Demo Mode scaffolding | 30 | — |
| 3 | Reword three Pydantic field descriptions | 30 | — |
| 4 | Add `ManufacturingDomain` / `ProjectContext` with a `GENERIC_MANUFACTURING` fallback | 4 | 22, 23 |
| 5 | Introduce typed units; make period and currency explicit | 13 | 14, 20 |
| 6 | Represent production architecture; break operation ≡ station | 2, 15, 16 | 17, 25 |
| 7 | Model the lifecycle as stages with status and evidence | 8 | 34 |
| 8 | Bob provider — boundary only, pending an API contract | 5 | **blocked** |
| 9 | README, `.env.example`, public repository surface | 31, 35 | — |

Items 1-3 are defect fixes and are cheap. Item 6 is the one that decides
whether Fabrivium is a line planner or a production-system planner.

---

## 6. Golden-run parity, measured rather than asserted

The changes made after this audit (§5 items 1-3, plus the Bob provider and
the core-isolation test) were checked against the checkpoint by **running
the same golden journey against both code states and comparing the output**,
rather than by reasoning about which modules were touched.

**Method.** A git worktree was created at
`fabrivium-checkpoint-pre-generalization`, a uvicorn started from it on port
8002, and another from the current tree on 8001. `scripts/golden_journey_run.py`
was run against each — it uploads the real
`Compact_Electronics_Controller_Product_Specification.pdf` through
`POST /product/upload` and drives the whole pipeline over HTTP, with the
language model off. Both full JSON logs were then compared line by line.

**Result.** Run twice — once after the first round of changes, and again
after the extraction and target-parsing fixes that the medical-device and
packaging cases produced (`FABRIVIUM_MULTI_DOMAIN_VALIDATION.md`). Those two
are real behaviour changes to the product path, so the second run is the one
that matters.

```
                    checkpoint      after round 1     final
lines                    13847            13847      13847
differing values             -                1          1
                                  elapsed_seconds   elapsed_seconds
                                    29.235→34.221     29.235→27.112
```

Wall-clock time, and nothing else, in both directions. Every engineering figure is identical:

| | Checkpoint | Current |
|---|---|---|
| Operations | 7, same names and repeat counts | identical |
| Baseline throughput | 1,196/day | 1,196/day |
| Target | 1,900/day | 1,900/day |
| Bottleneck | `m-screwdriving` | `m-screwdriving` |
| Delivered | 1,900/day | 1,900/day |
| Modeled capacity | 2,239/day | 2,239/day |
| Capacity headroom | 18% | 18% |
| Strategies retained | 4 | 4 |
| Simulations run | 28 | 28 |

**CEC-120 golden run still reproducible: YES**, byte-for-byte, and still
byte-for-byte after the whole-token marker fix, the label inflections and
the production-target generalization.

### One figure that needed explaining — now resolved

This unattended run reported a **baseline of 1,196/day and 28 simulations**,
where the competition case is **1,435/day and 23 simulations**.

**Resolved on 2026-08-31, and it was not a regression.** The harness was
omitting two engineer decisions the film shows being made on camera: the
40 s override on Cable connection ×2, and the ASSISTED automation level on
Screw fastening ×6 (39.8 s assisted against 48.0 s by hand, which is what
moved the constraint onto screwdriving and lowered the baseline).

With both decisions restored, the harness reproduces the competition case
exactly — 1,435 baseline, 465 gap, `m-assembly-2` bottleneck, 1,900
delivered, 3 strategies, 23 simulations, Plan B with +1 shift and 0 machines.

Full account, including the rule that public material quotes the competition
case only: `FABRIVIUM_CEC_CASE_PROVENANCE.md`.

---

## Appendix · Method limits

Stated so the numbers are read for what they are.

* **TypeScript commentary detection is approximate.** A `//` inside a string
  literal or a regex would be misread as a comment, understating class E.
  Every class E and F hit was read by hand, so the reported findings do not
  rest on the scanner's judgement — only the class A/B/C counts do.
* **Binary demo assets are not scanned** (`.wav`, `.mp4`, `.png`, `.pdf`).
  They cannot contain a branch.
* **Class B is not audited for isolation here.** That 5,084 is dominated by
  the recorded demo run and the presentation sources, which are example data
  by location. Whether any of it is reachable from a production import is
  §4's `concept_example_data` question, answered there.
* **The scan reads the working tree, not `HEAD`.** It therefore covers the
  uncommitted work of earlier phases, which is the code that would actually
  ship.
