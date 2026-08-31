# IBM Bob and Fabrivium

Two different things share a name here, and conflating them would be the
easiest dishonesty in this submission. They are kept apart on purpose.

| | Development role | Runtime provider |
|---|---|---|
| What | IBM Bob assisted in building Fabrivium | `BobProvider` calls Bob's inference API |
| Status | **True and evidenced** | **Implemented and contract-tested; the path was exercised live during development, and no transcript was kept** |
| Claimable as | "IBM Bob was used to build this" | "A provider is implemented and contract-tested, and `scripts/bob_smoke` re-runs the live check" |
| NOT claimable as | — | "Powered by IBM Bob", "Integrated with IBM Bob" |

---

## 1. Development role

IBM Bob was used as an AI SDLC partner across this project's phases, and
the work was not only code:

| Where | What Bob was used for |
|---|---|
| **Architecture** | Which mechanisms the product needs at all — provenance that survives an edit, unknowns that block a run instead of defaulting to zero, revision invalidation, and the boundary between the language layer and the deterministic core |
| **Planning** | Breaking the build into stages small enough that each one could be verified before the next began, and deciding what belonged in which stage |
| **Concept design** | How a written specification becomes an engineering model, and where a human decision has to sit in that chain |
| **Implementation** | Backend, frontend and the Siemens Plant Simulation integration |
| **Testing** | Test design, regression analysis, and the audits and validation reports under `docs/` |
| **Debugging and review** | Including defects that were found and changes that were rejected |
| **Runtime** | The `BobProvider` written against Bob's inference API |

The evidence a reviewer can check is not a narrative — it is a chain of
artefacts, each of which either runs or fails:

| Artefact | What a reviewer can do with it |
|---|---|
| `backend/app/llm/bob_provider.py` | Read the provider written against Bob's inference API |
| `backend/tests/test_bob_provider.py` | Run 47 tests over request construction, response parsing, the HTTP error taxonomy, bounded retry and key redaction |
| `backend/tests/test_deterministic_core_isolation.py` | Assert that no engineering-core module can reach the provider layer, transitively |
| `python -m scripts.fabrivium_coupling_audit` | Confirm 0 production hard-codings and 0 hidden golden-run couplings |
| `python -m scripts.golden_journey_run` | Reproduce the CEC-120 case end to end from the source document |
| `docs/FABRIVIUM_CLAIM_MATRIX.md` | Check every public sentence against the claim it is allowed to make |
| `docs/SIEMENS_HANDOFF_VERIFICATION.md` | Check the Plant Simulation handoff against read-back evidence |

Each was produced by the same loop: an engineering objective, a Bob-assisted
implementation or test design, an automated gate, and an engineering review
that could reject the result and send it back. The artefacts are specific
about what was measured, what failed, and what was left undone — which is
what makes the claims checkable rather than assertable.

This is a statement about **how the code was written**. It says nothing
about what the running system does, and it is not evidence for the runtime
row above.

## 2. Runtime provider

`backend/app/llm/bob_provider.py` implements Bob's inference API behind
Fabrivium's existing `LLMProvider` contract.

**What is real:**

* The API contract was resolved from IBM's own Bob documentation and a
  published integration package, and `docs/FABRIVIUM_IBM_BOB_RUNTIME.md`
  records which detail came from which source — including the one that is
  single-sourced and is therefore a configuration value rather than a
  constant.
* Base URL `https://api.us-east.bob.ibm.com/inference/v1`, OpenAI-compatible
  `POST /chat/completions`, `Authorization: Apikey <key>`, credential in
  `BOB_API_KEY`, key scope **`Inference`**.
* 47 unit tests cover request construction, response parsing, truncation and
  refusal handling, the full HTTP error taxonomy, retry boundedness, and
  redaction of the API key out of every error message.
* Selectable with `FACTORYMIND_LLM_PROVIDER=bob`.

**What the repository can and cannot show:**

The path was exercised live during development, through Bob's inference API,
and it worked. **No transcript was kept from those runs**, so this repository
does not ship a recording of one — and a claim without an artefact is worth
less than a command anyone can run.

That command is `python -m scripts.bob_smoke` from `backend/`. It lists the
models the account can reach, then makes one cheap real call through the same
path a planning run uses. On a machine with a key it re-establishes the live
result in seconds, which is why the evidence offered here is the contract
suite plus that script rather than a saved log.

### The other IBM provider

The watsonx provider is implemented and **externally blocked**: live Granite
calls return `403 token_quota_reached` because the account's watsonx.ai
instance is on the Lite plan and its monthly allowance is exhausted. Nothing
in the code can unblock it.

The designed behaviour is what runs: the 403 maps to a non-retryable error,
exactly one call is made with no retry storm, the deterministic backend
takes over, and provenance records that the fallback ran.

**So Fabrivium's demonstrated behaviour is its deterministic path.** Every
result in this repository — the CEC-120 case, the mechanical and packaging
domains, the browser QA — was produced with `FACTORYMIND_LLM_ENABLED=false`.
That is a strength worth stating rather than hiding: the engineering claims
do not depend on a model being reachable.

---

## 3. The deterministic boundary

This is the part that makes the language integration safe, and it is
enforced rather than intended.

```
    Bob / any language model            Fabrivium
    ────────────────────────            ─────────
    understands                         calculates
    extracts                            simulates
    classifies                          compares
    proposes                            verifies
    explains                            refuses when it does not know
```

A model may **understand, extract, classify, propose and explain**. It may
not compute throughput, capacity, takt, utilisation, bottleneck, cost,
feasibility, sensitivity or verification.

**How it is enforced:**
`backend/tests/test_deterministic_core_isolation.py` asserts that none of 32
named core modules — the simulator, capacity, sensitivity, candidate search,
cost model, layout engine, Plant Simulation adapter — can reach the provider
layer **transitively**. A direct-import check would pass while the coupling
was fully real through one helper.

It also fails if the *set* of modules importing `app.llm` changes at all, so
a new module that starts calling a provider has to be classified
deliberately. Exactly five modules may: `llm_integration`,
`conversation_orchestrator`, `estimation`, `product_intelligence` and
`skills/contract`. What each gets back is a **proposal a person accepts**,
never a figure a KPI reads.

Every model output additionally passes JSON parsing → Pydantic validation →
domain validation → explicit human acceptance where it matters. Malformed
output fails closed to the deterministic path.

**Prompts are domain-neutral, and that is tested too**
(`test_prompt_domain_neutrality.py`, 28 tests): no production prompt names
an industry, a product or a line shape, and the process-family vocabulary
the model receives is generated from the canonical catalog rather than
typed into a prompt.

---

## 4. What to say

**Accurate:**

> "IBM Bob was used throughout development — architecture, planning,
> concept design, implementation, testing and documentation. At runtime,
> Fabrivium has an implemented and contract-tested Bob provider, and that path
> was exercised live while building; `scripts/bob_smoke` re-runs the check, and
> every engineering result shown was produced by the deterministic engine."

**Not accurate:**

> ~~"Fabrivium is powered by IBM Bob."~~
> ~~"Fabrivium integrates IBM Bob for production planning."~~

See `docs/FABRIVIUM_CLAIM_MATRIX.md` §5 for the binding wording.
