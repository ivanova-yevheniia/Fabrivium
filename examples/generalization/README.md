# Generalization evidence

This directory contains five pre-registered generalization cases (A-E), two
cross-domain end-to-end scenarios (M and P), and the recorded outputs used to
support Fabrivium's public generalization claims.

> **Naming note.** Fabrivium was named FactoryMind when cases A-C were
> pre-registered and first run. Their specifications, pre-registration and
> recorded outputs retain that historical name so the evidence is not rewritten
> after the fact.

## Source specifications and pre-registration

| File | Purpose |
|---|---|
| `PRE_REGISTRATION.md` | Predictions for cases A-C, written before those runs |
| `case_a_lt8_gearbox_housing.txt` | Metal gearbox housing with bolts and leak testing |
| `case_b_ft9_filter_head.txt` | Deliberately incomplete engineering information |
| `case_c_gr7_guard_assembly.txt` | An intentionally infeasible constraint set |
| `PRE_REGISTRATION_D_E.md` | Predictions for cases D-E, written before those runs |
| `case_d_dx4_lateral_flow_cassette.txt` | Medical device with ultrasonic welding and no fasteners |
| `case_e_bv2_bottled_beverage_line.txt` | Packaging line whose core filling and capping operations are outside current coverage |
| `scenario_m_ac6_compact_actuator.txt` | Mechanical cross-domain scenario driven to deterministic simulation |
| `scenario_p_lf3_liquid_fill_line.txt` | Packaging cross-domain scenario driven to deterministic simulation |

## Recorded outputs

| File | What it records |
|---|---|
| `results/case_{a,b,c,d,e}.json` | The five pre-registered generalization runs |
| `results/case_{m,p}.json` | The mechanical and packaging cross-domain runs |
| `results/case_cec.json` | The unattended CEC-120 control used by the leakage audit |
| `results/golden_cec120.json` | The separate competition golden journey; this is not the unattended control |
| `results/audit.json` | Generated provenance and leakage audit over every `case_*.json` result |

The result files contain the HTTP requests and responses recorded at each
pipeline stage. They are outputs, not fixtures: production code does not read
them. Re-running a case overwrites its corresponding result file.

Case D intentionally has no `final_draft`: unsupported welding data blocks the
concept build instead of being silently substituted. That incomplete result is
the expected fail-closed evidence, not a truncated file.

## Re-running the evidence

```bash
cd backend
python scripts/generalization_run.py       # all recorded cases; LLM off
python scripts/generalization_run.py M     # mechanical scenario only
python scripts/generalization_run.py P     # packaging scenario only
python scripts/generalization_run.py CEC   # unattended CEC control only
python scripts/generalization_audit.py     # regenerate results/audit.json
pytest -q tests/test_generalization.py tests/test_cross_domain_process.py
```

The harness calls the production HTTP API through FastAPI's `TestClient`. It
does not inject simulation results, reuse a CEC-120 fixture for non-CEC cases,
or call the example-data endpoints. No run requires an LLM credential.

## Scope of the evidence

- `case_m.json`: deterministic simulation reaches 420/420 units per day.
- `case_p.json`: deterministic simulation reaches 2,952/4,000 units per day,
  identifies `m-packaging` as the constraint, and records three options.
- Cases D and E document coverage limits in medical-device and
  continuous-motion packaging scenarios.
- Current audit: `docs/FABRIVIUM_GENERALIZATION_AUDIT.md`.
- Medical-device and packaging findings:
  `docs/FABRIVIUM_MULTI_DOMAIN_VALIDATION.md`.
- Public claim boundaries: `docs/FABRIVIUM_CLAIM_MATRIX.md`.

Do not describe these files as proof that Fabrivium works for any product.
They show that the same pipeline ran seven non-CEC specifications, including
partial and fail-closed outcomes whose limitations remain visible.
