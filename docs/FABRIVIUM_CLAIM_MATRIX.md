# Fabrivium claim matrix

**No README, submission page or spoken claim may exceed a row in this
table.** If a sentence is not supported here, it is not said.

Status vocabulary, used strictly:

| Status | Means |
|---|---|
| **DEMO-VERIFIED** | Run end to end, by a person, and the evidence is in the repository |
| **TESTED** | Covered by an automated test that fails if it breaks |
| **IMPLEMENTED** | Built and working, not covered end to end |
| **ROADMAP** | Not built. May be described as intended, never as present |

---

## 1. The competition case

| Claim | Status | Evidence | Allowed wording | Forbidden |
|---|---|---|---|---|
| CEC-120 goes from 1,435 to 1,900 units/day | **DEMO-VERIFIED** | `docs/FABRIVIUM_CEC_CASE_PROVENANCE.md`, `examples/electronics/CEC-120_competition_case.json`, `backend/scripts/golden_journey_run.py` | "A verified case study: 1,435 → 1,900/day" | "Fabrivium optimises any line to target" |
| The plan buys no new machines and costs €18,000/day more | **DEMO-VERIFIED** | Same run | "The chosen plan added a shift, not a machine" | "Fabrivium finds free capacity" |
| 23 simulations were run to choose it | **DEMO-VERIFIED** | Recorded arena output | "23 simulated alternatives" | "23 optimisations" |
| The 40 s cycle time was an engineer's override | **DEMO-VERIFIED** | Provenance badge ENGINEER in the run | "An engineer overrode the estimate; provenance says so" | "Fabrivium measured 40 s" |
| The figures are reproducible from their inputs | **DEMO-VERIFIED** | `backend/scripts/golden_journey_run.py`, 2026-08-31: 1,435 / 465 / `m-assembly-2` / 1,900 / 3 / 23, from the source PDF through the production API | "Reproducible on demand from the source document" | "Deterministic under any change" |
| The competition case is one of two CEC configurations | **DOCUMENTED** | `FABRIVIUM_CEC_CASE_PROVENANCE.md` | "Public material quotes the competition case only" | Calling the unattended baseline "the canonical CEC case" |

**There are two CEC-120 configurations and only one is public.**

| | Competition case | Unattended baseline |
|---|---|---|
| Baseline | **1,435/day** | 1,196/day |
| Bottleneck | Cable connection ×2 | Screw fastening ×6 |
| Simulations | **23** | 28 |
| Public? | **Yes** | No — internal regression evidence |

They differ by exactly two engineer decisions (a 40 s override, and ASSISTED
rather than MANUAL screwdriving). Never present one number as the other, and
never call the unattended run "the canonical CEC case". Full account:
`docs/FABRIVIUM_CEC_CASE_PROVENANCE.md`.

## 2. Generalization

| Claim | Status | Evidence | Allowed wording | Forbidden |
|---|---|---|---|---|
| No production code branches on the product or the demo | **TESTED** | `backend/scripts/fabrivium_coupling_audit.py`, class E = 0, F = 0, exits non-zero on a finding | "No production branch is keyed on the product, the demo or the golden case" | "No demo-specific code exists anywhere" (fixtures and example data do) |
| Mechanical product runs the same pipeline to a verified simulation | **DEMO-VERIFIED** | `examples/generalization/results/case_m.json` — 420/420, demand met | "A mechanical actuator ran the same path to a verified 420/day" | "Fabrivium supports mechanical assembly" (7 of its operations have no rule) |
| Packaging product runs the same pipeline to a verified simulation | **DEMO-VERIFIED** | `case_p.json` — 2,952/4,000, bottleneck `m-packaging`, 3 strategy options | "A filling line ran the same path, found its constraint and generated priced-incomplete options" | "Fabrivium plans packaging lines" |
| Five non-CEC products have been run from a written specification | **DEMO-VERIFIED** | `case_{a,b,c,d,e,m,p}.json`, all pre-registered | "Seven products, five domains, one pipeline" | "Fabrivium works for any product" |
| No CEC-120 value reaches another product | **TESTED** | `backend/scripts/generalization_audit.py`: "no leakage or unknown-substitution finding" on every case | "No golden-run figure reaches another product" | "No data leakage is possible" |
| Browser UI is domain-neutral | **DEMO-VERIFIED** | Mechanical + packaging at 1920/1440/1366: 0 overflow, 0 console errors, 0 electronics strings | "The same UI renders a mechanical and a packaging project without electronics vocabulary" | "The UI adapts to any domain automatically" |

## 3. Engineering integrity

| Claim | Status | Evidence | Allowed wording | Forbidden |
|---|---|---|---|---|
| A language model cannot reach the simulation core | **TESTED** | `backend/tests/test_deterministic_core_isolation.py` — transitive import graph, 32 core modules | "Enforced by an architecture test, transitively" | "The AI cannot affect results" (it proposes values a person may accept) |
| Unknown is never silently substituted | **TESTED** | `SourcedFloat`/`SourcedInt`; `concept_to_factory` refuses; generalization audit finds no substitution | "A missing cycle time stays missing and blocks simulation" | "Fabrivium never guesses" (it estimates, labelled) |
| Every value carries provenance | **TESTED** | Provenance suites; badges in UI | "Every value knows where it came from" | "Every value is verified" |
| Verification goes stale when inputs move | **TESTED** | Channel model; `backend/tests/test_operation_grouping.py` pins grouping invalidation | "Changing a simulation input invalidates the verified result" | "Fabrivium always knows what is current" |
| Simulation is deterministic discrete-event | **IMPLEMENTED** | SimPy; `services/simulation.py` | "Deterministic discrete-event simulation" | "Stochastic/Monte-Carlo analysis" — there is none |
| What "VERIFIED" covers | **TESTED** | Badge reads "Verified by deterministic simulation of the current engineering model" | "Verified under the modelled process and engineering inputs" | "Verified that the product can be manufactured", "the document was fully understood" |

## 4. Operation â‰  station

| Claim | Status | Evidence | Allowed wording | Forbidden |
|---|---|---|---|---|
| Several operations can share one physical resource | **TESTED** | `ConceptOperationGroup`; 27 tests in `backend/tests/test_operation_grouping.py` | "An engineer can declare that one cell performs several operations" | "Fabrivium designs cells" — it records the engineer's decision |
| A grouped architecture simulates | **TESTED** | `backend/tests/test_operation_grouping.py::test_a_grouped_concept_simulates` | "A grouped concept compiles and simulates" | "Fabrivium optimises cell layout" |
| Cell work content is the sum of its operations | **TESTED** | `backend/tests/test_operation_grouping.py::test_cell_work_content_is_the_sum_and_never_less` | "Sequential cell work content = the sum" | "Fabrivium models cell concurrency" — only SEQUENTIAL exists |
| Grouping is reversible and invalidates verification | **TESTED** | API tests + channel test | "Explicit, reversible, and it re-opens verification" | — |
| Automatic production-architecture synthesis | **ROADMAP** | Not built | "Planned: Bob proposes architectures, Fabrivium simulates them" | Any present-tense claim |

## 5. Language / IBM Bob

| Claim | Status | Evidence | Allowed wording | Forbidden |
|---|---|---|---|---|
| Production prompts are domain-neutral | **TESTED** | `backend/tests/test_prompt_domain_neutrality.py`, 28 tests over the 6 real prompts | "No production prompt names an industry; verified by test" | "The AI is domain-agnostic" |
| The process-family catalog reaches the model dynamically | **TESTED** | Same file; composed from `services.process_families` | "The model is given the canonical twelve families, generated not typed" | — |
| BobProvider is implemented | **IMPLEMENTED** | `app/llm/bob_provider.py` | "An IBM Bob provider is implemented and wired" | "Fabrivium runs on IBM Bob" |
| BobProvider is contract-tested | **TESTED** | `backend/tests/test_bob_provider.py`, 47 tests against a stubbed transport | "Request construction, parsing, error mapping and key redaction are tested" | "Verified against IBM Bob" |
| **A live Bob call has been made** | **DONE IN DEVELOPMENT, NOT RECORDED** | The path was exercised live while building; no transcript was retained. Repeatable with `backend/scripts/bob_smoke.py` | "The provider is implemented and contract-tested, and the path was exercised live during development; the repository ships the contract suite and a smoke script rather than a saved transcript" | "Powered by IBM Bob" · citing the live run as if a recording of it were in the repository |
| IBM Bob was used to build Fabrivium | **TRUE, development-time** | `docs/IBM_BOB_DEVELOPMENT.md` | "IBM Bob was used during development" | Conflating this with runtime inference |
| IBM watsonx runtime | **IMPLEMENTED, externally blocked** | 403 `token_quota_reached`, Lite plan | "watsonx provider implemented; the account's quota is exhausted, and the deterministic fallback is what runs" | "Powered by watsonx" |

## 6. Siemens Plant Simulation

| Claim | Status | Evidence | Allowed wording | Forbidden |
|---|---|---|---|---|
| A real `.spp` model is produced and reopens correctly | **DEMO-VERIFIED** | `docs/SIEMENS_HANDOFF_VERIFICATION.md` — OLE header, topology and cycle times checked in Plant Simulation | "A real Siemens Plant Simulation handoff, verified in the application" | "Fabrivium runs inside Plant Simulation" |
| Requires a local Windows install | **TRUE** | COM / pywin32 | "Requires Tecnomatix Plant Simulation 2404 locally" | Implying a cloud path |
| The two simulators agree | **PARTIAL, and measured** | `docs/CROSS_SIMULATOR_VALIDATION_REPORT.md`, scored against the tolerance fixed in advance in `docs/CROSS_SIMULATOR_VALIDATION_PLAN.md`; raw record in `docs/evidence/cross_simulator_evidence.json`; the semantic differences in `docs/CROSS_SIMULATOR_SEMANTICS.md` | "Where Fabrivium's workforce constraint is not binding, the two engines agree to within one unit per day (1,104 vs 1,104 and 2,463 vs 2,462). Where it binds, they differ by a known and stated amount, because the workforce does not transfer. One of the four gated scenarios missed the preregistered tolerance by two units and is reported as a failure." | "Results match Siemens" · "Siemens validates Fabrivium" · quoting the agreement without saying that it holds where the workforce constraint is not binding |

## 7. Knowledge and skills

| Claim | Status | Evidence | Allowed wording | Forbidden |
|---|---|---|---|---|
| Engineering Knowledge Base, 71 provenanced items | **IMPLEMENTED** | `GET /knowledge` | "71 versioned, provenanced knowledge items" | "A comprehensive manufacturing knowledge base" |
| Standards compliance | **NO** | API returns `claims_standards_compliance: false` | "Fabrivium points at standards; it does not certify against them" | "Standards-compliant" |
| Engineering Skills as installable packages | **ROADMAP** | 14 workflow skills exist; manifest packaging does not | "14 workflows; packaged Skills are planned" | "Extensible skill marketplace" |

## 8. Coverage — the limits that must travel with any generalization claim

| Fact | Status | Required qualifier |
|---|---|---|
| 12 process families | **IMPLEMENTED** | — |
| 5 of 12 have a measured reference band | **TRUE** | Say "5 of 12" whenever estimation is mentioned |
| 3 of 12 have researched equipment data | **TRUE** | Say "3 of 12" whenever equipment evidence is mentioned |
| No rule for joining, functional test, filling, sealing, collating | **TRUE** | Mechanical and packaging routes are **partial**, and this must be said alongside "it works" |
| Coverage reports over extracted facts, not over the document | **TRUE, and now said on screen** | The metric is named *extracted-requirement coverage*, carries a "What does this mean?" scope note, and shows a PROCESS SCOPE line stating that completeness against the source is not independently established |

---

## The three sentences most likely to be over-claimed

1. **"It works for any product."** It does not. Seven products have run; two
   domains route only partially; five of twelve families have estimation
   data. Say *"the same pipeline ran seven products across five domains,
   with declared coverage limits."*

2. **"Powered by IBM Bob."** Fabrivium's engineering results are produced by
   the deterministic engine, not by a model. Say *"IBM Bob was used to build
   Fabrivium, and an IBM Bob provider is implemented and contract-tested; the
   path was exercised live in development and `scripts/bob_smoke` re-runs that
   check."*

3. **"Verified by simulation."** True of throughput, and only of throughput,
   and only of the model that was built. It is not verified cost, not
   verified feasibility, not a verified layout, and not evidence that the
   source document was completely understood — coverage measures extraction,
   not the document. Say what was verified, and against what.