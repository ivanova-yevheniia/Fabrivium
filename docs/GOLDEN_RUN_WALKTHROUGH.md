# The run, screen by screen

This is the CEC-120 case as the product actually shows it — the same path the
demo film takes, captured from the build in this repository with the
**language-model layer switched off**.

Nothing here is a mock-up. Every screen below is reachable in a few minutes:

```bash
cd backend && uvicorn app.main:app          # terminal 1
cd frontend && npm install && npm run dev   # terminal 2
```

Then open the app and choose **Explore the example project**. No provider and
no API key are needed.

---

## 1 · Start

![The Fabrivium landing screen: a field to name a new project, an empty recent-projects list, and a button to explore the bundled example project](images/walkthrough/01-landing.png)

A project is a named, saved thing. The example project carries Fabrivium's own
bundled specification, and everything that comes out of it is labelled as
example data.

---

## 2 · The document

![The product screen with the bundled compact electronics controller specification pasted into a text area, with a note that this is Fabrivium's own example document read by the same extractor as a real one](images/walkthrough/02-product-start.png)

A specification arrives as a PDF or as text. This one is Fabrivium's own
example document — **read by exactly the same extractor as a customer file**,
which is the only reason it is worth showing.

---

## 3 · What was read, and what was not

![The product understanding screen listing detected facts — enclosure, label, PCB, 2 cable connections, 6 screws, ABS material — each with a Document badge and an Evidence link, one of them expanded to show the sentence it came from, and a STILL NEEDED section naming the screw thread and torque](images/walkthrough/03-product-facts.png)

Every fact carries a **`Document`** badge and an **Evidence** link. The expanded
one shows the sentence it was taken from — *"pre-crimped connectors and are
attached by hand during assembly."*

Underneath is the part most tools leave out: **STILL NEEDED**. The document
never states the screw thread, drive type or torque, so Fabrivium says so and
names what that blocks — equipment validation. It does not invent a screw.

---

## 4 · The process, with its reasoning attached

![The proposed manufacturing process: seven operations in route order, each with a Fabrivium rule badge and a why-was-this-proposed control, one expanded to show the rule and the quoted source sentence, beside a coverage panel that quotes the one requirement no operation answers](images/walkthrough/04-process-draft.png)

Seven operations, in route order, each proposed by a **rule** rather than a
guess. Opening *"Why Cable connection ×2 was proposed"* shows the rule, the
requirement it answers (`connection.cable.count`) and the sentence behind it.

The coverage panel is the honest half. It reports **extracted-requirement
coverage** — not coverage of the document — and it quotes the requirement no
operation answers yet: *"The enclosure base and lid are moulded in ABS."* An
engineer either adds an operation, links an existing one, or records it as out
of scope. Until then the concept cannot be built.

---

## 5 · A concept with no numbers in it yet

![The concept screen showing the customer brief parsed into a 1,900 units per day target, 8 operators and a 30 by 18 metre floor, above a process flow whose cycle times, capacities and operator counts are all empty, with a bar reporting that 16 inputs are still needed](images/walkthrough/05-engineering-inputs.png)

The brief has been read — target, workforce, floor, and the customer's stated
preference to avoid new machines — and each value is labelled with where it
came from.

The engineering inputs are **empty**, and the bar says exactly how many are
missing. This is the state the product is designed to sit in: it will not
simulate a line whose cycle times nobody has supplied.

---

## 6 · What Fabrivium will supply, and what it refuses to

![The resolve engineering inputs panel, split into values Fabrivium computes — available production time, required takt, processing time, slowest stage — and values required to simulate, each tagged COMPUTED, ENGINEER or UNKNOWN](images/walkthrough/06-resolve-inputs.png)

> *"Fabrivium computes what it can compute and estimates what it can estimate.
> Anything that can only be known, measured or quoted is asked for — never
> invented."*

The panel separates three kinds of number and never blurs them:

| Tag | Meaning |
|---|---|
| **`COMPUTED`** | Derived, with the formula shown — available time is `shifts × hours × 3600`, takt is `available time ÷ daily target` |
| **`ENGINEER`** | A person supplied it; the target of 1,900/day and the eight operators came from the customer's brief |
| **`UNKNOWN`** | Nobody has supplied it. It stays unknown and blocks the run |

`REQUIRED TO SIMULATE` marks the values the simulator reads directly. Demo
values exist, but they are badged **DEMO ONLY** wherever they are offered.

---

## 7 · Verified, then improved

![The CEC-120 project after verification: a production goal of 1,900 units per day, a baseline concept delivering 1,435 with the bottleneck named as Cable connection ×2, and a recommended Plan B that reaches 1,900 with one extra shift, zero new machines and 18,000 euro per day of additional operating cost](assets/cec120-verified-result.png)

With the inputs supplied — including the engineer's override of Cable
connection ×2 to **40.0 s**, and `ASSISTED` automation on Screw fastening ×6 —
the concept simulates at **1,435 units/day** against a target of 1,900, and the
constraint is named.

Fabrivium then generates strategies and simulates each one: **23 deterministic
simulations across 3 strategies**. The recommended plan reaches **1,900/day**
with **one extra shift and no new machines**, because the limiting station
still has capacity the shift pattern was not using. The €18,000/day is the
engineer's own commercial figure — Fabrivium does not price money it was not
given.

Which inputs produced which figure: [CEC-120 case provenance](FABRIVIUM_CEC_CASE_PROVENANCE.md).

---

## 8 · Handed to Siemens

![Two stations of the generated model in the Tecnomatix Plant Simulation 2404 3D view, beside the read-back verification — 6 of 6 stations, 6 of 6 cycle times, 5 of 5 buffers, 13 of 13 positions, 12 of 12 flow connections — and the route walked in the reopened file from Source to Drain](images/fabrivium-siemens-handoff.png)

The agreed structure is written into **Tecnomatix Plant Simulation 2404**
through its own `RemoteControl` COM interface, then saved, closed, reopened and
verified out of the file that came back.

What transfers and what does not is stated rather than implied:
[handoff verification](SIEMENS_HANDOFF_VERIFICATION.md) ·
[cross-simulator semantics](CROSS_SIMULATOR_SEMANTICS.md).

---

## Reproducing the numbers without a browser

The same journey runs headless through the production HTTP API:

```bash
cd backend
python scripts/golden_journey_run.py
```

It uploads the specification PDF, drives the API end to end, and prints each
computed figure beside its expected counterpart. Every input the case needs
lives in one fixture,
[`examples/electronics/CEC-120_competition_case.json`](../examples/electronics/CEC-120_competition_case.json),
whose `expected_results` block is read **only after** a run.
