"""Run three independent product cases through the REAL FactoryMind pipeline."""

from __future__ import annotations

import json
import os
import pathlib
import sys

os.environ["FACTORYMIND_LLM_ENABLED"] = "false"

BACKEND = pathlib.Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

CASES_DIR = ROOT / "examples" / "generalization"
RESULTS_DIR = CASES_DIR / "results"

# Engineer inputs, stated up front.
CASES: dict[str, dict] = {
    # THE CONTROL.
    "CEC": {
        "document": None,
        "document_path": BACKEND / "app" / "data" / "electronics_controller_reference_product.txt",
        "product_name": "Compact Electronics Controller (CEC-120)",
        "requirements_brief": (
            "We need a new electronics assembly line. The product goes through assembly, "
            "screwdriving, inspection and packaging. We need about 1,900 units per day. "
            "The available production area is 30 by 18 meters. We have eight operators. "
            "We would prefer not to buy unnecessary equipment."
        ),
        "user_request": "We need 1900 units/day. Avoid buying new machines if possible.",
        "automation_level": "MANUAL",
        "link_requirements": {
            "component.enclosure": "first",
            "component.label": "packaging",
        },
        "engineer_resolutions": [
            ("shifts_per_day", 2, "ENGINEER", "Not stated in the brief; the demo line runs two shifts."),
            ("hours_per_shift", 8, "ENGINEER", "Not stated in the brief; the demo line runs 8-hour shifts."),
        ],
    },
    "A": {
        "document": "case_a_lt8_gearbox_housing.txt",
        "product_name": "LT-8 Gearbox Housing Assembly",
        "requirements_brief": (
            "We build the LT-8 for a conveyor manufacturer. We need 900 units per day "
            "from a single cell. We run two 8-hour shifts and have six operators "
            "available for this cell. The available floor area is 22 by 14 meters. "
            "A budget for one additional station has been approved if it is needed."
        ),
        "user_request": (
            "Reach 900 units per day for the LT-8 cell. A budget for one additional "
            "station has been approved if it is needed."
        ),
        "automation_level": "MANUAL",
        # Engineering resolution of coverage gaps: which accepted operation the
        # engineer says already answers a requirement the rule table did not link.
        "link_requirements": {
            "component.enclosure": "first",
            "component.label": "packaging",
        },
        "engineer_resolutions": [],
    },
    "B": {
        "document": "case_b_ft9_filter_head.txt",
        "product_name": "FT-9 In-Line Filter Head Assembly",
        "requirements_brief": (
            "We plan to make the FT-9 on a new manual cell. The customer forecast is "
            "600 units per day. The shift pattern and the staffing for this cell have "
            "not been agreed yet, and the cell footprint has not been allocated."
        ),
        "user_request": "Reach 600 units per day for the FT-9 cell.",
        "automation_level": "MANUAL",
        "link_requirements": {
            "component.enclosure": "first",
            "component.label": "packaging",
        },
        # The brief states none of these.
        "engineer_resolutions": [
            ("shifts_per_day", 1, "ENGINEER", "Working assumption for the concept study; not agreed with the customer."),
            ("hours_per_shift", 8, "ENGINEER", "Working assumption for the concept study; not agreed with the customer."),
            ("operators_available", 4, "ENGINEER", "Working assumption for the concept study; not agreed with the customer."),
        ],
    },
    "C": {
        "document": "case_c_gr7_guard_assembly.txt",
        "product_name": "GR-7 Bench Grinder Guard Assembly",
        "requirements_brief": (
            "We need 6,000 units per day of the GR-7 from one cell. We run one 8-hour "
            "shift and have four operators. Do not buy any new machines and do not add "
            "any new machines. There is no capital budget this year. The floor area is "
            "24 by 12 meters."
        ),
        "user_request": (
            "We need 6,000 units per day of the GR-7 from one cell. We run one 8-hour "
            "shift and have four operators. Do not buy any new machines and do not add "
            "any new machines. There is no capital budget this year. No second shift is "
            "available and we cannot hire additional operators."
        ),
        "automation_level": "MANUAL",
        "link_requirements": {
            "component.enclosure": "first",
            "component.label": "packaging",
        },
        "engineer_resolutions": [],
    },
    # D and E: the two domains the product generalization brief names
    #
    # A, B and C are all discrete mechanical/industrial products, so medical
    # device and packaging were untested. Predictions for both were written
    # BEFORE either was run — see PRE_REGISTRATION_D_E.md, which is what the
    # report is scored against.
    "D": {
        "document": "case_d_dx4_lateral_flow_cassette.txt",
        "product_name": "DX-4 Single-Use Diagnostic Cassette",
        "requirements_brief": (
            "We need 4,000 cassettes per day across 3 shifts of 7.5 hours. Six "
            "operators are available. The available floor area is 22 by 14 meters. "
            "No capital budget has been set."
        ),
        "user_request": "Reach 4,000 cassettes per day for the DX-4 line.",
        "automation_level": "MANUAL",
        # Deliberately EMPTY.
        "link_requirements": {},
        "engineer_resolutions": [],
    },
    "E": {
        "document": "case_e_bv2_bottled_beverage_line.txt",
        "product_name": "BV-2 Bottled Beverage",
        "requirements_brief": (
            "We need 18,000 bottles per day across 2 shifts of 8 hours. Four "
            "operators supervise the line. The available floor area is 45 by 20 "
            "meters. The monobloc has not been selected and no equipment cost is "
            "available."
        ),
        "user_request": "Reach 18,000 bottles per day on the BV-2 line.",
        # AUTOMATIC, because the document says the line is substantially
        # automated and the operators supervise rather than handle each unit.
        # This is the first case that is not MANUAL.
        "automation_level": "AUTOMATIC",
        "link_requirements": {},
        "engineer_resolutions": [],
    },
    # M and P: the two scenarios the final sprint requires Unlike D and E, these are
    # driven all the way to a deterministic simulation.
    "M": {
        "document": "scenario_m_ac6_compact_actuator.txt",
        "product_name": "AC-6 Compact Electromechanical Actuator",
        "requirements_brief": (
            "We need 420 units per day on 1 shift of 8 hours. 5 operators are "
            "available. No equipment has been selected and no equipment price is "
            "available."
        ),
        "user_request": "Reach 420 units per day for the AC-6 line.",
        "automation_level": "MANUAL",
        "link_requirements": {
            "component.enclosure": "first",
            "component.label": "packaging",
        },
        "engineer_resolutions": [],
    },
    "P": {
        "document": "scenario_p_lf3_liquid_fill_line.txt",
        "product_name": "LF-3 Consumer Liquid Product",
        "requirements_brief": (
            "We need 4,000 units per day across 2 shifts of 8 hours. 6 operators "
            "are available. Filling, sealing and labelling are automatic; the "
            "operators supervise the line."
        ),
        "user_request": "Reach 4,000 units per day on the LF-3 line.",
        # The line really is automated, and the estimator correctly refuses to
        # guess an automated station's operator demand — an unattended
        # assumption would silently free an operator the line may need. So the
        # operator counts below are ENGINEER decisions, which is exactly the
        # human-in-the-loop step this stage exists for.
        "automation_level": "AUTOMATIC",
        "link_requirements": {
            "component.enclosure": "first",
            "component.label": "packaging",
        },
        # The ONLY values a person supplies on this case, and each is a real engineering
        # decision the estimator declines to make for a reason it states:
        "engineer_resolutions": [
            ("stage.m-labelling.operators_required", 1, "ENGINEER",
             "Automatic labeller; the document says operators supervise the line, so one "
             "supervising operator is attributed to this station."),
            ("stage.m-inspection.operators_required", 1, "ENGINEER",
             "Automatic inspection; one supervising operator attributed, per the document."),
            ("stage.m-packaging.operators_required", 1, "ENGINEER",
             "Carton packing is not described as automatic, so one operator is attributed."),
        ],
    },
}


def post(client: TestClient, path: str, payload: dict) -> tuple[int, dict]:
    response = client.post(path, json=payload)
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - a non-JSON body is itself the finding
        body = {"_raw": response.text}
    return response.status_code, body


def pick_operation(draft: dict, rule: str) -> str | None:
    """Which operation the engineer links a requirement to."""
    operations = draft.get("operations", [])
    if not operations:
        return None
    if rule == "packaging":
        for op in operations:
            if op["process_type"] == "packaging":
                return op["id"]
        return operations[-1]["id"]
    return operations[0]["id"]


def run_case(client: TestClient, case_id: str, spec: dict) -> dict:
    log: dict = {"case": case_id, "product_name": spec["product_name"], "steps": {}}
    source = spec.get("document_path") or (CASES_DIR / spec["document"])
    text = pathlib.Path(source).read_text(encoding="utf-8")

    # 1. product understanding
    status, body = post(
        client,
        "/product/describe",
        {"description": text, "product_name": spec["product_name"], "mode": "LOCAL_ONLY"},
    )
    log["steps"]["describe"] = {"status": status, "body": body}
    if status != 200:
        return log
    understanding = body["understanding"]

    # 2. process proposal
    status, body = post(client, "/product/plan-process", {"understanding": understanding})
    log["steps"]["plan_process"] = {"status": status, "body": body}
    if status != 200:
        return log
    process = body["draft"]

    # 3. requirement coverage, as proposed
    status, body = post(
        client,
        "/product/requirement-coverage",
        {"understanding": understanding, "draft": process},
    )
    log["steps"]["coverage_before_review"] = {"status": status, "body": body}

    # 4. engineering resolution of coverage gaps
    links = []
    for item in body.get("items", []):
        if item["status"] != "UNRESOLVED":
            continue
        rule = spec["link_requirements"].get(item["fact_key"])
        if rule is None:
            links.append({"fact_key": item["fact_key"], "action": "LEFT UNRESOLVED"})
            continue
        operation_id = pick_operation(process, rule)
        status, linked = post(
            client,
            "/product/process/link-requirement",
            {
                "understanding": understanding,
                "draft": process,
                "operation_id": operation_id,
                "fact_keys": [item["fact_key"]],
            },
        )
        links.append(
            {"fact_key": item["fact_key"], "operation_id": operation_id, "status": status}
        )
        if status == 200:
            process = linked["draft"]
    log["steps"]["requirement_links"] = links

    # 5. the engineer accepts every proposed operation
    process = {
        **process,
        "operations": [
            {**op, "status": "ACCEPTED", "fact_status": "ENGINEER_VERIFIED"}
            for op in process["operations"]
        ],
    }

    status, body = post(
        client,
        "/product/requirement-coverage",
        {"understanding": understanding, "draft": process},
    )
    log["steps"]["coverage_after_review"] = {"status": status, "body": body}

    # 6. concept from the accepted process
    status, body = post(
        client,
        "/product/build-concept",
        {
            "understanding": understanding,
            "process": process,
            "requirements_brief": spec["requirements_brief"],
            "name": spec["product_name"],
        },
    )
    log["steps"]["build_concept"] = {"status": status, "body": body}
    if status != 200:
        return log
    draft = body["draft"]
    station_context = body["station_context"]

    # 7. readiness and resolution plan, before any value is written
    for name, path in (("readiness_before", "/concept/readiness"), ("plan_before", "/concept/resolution-plan")):
        status, out = post(client, path, {"draft": draft})
        log["steps"][name] = {"status": status, "body": out}

    # 8. Phase 18B estimates, station by station
    estimates = []
    for stage in draft["stages"]:
        context = station_context.get(stage["id"], {})
        description = context.get("estimator_description") or stage["name"]
        status, out = post(
            client,
            "/concept/estimate",
            {
                "draft": draft,
                "stage_id": stage["id"],
                "description": description,
                "automation_level": spec["automation_level"],
                "operations_per_unit": context.get("repeated_operations"),
                "mode": "LOCAL_ONLY",
            },
        )
        record = {"stage_id": stage["id"], "description": description, "status": status, "body": out}
        estimates.append(record)
        if status != 200 or not out.get("proposal"):
            continue

        proposal = out["proposal"]
        accepted = [
            field
            for field in ("cycle_time", "capacity", "operators")
            if proposal.get(field) is not None
        ]
        if not accepted:
            continue
        status, applied = post(
            client,
            "/concept/accept-assumptions",
            {"draft": draft, "proposal": proposal, "accepted_fields": accepted},
        )
        record["accepted_fields"] = accepted
        record["accept_status"] = status
        if status == 200:
            draft = applied["draft"]
            record["applied"] = applied["applied"]
    log["steps"]["estimates"] = estimates

    # 9. state after estimation, before any engineer decision
    for name, path in (
        ("readiness_after_estimates", "/concept/readiness"),
        ("plan_after_estimates", "/concept/resolution-plan"),
        ("validation_after_estimates", "/concept/validate"),
    ):
        status, out = post(client, path, {"draft": draft})
        log["steps"][name] = {"status": status, "body": out}

    # A build attempt at exactly this point: does FactoryMind refuse while a
    # required value is still unknown, or does it fill one in?
    status, out = post(client, "/concept/build", {"draft": draft})
    log["steps"]["build_attempt_before_engineer_input"] = {"status": status, "body": out}

    # 10. engineer decisions, explicitly listed
    resolutions = []
    for key, value, source, detail in spec["engineer_resolutions"]:
        status, out = post(
            client,
            "/concept/resolve-input",
            {"draft": draft, "key": key, "value": value, "source": source, "detail": detail},
        )
        resolutions.append({"key": key, "value": value, "source": source, "status": status})
        if status == 200:
            draft = out["draft"]
    log["steps"]["engineer_resolutions"] = resolutions

    for name, path in (("readiness_final", "/concept/readiness"), ("plan_final", "/concept/resolution-plan")):
        status, out = post(client, path, {"draft": draft})
        log["steps"][name] = {"status": status, "body": out}

    log["final_draft"] = draft

    # 11. build, simulate
    status, out = post(client, "/concept/build", {"draft": draft})
    log["steps"]["build"] = {"status": status, "body": out}
    if status != 200:
        return log
    factory = out["factory"]
    product_id = out["product_id"]
    layout = out["layout"]

    status, out = post(
        client, "/simulation/run", {"factory": factory, "product_id": product_id}
    )
    log["steps"]["simulation"] = {"status": status, "body": out}

    # 12. strategy exploration: alternatives, ranking, recommendation
    status, out = post(
        client,
        "/strategies/explore",
        {
            "factory": factory,
            "product_id": product_id,
            "user_request": spec["user_request"],
            "layout": layout,
        },
    )
    # The verified sessions are large and are not needed for the audit; the
    # arena result carries every strategy, its metrics and its status.
    if status == 200 and isinstance(out, dict):
        out.pop("sessions", None)
    log["steps"]["strategies"] = {"status": status, "body": out}

    # 13. planning run: recommendation / no-feasible-plan
    status, out = post(
        client,
        "/planning/run",
        {
            "factory": factory,
            "product_id": product_id,
            "user_request": spec["user_request"],
            "layout": layout,
        },
    )
    log["steps"]["planning"] = {"status": status, "body": out}

    return log


def main() -> int:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    client = TestClient(app)
    only = sys.argv[1:] or list(CASES)
    for case_id in only:
        spec = CASES[case_id]
        print(f"--- case {case_id}: {spec['product_name']}")
        log = run_case(client, case_id, spec)
        path = RESULTS_DIR / f"case_{case_id.lower()}.json"
        path.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"    written {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
