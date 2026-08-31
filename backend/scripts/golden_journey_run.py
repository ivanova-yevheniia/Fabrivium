"""The golden CEC-120 journey, driven against the LIVE backend over HTTP."""

from __future__ import annotations

import json
import pathlib
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "examples" / "generalization" / "results" / "golden_cec120.json"

# THE ONE DEFINITION OF THE COMPETITION CASE.
CASE_FILE = ROOT / "examples" / "electronics" / "CEC-120_competition_case.json"
CASE = json.loads(CASE_FILE.read_text(encoding="utf-8"))
INPUTS = CASE["inputs"]


def _values(mapping: dict) -> dict:
    """Drop the fixture's `_`-prefixed explanatory keys."""
    return {k: v for k, v in mapping.items() if not k.startswith("_")}


PDF = ROOT / INPUTS["source_document"]

# The customer's own words.
BRIEF = INPUTS["production_requirements_brief"]
REQUEST = INPUTS["improvement_request"]
PRODUCT_NAME = INPUTS["product_name"]

# Which operation an engineer says answers a requirement the rule table has no rule for.
LINKS: dict[str, str] = _values(INPUTS["coverage_links"])

# Automation level per station, as the engineer described it to the estimator.
STATION_AUTOMATION: dict[str, str] = _values(INPUTS["station_automation"])

# What the film shows a person typing, in order.
ENGINEER_DECISIONS = INPUTS["engineer_decisions"]

#: For comparison in the printout only — never asserted, never restored, and
#: never fed back into the pipeline. A script that failed when the number
#: moved would be a script that tempts someone to move it back.
EXPECTED = CASE["expected_results"]
COMPETITION_CASE = {
    "baseline": EXPECTED["baseline_units_per_day"],
    "target": EXPECTED["target_units_per_day"],
    "delivered": EXPECTED["delivered_units_per_day"],
    "capacity": EXPECTED["modeled_capacity_units_per_day"],
    "simulations": EXPECTED["simulations_run"],
    "strategies": EXPECTED["strategies_retained"],
}
HISTORICAL = COMPETITION_CASE  # the name the printout below uses


def call(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode()[:400]
        raise SystemExit(f"{path} -> HTTP {error.code}: {detail}")


def upload_pdf() -> dict:
    """`POST /product/upload` as multipart, hand-rolled to avoid a dependency."""
    boundary = "----factorymind-golden-run"
    body = b""
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="file"; filename="{PDF.name}"\r\n'.encode()
    body += b"Content-Type: application/pdf\r\n\r\n"
    body += PDF.read_bytes()
    body += f"\r\n--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="product_name"\r\n\r\n'
    body += PRODUCT_NAME.encode() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    request = urllib.request.Request(
        BASE + "/product/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read())


def heading(text: str) -> None:
    print()
    print("=" * 74)
    print(text)
    print("=" * 74)


def main() -> int:
    if not PDF.exists():
        raise SystemExit(f"The controlled customer document is missing: {PDF}")

    log: dict = {"source_document": PDF.name, "steps": {}}

    # 1. the product
    heading("1. PRODUCT — the customer's PDF")
    uploaded = upload_pdf()
    understanding = uploaded["understanding"]
    log["steps"]["upload"] = uploaded
    print(f"document        : {PDF.name}")
    print(f"interpretation  : {understanding['interpretation_method']}")
    print(f"model used      : {uploaded.get('model_used')}")
    print(f"facts extracted : {len(understanding['facts'])}")
    for fact in understanding["facts"]:
        evidence = fact["evidence"][0] if fact["evidence"] else None
        where = f"p{evidence['page']}" if evidence and evidence.get("page") else "—"
        print(f"   {fact['key']:<28} {str(fact['value']):<14} {fact['status']:<10} {where}")
    print(f"information gaps: {len(understanding['information_gaps'])}")
    for gap in understanding["information_gaps"]:
        print(f"   {gap['label']} [{gap['severity']}]")
    unresolved = understanding.get("unresolved_statements", [])
    print(f"unresolved source statements: {len(unresolved)}")
    for statement in unresolved:
        print(f"   \"{statement['statement']}\"")

    # 2. proposed process
    heading("2. PROCESS — proposed from the facts, not from a template")
    planned = call("/product/plan-process", {"understanding": understanding})
    draft = planned["draft"]
    log["steps"]["plan_process"] = planned
    for operation in draft["operations"]:
        repeats = operation.get("repeated_operations")
        print(f"   {operation['name']:<24} {operation['process_type']:<14} "
              f"repeats={repeats} from={operation['source_fact_keys']}")
    for question in draft.get("open_questions", []):
        print(f"   ? {question}")

    coverage = call(
        "/product/requirement-coverage", {"understanding": understanding, "draft": draft}
    )
    log["steps"]["coverage"] = coverage
    print("\n   requirement coverage:")
    for item in coverage["items"]:
        print(f"      {item['status']:<18} {item['severity']:<14} {item['fact_key']} "
              f"-> {item['addressed_by']}")

    # 3.
    heading("3. ENGINEER REVIEW — unanswered requirements linked by a person")
    for fact_key, operation_name in LINKS.items():
        operation = next(o for o in draft["operations"] if o["name"].startswith(operation_name))
        linked = call(
            "/product/process/link-requirement",
            {
                "understanding": understanding,
                "draft": draft,
                "operation_id": operation["id"],
                "fact_keys": [fact_key],
            },
        )
        draft = linked["draft"]
        print(f"   ENGINEER links {fact_key:<22} -> {operation['name']}")

    recheck = call(
        "/product/requirement-coverage", {"understanding": understanding, "draft": draft}
    )
    log["steps"]["coverage_after_review"] = recheck
    still_open = [i for i in recheck["items"] if i["status"] == "UNRESOLVED"]
    print(f"   unresolved requirements after review: {len(still_open)}")

    draft = {
        **draft,
        "operations": [
            {**op, "status": "ACCEPTED", "fact_status": "ENGINEER_VERIFIED"}
            for op in draft["operations"]
        ],
    }
    print("   every operation accepted explicitly by the engineer")

    built = call(
        "/product/build-concept",
        {
            "understanding": understanding,
            "process": draft,
            "requirements_brief": BRIEF,
            "name": "Compact Electronics Controller (CEC-120)",
        },
    )
    concept = built["draft"]
    log["steps"]["build_concept"] = built
    print(f"   stages     : {[s['name'] for s in concept['stages']]}")
    for field in ("production_target", "operators_available", "floor_width", "floor_length",
                  "shifts_per_day", "hours_per_shift", "budget", "prefer_no_new_machines"):
        print(f"   {field:<22}: {json.dumps(concept.get(field))}")

    # 4. what is still unknown
    heading("4. ENGINEERING INPUTS — what the document cannot decide")
    plan = call("/concept/resolution-plan", {"draft": concept})
    log["steps"]["resolution_plan_initial"] = plan
    for row in plan["inputs"]:
        if not row["resolved"]:
            print(f"   UNRESOLVED  {row['key']:<34} {row['label']}")
    print(f"   ready to simulate: {plan['ready_to_simulate']}")

    readiness = call("/concept/readiness", {"draft": concept})
    log["steps"]["readiness_initial"] = readiness
    print(f"   provenance : {json.dumps(readiness['counts'])}")

    # 5.
    heading("5. ESTIMATES — proposed, with method, range and confidence")
    station_context = built.get("station_context") or {}
    for stage in concept["stages"]:
        context = station_context.get(stage["id"], {})
        proposal_out = call(
            "/concept/estimate",
            {
                "draft": concept,
                "stage_id": stage["id"],
                "description": context.get("estimator_description") or stage["name"],
                "automation_level": STATION_AUTOMATION.get(stage["id"], "MANUAL"),
                "operations_per_unit": context.get("repeated_operations"),
            },
        )
        proposal = proposal_out.get("proposal")
        if not proposal:
            # A refusal is a result.
            needs = proposal_out.get("needs_information") or {}
            print(f"   {stage['name']:<20} NO ESTIMATE — {needs.get('reason')}")
            for question in needs.get("questions", []):
                print(f"                        ? {question}")
            continue

        cycle = proposal.get("cycle_time")
        if cycle:
            print(f"   {stage['name']:<20} {cycle['working_value']:>6.1f} s  "
                  f"[{cycle['low']:g}–{cycle['high']:g}]  {cycle['confidence']:<7} {cycle['method']}")
        accepted = [f for f in ("cycle_time", "capacity", "operators") if proposal.get(f) is not None]
        if not accepted:
            continue
        applied = call(
            "/concept/accept-assumptions",
            {"draft": concept, "proposal": proposal, "accepted_fields": accepted},
        )
        concept = applied["draft"]
        print(f"   {'':<20} accepted: {accepted}")
    log["steps"]["after_estimates"] = concept

    # 5b.
    heading("5b. ENGINEER DECISIONS — typed, and recorded as ENGINEER")
    for decision in ENGINEER_DECISIONS:
        key, value, detail = decision["key"], decision["value"], decision["reason"]
        out = call(
            "/concept/resolve-input",
            {"draft": concept, "key": key, "value": value, "source": "ENGINEER", "detail": detail},
        )
        concept = out["draft"]
        print(f"   ENGINEER  {key:<24} = {value:<6} — {detail}")

    plan = call("/concept/resolution-plan", {"draft": concept})
    log["steps"]["resolution_plan_final"] = plan
    print(f"   ready to simulate: {plan['ready_to_simulate']}")
    readiness = call("/concept/readiness", {"draft": concept})
    log["steps"]["readiness_final"] = readiness
    print(f"   provenance : {json.dumps(readiness['counts'])}")
    print(f"   verdict    : {readiness['verdict']}")

    # 6. build and simulate
    heading("6. CONCEPT — built and simulated")
    build = call("/concept/build", {"draft": concept})
    log["steps"]["build"] = build
    factory = build["factory"]
    print(f"   machines: {[m['name'] for m in factory['machines']]}")

    product_id = build["product_id"]
    simulation = call("/simulation/run", {"factory": factory, "product_id": product_id})
    log["steps"]["simulation"] = simulation
    baseline = simulation["demand_per_day"] - simulation["demand_gap_units"]
    system = simulation["system"]
    print(f"   demand/day          : {simulation['demand_per_day']}")
    print(f"   BASELINE THROUGHPUT : {baseline} units/day "
          f"(gap {simulation['demand_gap_units']}, met={simulation['demand_met']})")
    print(f"   throughput/hour     : {simulation['throughput_per_hour']}")
    print(f"   BOTTLENECK          : {system.get('bottleneck_machine_id') or system.get('bottleneck')}")
    print(f"   system              : {json.dumps(system)[:500]}")

    # 7. alternatives
    heading("7. ALTERNATIVES — searched and simulated, not guessed")
    planning = call(
        "/planning/run",
        {"factory": factory, "product_id": product_id, "user_request": REQUEST},
    )
    log["steps"]["planning"] = planning
    print(f"   parser        : {planning['parse_result']['parser_type']}")
    print(f"   parsed target : {planning['parse_result']['parsed_requirements']['target_units_per_day']}")
    print(f"   no new machines requested: "
          f"{planning['parse_result']['parsed_requirements']['prefer_no_new_machines']}")

    session = planning["session"]
    baseline_sim = session["baseline_simulation"]
    final_sim = session["current_simulation"]
    hours = concept["shifts_per_day"]["value"] * concept["hours_per_shift"]["value"]
    delivered = round(final_sim["throughput_per_hour"] * hours)
    print(f"   goal reached  : {session['goal_reached']}  ({session['stop_reason']})")
    print(f"   iterations    : {len(session['iterations'])}")
    print(f"   delivered     : {delivered} units/day (gap {final_sim['demand_gap_units']})")

    # 8.
    heading("8. STRATEGY ARENA — every option simulated, capacity measured")
    explored = call(
        "/strategies/explore",
        {"factory": factory, "product_id": product_id, "user_request": REQUEST},
    )
    arena = explored["arena"]
    log["steps"]["strategies"] = {k: v for k, v in explored.items() if k != "sessions"}

    stats = arena["stats"]
    strategies = arena["strategies"]
    print(f"   families attempted  : {stats['families_attempted']}")
    print(f"   strategies retained : {stats['strategies_retained']} "
          f"(discarded {stats['strategies_discarded']})")
    print(f"   SIMULATIONS RUN     : {stats['simulations_run']}")
    print(f"   families with no option: {arena['families_without_options']}")
    print(f"   summary             : {arena['summary']}")
    print()
    for entry in strategies:
        m = entry["metrics"]
        print(f"   {entry['label']:<7} {entry['title'][:36]:<36} "
              f"reaches={str(m['goal_met']):<5} delivered={m['completed_units']:<5} "
              f"capacity={str(m['capacity_units_per_day']):<6} "
              f"headroom={str(m['capacity_headroom_percent']):<5} "
              f"priced={entry['commercially_complete']}")

    recommended = next(
        (e for e in strategies if e["strategy_id"] == arena["recommended_strategy_id"]), None
    )
    if recommended is not None:
        m = recommended["metrics"]
        print()
        print(f"   RECOMMENDED       : {recommended['label']} — {recommended['title']}")
        print(f"   delivered         : {m['completed_units']} units/day")
        print(f"   MODELED CAPACITY  : {m['capacity_units_per_day']} units/day")
        print(f"   CAPACITY HEADROOM : {m['capacity_headroom_percent']}%")
        print(f"   sustains target at capacity: {m['sustains_target_at_capacity']}")
        print(f"   new bottleneck    : {m['bottleneck_machine_id']}")
        print(f"   commercially complete: {recommended['commercially_complete']}")
        for warning in recommended["warnings"]:
            print(f"   warning           : {warning}")
        for tradeoff in recommended["tradeoffs"]:
            print(f"   tradeoff          : {tradeoff}")
        log["recommended"] = recommended

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(log, indent=2, default=str), encoding="utf-8")

    heading("SUMMARY — the golden CEC-120 numbers, measured now")
    target = concept["production_target"]["value"]
    m = (recommended or {}).get("metrics", {})
    print(f"   source document   : {PDF.name}")
    print(f"   baseline          : {baseline:>6}   (competition case {HISTORICAL['baseline']})")
    print(f"   target            : {target:>6.0f}   (competition case {HISTORICAL['target']})")
    print(f"   gap               : {target - baseline:>6.0f}")
    print(f"   bottleneck        : {system.get('bottleneck_machine_id')}")
    print(f"   delivered         : {m.get('completed_units', '—'):>6}   "
          f"(competition case {HISTORICAL['delivered']})")
    print(f"   modeled capacity  : {m.get('capacity_units_per_day', '—'):>6}   "
          f"(competition case {HISTORICAL['capacity']})")
    print(f"   capacity headroom : {m.get('capacity_headroom_percent', '—')}%")
    print(f"   strategies        : {stats['strategies_retained']}   "
          f"(competition case {HISTORICAL['strategies']})")
    print(f"   simulations       : {stats['simulations_run']}   "
          f"(competition case {HISTORICAL['simulations']})")
    print()
    print("   The competition-case figures are for comparison only. Every figure above")
    print("   came out of this run; none was preserved, restored or tuned toward.")
    print()
    print(f"   full log written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
