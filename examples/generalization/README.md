# Generalization cases

Five product specifications Fabrivium had never seen, plus the evidence
from running them through the real pipeline. Written for the generalization
validation phase; kept so the claim can be re-checked rather than believed.

| File | What it is |
|---|---|
| `PRE_REGISTRATION.md` | The cases, the exact briefs, and the predictions — **written before anything was run** |
| `case_a_lt8_gearbox_housing.txt` | Different product, different process (metal, bolts, leak test) |
| `case_b_ft9_filter_head.txt` | Deliberately incomplete engineering information |
| `case_c_gr7_guard_assembly.txt` | Constraint set that cannot meet the target |
| `PRE_REGISTRATION_D_E.md` | Predictions for D and E — **written before either was run** |
| `case_d_dx4_lateral_flow_cassette.txt` | Medical device: no fasteners, ultrasonic welding, 3 x 7.5 h |
| `case_e_bv2_bottled_beverage_line.txt` | Packaging: filling and capping have no family at all |
| `results/case_{cec,a,b,c,d,e}.json` | Every request and response, step by step. `cec` is the CEC-120 control run |
| `results/audit.json` | Provenance and leakage audit over all four |

## Re-running it

```bash
cd backend
python scripts/generalization_run.py            # all cases; ~20 min, LLM off
python scripts/generalization_run.py A          # one case
python scripts/generalization_audit.py          # provenance + leakage report
```

The run calls the production HTTP API through FastAPI's `TestClient`. It never
injects a simulation result, never reuses a CEC-120 fixture, and never calls
the example-data endpoints — those would fill a new product's stations from the
bundled electronics dataset, which is the leakage the audit tests for.

Findings and verdict, cases A-C: `docs/GENERALIZATION_VALIDATION_REPORT.md`.
Findings and verdict, cases D-E: `docs/FABRIVIUM_MULTI_DOMAIN_VALIDATION.md`
— three production defects, two fixed.
Code audit: `docs/GENERALIZATION_CODE_AUDIT.md`.
Regression tests: `backend/tests/test_generalization.py`.
