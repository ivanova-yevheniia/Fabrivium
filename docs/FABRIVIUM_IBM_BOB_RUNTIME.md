# IBM Bob as a runtime provider

**Status: implemented, wired and contract-tested. The path was exercised live
during development; no transcript was kept, and `scripts/bob_smoke` re-runs the
check on demand.**

This document exists so that anyone quoting the Bob runtime knows exactly
which part is built and which part is one command away.

---

## What is true today

| | |
|---|---|
| Provider implemented | **Yes** — `backend/app/llm/bob_provider.py` |
| Wired into the factory | **Yes** — `FACTORYMIND_LLM_PROVIDER=bob` |
| Configuration documented | **Yes** — `backend/.env.example` |
| Unit tests | **47**, against a stubbed HTTP transport |
| Secrets reachable from the browser | **No** — see §6 |
| **Live call made during development** | **Yes — not recorded, so no transcript ships here** |
| **Live smoke, repeatable** | `python -m scripts.bob_smoke` — one command, on any machine with a key |

Nothing in the product UI, the README or the architecture panel claims
Fabrivium talks to IBM Bob at runtime. The one place Bob is named on screen
(`ArchitecturePanel.tsx`) says "IBM Bob · development", which was accurate
before this work and is still accurate now.

---

## 1. How the contract was resolved

The brief was explicit: *"Do NOT invent Bob API details."* So here is where
each detail came from, separated by source, with the single-sourced one
called out rather than blended in.

### From IBM's own Bob documentation (`bob.ibm.com/docs`)

* Bob issues **API keys**, and a key carries a **scope**. The scope required
  for programmatic inference is **`Inference`**.
* The credential is supplied through the environment as **`BOB_API_KEY`**.
* Authentication is either an API key — "ideal for automation, CI/CD
  pipelines, and non-interactive environments" — or SSO/IBMid via
  `bob.ibm.com/login`.
* IBM's own instruction, carried into our configuration comments verbatim in
  spirit: *"Never share your API key with anyone."*
* The model catalogue is served from an authenticated
  **`/inference/v1/model/info`** endpoint on **`api.us-east.bob.ibm.com`**.

### From `pi-bob`, a published integration package for the same service

* Base URL **`https://api.us-east.bob.ibm.com/inference/v1`**.
* The inference API is **OpenAI Chat Completions compatible**:
  **`POST {base}/chat/completions`**.
* Default authorization scheme **`Authorization: Apikey <key>`**, with
  `Bearer` used for SSO-issued tokens.
* `/model/info` lists models; entries marked `exposed: false` are excluded.
* Non-secret routing metadata (`instanceId` / `teamId`) is read from
  `~/.bob/settings.json` where present.

### What is corroborated, and what is not

**Corroborated by both sources:** the host, the `/inference/v1` path shape,
the `/model/info` endpoint, and the `BOB_API_KEY` variable name.

**Single-sourced:** the literal scheme word `Apikey`.

That asymmetry is why the scheme is a configuration value
(`FACTORYMIND_BOB_AUTH_SCHEME`, default `Apikey`, alternative `Bearer`)
rather than a constant welded into the request. If a deployment's key wants
`Bearer`, that is one environment variable and no code change.

**Not resolved, and therefore not implemented:** whether any account
requires a team or instance identifier. Headers for both exist and are sent
**only when configured** — an unset id is absent from the request rather
than sent as an empty string, because an empty string is a real (invalid)
value to some gateways.

---

## 2. What the provider does

```
LLMRequest  (system prompt + user prompt + target JSON Schema)
      |
      v
POST https://api.us-east.bob.ibm.com/inference/v1/chat/completions
     Authorization: Apikey <key>
     { "model": …, "messages": [system, user], "temperature": 0.0,
       "max_tokens": …, "response_format": {"type": "json_object"} }
      |
      v
choices[0].message.content    ->  de-fenced  ->  json.loads
      |
      v
LLMProvider.generate_structured  ->  Pydantic validation  ->  typed value
```

Four properties are inherited from the existing provider base class rather
than reimplemented, which is the reason adding Bob was one file:

* **Bounded retry.** Retryable errors are retried up to `max_retries`; auth
  and capability errors are raised on the first occurrence, because they
  fail identically every time. Never unbounded.
* **Mandatory structured output.** A response that is not valid JSON, or
  that fails the caller's Pydantic model, raises
  `LLMMalformedResponseError`. Unvalidated text never escapes.
* **Typed errors only.** No `httpx` exception crosses the provider
  boundary.
* **Fail closed.** Malformed output falls back to the deterministic backend,
  and provenance records that the fallback ran.

Three things the provider does that are specific to it being Bob:

* **A 403 names the likely cause.** A valid key with the wrong scope
  authenticates and is then refused; the error says so, because otherwise a
  scope problem reads as a bad key.
* **No model id is defaulted.** Bob's catalogue is account-specific.
  Defaulting to a guessed name would fail confusingly on an account that
  does not have it, so `FACTORYMIND_BOB_MODEL` is required and the error
  message points at the smoke script that lists the real options.
* **Provenance names the model that answered**, read back from the
  response's `model` field, not the one that was asked for — an account may
  alias.

---

## 3. What Bob is allowed to decide

Nothing with a number in it.

| Bob may | Bob may not |
|---|---|
| Understand an uploaded document | Throughput |
| Extract requirements | Capacity, takt, utilisation |
| Identify missing information | Bottleneck identification |
| Propose operations | Simulation of any kind |
| Propose production architectures | Cost arithmetic |
| Explain an alternative | Feasibility |
| Interpret a natural-language constraint | Sensitivity |
| Answer a question about a plan | Verification, Siemens readback |

This is not a convention. It is enforced by the import graph and checked
mechanically by **`backend/tests/test_deterministic_core_isolation.py`**,
which asserts that none of 32 named core modules — the simulator, capacity,
sensitivity, the candidate search, the cost model, the layout engine, the
Plant Simulation adapter — can reach `app.llm` **transitively**.

Transitive matters. A direct-import check would pass while the coupling is
fully real through one helper. The test also fails if the set of modules
importing `app.llm` changes at all, so a new module that starts calling a
provider has to be classified deliberately rather than sliding in.

The five modules permitted to reach a provider are language *boundaries*,
and what they get back is a **proposal a person accepts**, never a figure a
KPI reads: `llm_integration`, `conversation_orchestrator`, `estimation`,
`product_intelligence`, `skills/contract`.

---

## 4. Finishing the integration

Everything below needs a Bob account. None of it needs a code change.

1. In the Bob portal, create an API key with **Scope = `Inference`**.
2. In `backend/.env` (gitignored, never committed):

   ```
   BOB_API_KEY=<your key>
   FACTORYMIND_BOB_MODEL=<from step 3>
   ```

3. From `backend/`, run the smoke script:

   ```
   python -m scripts.bob_smoke
   ```

   It lists the models the account can actually reach, then makes one cheap
   real call through the same path a planning run uses. It prints endpoint,
   model, latency, token usage and request id — and never the key.

4. If step 3 passes, enable it:

   ```
   FACTORYMIND_LLM_ENABLED=true
   FACTORYMIND_LLM_PROVIDER=bob
   ```

5. **Update the "Live smoke" row at the top of this document**, and only
   then may anything claim Fabrivium calls Bob at runtime.

### Failures, and what each one means

| Symptom | Cause |
|---|---|
| `NOT CONFIGURED: No Bob API key` | `BOB_API_KEY` unset |
| `FACTORYMIND_BOB_MODEL is not set` | Required; run the smoke script for the list |
| **403** | Most likely the key's scope is not `Inference` |
| **404** on chat, catalogue listed fine | The model id — compare against the printed list |
| Catalogue unreachable, chat works | Normal for a deployment that exposes chat only |
| `LLMMalformedResponseError` | The model returned prose. Try `FACTORYMIND_BOB_JSON_MODE=true` |

---

## 5. What is deliberately not built

* **No streaming.** Every Fabrivium call is a structured extraction whose
  value is the validated object, not the typing effect.
* **No model discovery at call time.** `pi-bob` discovers models from
  `/model/info` on startup. Fabrivium requires an explicit model id instead:
  a provider that picks its own model makes a run non-reproducible, and
  reproducibility is the property the whole product is built on. Discovery
  lives in the smoke script, where it is a diagnostic.
* **No `openai-responses` or `anthropic-messages` adapters.** `pi-bob`
  supports all three; Fabrivium sends chat completions only, because one
  tested wire format is worth more than three untested ones.
* **No conversation memory.** Each call is independent and carries its own
  context, which is what makes a result reproducible from its inputs.

---

## 6. Data that would reach IBM Bob

Stated concretely. "Customer data is secure" is not a claim this document
makes.

**What is sent, when Bob is enabled:**

* The **system prompt**, which is Fabrivium's own instruction text plus the
  target JSON Schema generated from its Pydantic models.
* The **user prompt**, which is the compact context the calling agent built.
  For product understanding this includes **text the customer supplied** — a
  pasted product description, or text extracted from an uploaded
  specification.
* The configured **model id**, and `team_id`/`instance_id` if set.

**What is never sent:** the API key to the browser; a whole `Factory`
object; stored project documents; anything from the simulator.

**Therefore: if a customer's specification is confidential, enabling any
external provider sends parts of it to that provider.** That is a deployment
decision, not a technical detail, and it is why `FACTORYMIND_LLM_ENABLED`
defaults to **false** and Fabrivium runs completely without a provider.

**Secret handling, verified:**

* `backend/.env` is gitignored and not tracked; only `.env.example`
  (placeholders) is in the repository.
* The key is read server-side only. The frontend receives `provider_name`
  and the public model id — never a credential.
* Every error body is **redacted** before it reaches an exception message
  (`BobSettings.redact`), because a gateway echoing a request header into
  its error response is not hypothetical, and an exception message is the
  one place a secret reliably reaches a log. Six HTTP statuses and a
  non-JSON body are tested for this.
* `repr()` of both the settings and the provider renders `<redacted>`.
* The test suite forces `FACTORYMIND_LLM_ENABLED=false` before any module
  imports `app.main`, so it can never start billing.

---

## 7. Bob's other role

Separately from any of the above, IBM Bob was used as a **development-time**
assistant while Fabrivium was built. That is what `ArchitecturePanel.tsx`
describes, and it is a different claim from runtime inference. The two are
kept apart on purpose: one is a statement about how the code was written,
the other about what the running system does, and merging them is how a
demo starts describing capabilities it does not have.

**Sources:** [IBM Bob docs — install and setup](https://bob.ibm.com/docs/shell/getting-started/install-and-setup) · [IBM Bob docs — introduction](https://bob.ibm.com/docs/ide/getting-started/tutorials/introduction) · [pi-bob package reference](https://pi.dev/packages/pi-bob)
