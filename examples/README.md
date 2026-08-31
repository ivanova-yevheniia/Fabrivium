# Examples

Three product specifications, one per domain, in the form Fabrivium actually
reads: plain text a customer could have written.

| Directory | Product | What it exercises |
|---|---|---|
| `electronics/` | CEC-120 compact controller | The verified competition case study, plus `CEC-120_competition_case.json` — every input needed to reproduce it |
| `mechanical/` | AC-6 compact electromechanical actuator | Aluminium housing, pressed bearing, no PCB and no cables |
| `packaging/` | LF-3 consumer liquid filling line | Automatic line, no fasteners at all, supervisory operators |

`generalization/` holds five further cases and the **pre-registered
predictions** each was scored against, written before any of them was run.

## Using one

Paste the file's text into **Describe a product** on a new project, or run
the harness that drives the production HTTP API end to end:

```bash
cd backend
python scripts/generalization_run.py M      # mechanical
python scripts/generalization_run.py P      # packaging
python scripts/generalization_run.py CEC    # the control
python scripts/golden_journey_run.py        # the competition case, needs a live server
python scripts/generalization_audit.py      # provenance + leakage report
```

The language model is off for every one of these. Nothing here needs a
credential, and no result in this repository depends on a model being
reachable.

## What actually happened, per domain

Reported honestly, including where the routes are incomplete — the full
account is in [`docs/FABRIVIUM_MULTI_DOMAIN_VALIDATION.md`](../docs/FABRIVIUM_MULTI_DOMAIN_VALIDATION.md).

**Electronics (CEC-120)** — the verified case study. 1,435 → 1,900/day,
23 simulations, no new machines. `DEMO-VERIFIED`.

**Mechanical (AC-6)** — five operations proposed, engineering inputs
estimated, **deterministic simulation reached: 420/420 units/day, demand
met.** Also walked through the real browser UI at three resolutions.
The document also describes pressing a bearing and greasing a seat; there is
no rule for either, so those operations are **absent from the route** and
the concept is a partial model of the described line.

**Packaging (LF-3)** — three operations proposed, **deterministic simulation
reached: 2,952 against a 4,000/day target**, constraint identified at
packing, three improvement options generated of which two reach the target.
Filling and sealing have no process family, so they are **absent from the
route**. The operator counts for the automatic stations were supplied by an
engineer, because the estimator declines to assume operator demand on an
automated station.

## The recorded runs

`generalization/results/*.json` holds every request and response of every
case, step by step — 3.3 MB, tracked on purpose. They are what the
generalization and multi-domain reports cite, and a claim like "the filling
line reached 2,952/day" is worth exactly as much as the run behind it being
readable.

They are outputs, not inputs: nothing in the pipeline reads them, and
re-running a case overwrites its file. If a number in a report and a number
in these files ever disagree, the files are the record of what actually
happened and the report is wrong.
