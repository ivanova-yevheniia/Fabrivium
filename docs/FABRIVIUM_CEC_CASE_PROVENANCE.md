# CEC-120 — which run produced which number

**Short answer: there is one CEC-120 product, one pipeline, and two
configurations of it.** The competition case is reproducible on demand and
was verified so on 2026-08-31. Nothing regressed.

This document exists because an internal report quoted a **1,196/day**
baseline next to the film's **1,435/day**, and a reviewer seeing both would
reasonably suspect the public case had drifted. It had not. The two numbers
are correct answers to two different questions, and the difference is
**exactly two engineer decisions**.

---

## The two configurations

| | **CEC-120 COMPETITION CASE** | **CEC-120 UNATTENDED BASELINE** |
|---|---|---|
| What it is | The engineering session in the submitted film | The pipeline run with no engineer in it |
| Question it answers | *What did this engineering session conclude?* | *What does the pipeline produce from the document alone?* |
| Public? | **Yes — this is the case study** | **No — internal regression evidence only** |
| Baseline | **1,435/day** | 1,196/day |
| Gap | **465/day** | 704/day |
| Bottleneck | **Cable connection ×2** (`m-assembly-2`) | Screw fastening ×6 (`m-screwdriving`) |
| Delivered | **1,900/day** | 1,900/day |
| Strategies | **3** | 4 |
| Simulations | **23** | 28 |
| Reproduce with | `python scripts/golden_journey_run.py` | The same script before 2026-08-31 |

Everything else is identical: the same PDF, the same seven operations in the
same order, the same 2 × 8 h schedule, the same 8 operators, the same five
of seven cycle times, the same code.

## Why they differ — the whole of it

Two engineer decisions that the film shows being made on camera, and that
the unattended run did not make:

| Station | Competition case | Unattended | Cause |
|---|---|---|---|
| Cable connection ×2 | **40.0 s** | 38.5 s | Engineer override of Fabrivium's estimate, typed on camera |
| Screw fastening ×6 | **39.8 s** | 48.0 s | Engineer selected **ASSISTED** automation; unattended defaulted to MANUAL |

The second is the one that moves everything. Six screws by hand price at
48.0 s; the same six on a driver on a balancer price at 39.8 s. At 48 s
screwdriving is the slowest station on the line, so it becomes the
constraint and the baseline falls. At 39.8 s it is not, and the constraint
sits where the film says it does — on the two cable connections at 40 s.

Both differences are **inputs**, both are recorded as engineer decisions
with stated reasons, and neither is a code path. No simulation logic, no
estimator band and no rule differs between the two runs.

## Verification, 2026-08-31

Both decisions live in **one public fixture**,
`examples/electronics/CEC-120_competition_case.json`, together with every
other input the case needs — the source document, the brief, the coverage
links and the station automation. `backend/scripts/golden_journey_run.py`
reads them from there and hard-codes none of them.

The fixture keeps the two sides of the reproduction strictly apart:

```
inputs            a document somebody wrote + decisions a person made
expected_results  read only AFTER a run, never fed back in
```

The script uploads the real
`Compact_Electronics_Controller_Product_Specification.pdf` through
`POST /product/upload` and drives the production HTTP API end to end, with
the language model off.

Result:

```
baseline          : 1435.0   (competition case 1435)
target            :   1900   (competition case 1900)
gap               :    465
bottleneck        : m-assembly-2
delivered         :   1900   (competition case 1900)
strategies        :      3   (competition case 3)
simulations       :     23   (competition case 23)
recommended       : Plan B — Run the line for longer (SHIFT_EXPANSION)
                    +1 shift/day, 0 machines added
```

Reproduced cycle times, against the manifest:

| Station | Manifest | Reproduced |
|---|---|---|
| PCB placement | 28.5 | 28.5 |
| Cable connection ×2 | 40.0 | **40.0** |
| Enclosure closure | 28.5 | 28.5 |
| Screw fastening ×6 | 39.8 | **39.8** |
| Product labelling | 19.0 | 19.0 |
| Visual inspection | 22.5 | 22.5 |
| Packaging | 29.0 | 29.0 |

**Every figure the film shows is reproduced from the source document
through the production API.** Verdict: **not a regression.** The earlier
1,196 was an incomplete reproduction, and it is now a fixed one.

## Sources of truth

| Artefact | Holds | Public? |
|---|---|---|
| **`examples/electronics/CEC-120_competition_case.json`** | **Every input needed to reproduce the case, plus a separated `expected_results` block. The one place these values are defined.** | **Yes** |
| `demo/recording/CEC120_CANONICAL_INPUT_MANIFEST.md` | The narrative record: station by station, what was typed and what was derived | No — with the footage |
| `demo/recording/golden_run_backup/c3c53435948d4b48.json` | The accepted Golden Run, SHA-256 `850d7377…3dcf` | No — with the footage |
| `backend/scripts/golden_journey_run.py` | The reproduction. Reads the fixture; defines nothing itself | Yes |

The fixture is the single source of truth for the *values*. The manifest
remains the source of truth for the *story* — what happened in what order in
front of the camera — and the fixture cites it.

## Rules for anyone quoting a CEC-120 number

1. **Public material uses the competition case only: 1,435 → 1,900/day, 23
   simulations, 3 strategies, 0 new machines, +1 shift, €18,000/day OPEX.**
2. Never call the unattended run "the canonical CEC case". It is the
   *unattended baseline*, and it exists to prove the pipeline runs without a
   human, not to describe the case study.
3. If a CEC number moves, check
   `examples/electronics/CEC-120_competition_case.json` before suspecting the
   engine. Every input that decides the figure is in that one file, and that
   is where it will be.

See also `docs/FABRIVIUM_CLAIM_MATRIX.md` §1.
