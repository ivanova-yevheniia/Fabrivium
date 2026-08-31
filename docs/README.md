# Documentation

Every record here answers one question and states its own boundary. Where a
report is older than the current tree, it says so at the top rather than being
rewritten.

## Start here

| Document | What it answers |
|---|---|
| [Claim matrix](FABRIVIUM_CLAIM_MATRIX.md) | Every public claim, and the evidence allowed to support it. **No statement anywhere may exceed a row in this table.** |
| [Roadmap](FABRIVIUM_ROADMAP.md) | Where Fabrivium goes next: what exists today, what comes next, in what order, and how each step gets proved |
| [CEC-120 case provenance](FABRIVIUM_CEC_CASE_PROVENANCE.md) | Which run produced which number in the case study |
| [The run, screen by screen](GOLDEN_RUN_WALKTHROUGH.md) | The CEC-120 case as the product shows it, captured from this build |

## Does it work outside the demo?

| Document | What it answers |
|---|---|
| [Multi-domain validation](FABRIVIUM_MULTI_DOMAIN_VALIDATION.md) | Medical device and packaging cases, and the three production defects they found |
| [Generalization validation](GENERALIZATION_VALIDATION_REPORT.md) | Three unseen products, seven findings — four fixed, three reported unfixed |
| [Coupling audit](FABRIVIUM_GENERALIZATION_AUDIT.md) | Is any production branch keyed on the demo, the product or the golden case? |
| [Generalization code audit](GENERALIZATION_CODE_AUDIT.md) | The earlier file-by-file audit of the same question |

## Siemens Plant Simulation

| Document | What it answers |
|---|---|
| [Handoff verification](SIEMENS_HANDOFF_VERIFICATION.md) | What reaches the generated model, and what does not |
| [Execution audit](PLANT_SIMULATION_EXECUTION_AUDIT.md) | Was the generated model runnable at all? |
| [Cross-simulator semantics](CROSS_SIMULATOR_SEMANTICS.md) | What "units/day" means in each engine, measured rather than assumed |
| [Cross-simulator preregistration](CROSS_SIMULATOR_VALIDATION_PLAN.md) | The scenarios, predictions and tolerance, fixed before the first run |
| [Cross-simulator validation report](CROSS_SIMULATOR_VALIDATION_REPORT.md) | The executed comparison, including the one gated scenario that failed |
| [Raw run record](evidence/) | The machine-readable output behind that report |

## Engineering and IBM Bob

| Document | What it answers |
|---|---|
| [Engineering Knowledge Base](FABRIVIUM_ENGINEERING_KNOWLEDGE_BASE.md) | The 71 knowledge items, their provenance, and how they are served |
| [Simulation scope](SIMULATION_SCOPE_AND_LIMITATIONS.md) | What the simulator deliberately leaves out |
| [IBM Bob development](IBM_BOB_DEVELOPMENT.md) | How IBM Bob was used to build the product |
| [IBM Bob runtime](FABRIVIUM_IBM_BOB_RUNTIME.md) | The provider: how the API contract was resolved, what is tested, and how to re-run the live check |

## Images

`assets/` holds the images used by the top-level README. `images/` holds
product and Plant Simulation screenshots cited by the reports.
