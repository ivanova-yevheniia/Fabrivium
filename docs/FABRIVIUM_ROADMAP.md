# Fabrivium — where it goes next

Fabrivium today takes a product specification and returns a production line
an engineer can defend: every input traceable, every figure simulated, and a
model that opens in Siemens Plant Simulation.

The next step is larger. A line is not a production system. An engineer does
not draw five stations in a row — they decide how many cells, which resources
are shared, which work belongs to one operator and which to a machine, and
what the company's own standards allow. That is the product Fabrivium is
being built toward, and this document says how it gets there: what exists
now, what comes next, in what order, and how each step will be proved.

---

## The foundation this is built on

Everything below assumes these are already in production and tested.

| Capability | State today |
|---|---|
| Specification → structured manufacturing facts, each citing its sentence | Working |
| Engineering model with provenance, unknowns and revisions | Working |
| Deterministic discrete-event simulation of the concept | Working |
| Improvement strategies generated and simulated, not guessed | Working |
| Engineering Knowledge Base — 71 versioned, provenanced items | Working, served from `GET /knowledge` |
| Siemens Plant Simulation handoff, verified by read-back | Working on Windows with Plant Simulation 2404 |
| Deterministic core unreachable from the language layer | Enforced by test over 32 core modules |
| One resource performing several operations | Working — engineer-declared, 27 tests |

That last row matters most for what follows. `ConceptOperationGroup` already
lets an engineer say *these four operations happen at one bench*, and the
compiler turns that group into one machine and one route step: cycle time the
sum, capacity the tightest member, operator demand the most demanding one,
internal buffers dropped and boundary buffers remapped. The grouping is
explicit, reversible, refused when it cannot be simulated, and it invalidates
any verification that came before it.

The architecture can therefore be **expressed**. Proposing it is step 1.

Every engineering figure Fabrivium publishes is reproducible with the
language-model layer switched off, so each step below is built on a result
that does not depend on a provider being reachable.

---

## Step 1 — Production architecture synthesis

**This step decides whether Fabrivium is a line planner or a production-system
planner.** It is larger than everything below it combined.

**Today.** Every concept starts as a serial line, one station per operation.
An engineer can group operations, and interventions can add parallel resources
to an existing station through a real service pool (`machine_pool.py`). The
throughput arithmetic is right. The architecture is the one the engineer
built, not one Fabrivium offered.

**Next.** A topology object — serial line, parallel resources, cellular,
hybrid — that can hold a *candidate* architecture with its parallelism, shared
resources, workforce allocation, rationale and provenance. Fabrivium then
proposes two or three architectures for the same product, simulates each, and
puts them in front of the engineer the way it puts improvement plans there
today: with the numbers, the cost, and what each one leaves unpriced.

**The boundary stays where it is.** Proposing candidates is a language-model
task. Structuring, simulating and comparing them is not, and the deterministic
core will not learn to reach upward for a suggestion.

**Proved when** two architectures for one product can be simulated and
compared like two improvement plans, and accepting one is an engineer's
recorded decision.

---

## The path, in dependency order

| # | Step | Today | What it unlocks |
|---|---|---|---|
| **1** | **Production architecture synthesis** | Groups can be declared by an engineer | Cells, shared resources and non-serial products, proposed and compared |
| **2** | **Typed units and currency** | Seconds, units/day, metres and EUR by convention | Demand stated per hour, per shift or per week; a currency mismatch that refuses instead of converting |
| **3** | **Domain context** | Vocabularies and rules exist without naming the domain they serve | Scoped terminology per domain, and a domain that can declare itself absent |
| **4** | **Coverage that knows what it missed** | Coverage measures extracted facts, and says so on screen | A route that can report *the document describes filling; no family covers it* |
| **5** | **Lifecycle model** | The stage is a route pointer | Domain-specific steps — flashing and ESD, filling and sealing, torque and dimensional inspection |
| **6** | **Engineering Skills as installable packages** | Fourteen workflows run on the knowledge base | A company's own standards, approved suppliers, cost models and layout rules |
| **7** | **The IBM Bob runtime path, executed live** | Implemented, wired, 47 contract tests | One command's worth of evidence: `python -m scripts.bob_smoke` |
| **8** | **Estimation coverage beyond five families** | 5 of 12 families have measured bands; 3 have researched equipment | Welding, soldering, painting, machining, cleaning, curing, palletizing |

Steps 2 and 3 are independent of 1 and can run in parallel. Step 4 should
follow 3, because measuring coverage before a domain can be named would
measure the wrong thing.

### Step 4 deserves its own paragraph

Coverage today answers *is every extracted requirement represented in the
route?* The step is to make it answer the harder question: *does the route
cover the document?* A metric that compares the plan against the source text
can say **the document describes a filling step and no process family covers
it** — which is the difference between a number that reassures and a number
that directs the next hour of engineering work. The validation runs that
shaped this step are in
[multi-domain validation](FABRIVIUM_MULTI_DOMAIN_VALIDATION.md).

---

## Further out

Beyond the numbered path, these are the directions the architecture already
allows and the product does not yet take.

**Company knowledge as a package.** The Engineering Knowledge Base is
versioned and provenanced item by item, and each item already records whether
it came from an implemented rule, a reference table, a manufacturer document,
an external standard or a customer record. Packaging that as something a
company installs — its standards, its approved suppliers, its cost models — is
the step from a tool an engineer uses to a tool a company owns.

**Product mix and changeover.** One product per run today. Mix, sequencing and
changeover cost are the next question every planner asks after throughput.

**Uncertainty as a distribution.** Today uncertainty is expressed as
sensitivity: the result recomputed across an input's band, deterministically.
Stochastic cycle times and confidence intervals are the natural extension, and
they only mean something on top of a deterministic result that can be
reproduced exactly — which is why that order is deliberate.

**Deeper Siemens synchronization.** Station names, positions, cycle times,
capacities, buffers and the flow chain transfer today and are verified by
reading the saved model back. Operator demand, the shift pattern and
provenance do not. Carrying the workforce constraint across is the largest
remaining piece, and it needs a representation that does not smuggle in
Plant Simulation's walking workers as if Fabrivium had modelled them. The
measured differences are in
[cross-simulator semantics](CROSS_SIMULATOR_SEMANTICS.md).

---

## How the next step gets chosen

The method does not change with the roadmap.

* **Nothing is claimed before it is run.** Scenarios, predictions and pass/fail
  tolerances are written down first — see
  [the cross-simulator preregistration](CROSS_SIMULATOR_VALIDATION_PLAN.md),
  written before a single model was executed in Plant Simulation.
* **A result is scored against the bar that was set first.** In that
  comparison the tolerance was never widened after the fact, and the report
  says so scenario by scenario.
* **Every public sentence maps to a row** in the
  [claim matrix](FABRIVIUM_CLAIM_MATRIX.md). If a claim is not supported
  there, it is not said.

A roadmap is worth what the evidence behind the last step was worth.

---

## One rename still owed

The product was called FactoryMind. The rebrand is complete in everything a
user reads, and deliberately incomplete in three places where changing a name
would break something:

* `FactoryMindExchange` — the class naming the Plant Simulation exchange
  package, which appears in generated exchange artifacts;
* the `X-FactoryMind-Skills` HTTP header, shared by backend and frontend, which
  any external client would be broken by;
* the `FACTORYMIND_…` environment-variable prefix, which every existing local
  `.env` depends on.

All three can be renamed safely at a release boundary, together, with a
migration note. None of them can be renamed quietly.
