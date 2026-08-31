import type {
  BranchComparison,
  BranchMetrics,
  ConversationSession,
  ConversationTurn,
  ConversationTurnResponse,
  Factory,
  Machine,
  PlanningBranch,
  PlanningExplanation,
  PlanningIteration,
  PlanningRequirements,
  PlanningSessionState,
  PlanningStateSnapshot,
  SimulationResult,
  InformationGap,
  StrategyActionSummary,
  StrategyArenaResult,
  StrategyComparison,
  StrategyMetrics,
  StrategyQueryAnswer,
  VerifiedStrategyOption,
} from "../api/types";

export const sampleFactory: Factory = {
  name: "Test Line",
  width: 20,
  length: 10,
  shifts_per_day: 1,
  hours_per_shift: 8,
  operators_available: 5,
  budget: 500_000,
  machines: [
    {
      id: "m-a",
      name: "Machine A",
      process_type: "assembly",
      cycle_time: 30,
      setup_time: 0,
      capacity: 1,
      operators_required: 1,
      purchase_cost: 50_000,
      position_x: 0,
      position_y: 0,
      width: 2,
      length: 2,
      parallel_of_machine_id: null,
      asset: null,
      lifecycle_status: "EXISTING",
      physical_envelope: null,
    },
    {
      id: "m-b",
      name: "Machine B",
      process_type: "packaging",
      cycle_time: 20,
      setup_time: 0,
      capacity: 1,
      operators_required: 1,
      purchase_cost: 30_000,
      position_x: 3,
      position_y: 0,
      width: 2,
      length: 2,
      parallel_of_machine_id: null,
      asset: null,
      lifecycle_status: "EXISTING",
      physical_envelope: null,
    },
  ],
  products: [
    {
      id: "p-1",
      name: "Widget",
      demand_per_day: 500,
      route: [
        { name: "Assembly", machine_id: "m-a", cycle_time: 30 },
        { name: "Packaging", machine_id: "m-b", cycle_time: 20 },
      ],
    },
  ],
  buffers: [],
};

/** A clone added to sampleFactory — mirrors what apply_scenario/
 * ADD_PARALLEL_MACHINE actually produces, for a realistic "after" snapshot. */
function withClone(factory: Factory, cloneId: string, sourceMachineId: string): Factory {
  const source = factory.machines.find((m) => m.id === sourceMachineId) as Machine;
  const clone: Machine = { ...source, id: cloneId, parallel_of_machine_id: sourceMachineId };
  return { ...factory, machines: [...factory.machines, clone] };
}

export const sampleFactoryAfterIteration1 = withClone(sampleFactory, "m-a-parallel-1", "m-a");

function simulation(overrides: Partial<SimulationResult>): SimulationResult {
  return {
    simulation_time_seconds: 57600,
    target_units: 500,
    completed_units: 500,
    throughput_per_hour: 20,
    demand_per_day: 500,
    demand_met: true,
    demand_gap_units: 0,
    machine_kpis: [],
    system: {
      average_flow_time_seconds: 60,
      max_flow_time_seconds: 90,
      work_in_progress: 2,
      bottleneck_machine_id: "m-a",
    },
    process_pool_kpis: [],
    // Phase 8A: an unconstrained workforce and a quiet buffer, so a fixture
    // only shows a constraint when a test deliberately sets one.
    operator_kpi: {
      operators_available: 4,
      operators_required_peak: 2,
      peak_operators_in_use: 2,
      average_operators_in_use: 1.2,
      utilization: 0.3,
      total_operator_wait_seconds: 0,
      average_operator_wait_seconds: 0,
      max_operator_wait_seconds: 0,
      operations_delayed_by_operators: 0,
      operator_constrained: false,
    },
    buffer_kpis: [
      {
        buffer_id: "buf-1",
        buffer_name: "Pre-B Buffer",
        capacity: 20,
        upstream_machine_id: "m-a",
        downstream_machine_id: "m-b",
        average_level: 3.5,
        max_level: 8,
        utilization: 0.175,
        time_full_seconds: 0,
        time_empty_seconds: 100,
        full_fraction: 0,
        empty_fraction: 0.2,
        upstream_blocked_seconds: 0,
        upstream_blocked_events: 0,
        blocking_observed: false,
      },
    ],
    ...overrides,
  };
}

function snapshot(overrides: Partial<PlanningStateSnapshot> & { simulation: SimulationResult }): PlanningStateSnapshot {
  return {
    factory: sampleFactory,
    layout: null,
    bottleneck_machine_id: overrides.simulation.system.bottleneck_machine_id,
    cumulative_known_capex: 0,
    // Defaults to "no budget constraint", matching a session whose
    // requirements set no max_capex. A budgeted fixture passes the real
    // per-stage figure — see sampleSessionBudgeted.
    remaining_known_capex: null,
    ...overrides,
  };
}

export const sampleRequirements: PlanningRequirements = {
  objective: "MEET_DEMAND",
  target_units_per_day: 700,
  max_capex: null,
  max_additional_machines: null,
  max_additional_operators: null,
  max_floor_area: null,
  allowed_action_types: null,
  forbidden_machine_ids: [],
  preserve_existing_layout: false,
  notes: [],
  confidence: 1,
  parse_warnings: [],
  prefer_no_new_machines: false,
  prefer_low_known_capex: false,
  prefer_few_changes: false,
  allowed_strategy_families: null,
};

const baselineSim = simulation({ completed_units: 300, demand_met: false, demand_gap_units: 200, target_units: 500 });
const afterAcceptSim = simulation({
  completed_units: 500,
  demand_met: true,
  demand_gap_units: 0,
  target_units: 500,
  system: { average_flow_time_seconds: 50, max_flow_time_seconds: 70, work_in_progress: 1, bottleneck_machine_id: "m-b" },
});

const baselineSnapshot = snapshot({ factory: sampleFactory, layout: null, simulation: baselineSim, cumulative_known_capex: 0 });
const afterAcceptSnapshot = snapshot({
  factory: sampleFactoryAfterIteration1,
  layout: null,
  simulation: afterAcceptSim,
  cumulative_known_capex: 50_000,
});

const acceptedIteration1: PlanningIteration = {
  iteration_index: 0,
  observation: "Demand gap: 200. Bottleneck: m-a.",
  planning_agent_result: {},
  selected_proposal: {
    proposal_id: "proposal-cand-add-parallel-m-a",
    scenario: {
      id: "cand-add-parallel-m-a",
      name: "Add parallel Machine A",
      description: "",
      actions: [{ action_type: "ADD_PARALLEL_MACHINE", machine_id: "m-a" }],
    },
    expected_effects: [],
    risks: [],
    confidence: 0.85,
    source: "DETERMINISTIC",
  },
  proposal_validation: [],
  scenario_result: {
    scenario_id: "cand-add-parallel-m-a",
    scenario_name: "Add parallel Machine A",
    baseline_result: baselineSim,
    candidate_result: afterAcceptSim,
    verdict: "IMPROVED",
    verdict_reasons: ["Demand gap decreased."],
  },
  layout_validation: null,
  recommendation_snapshot: {},
  accepted: true,
  rejection_reason: null,
  trace: ["Iteration 1:", "Proposed: Add parallel machine at m-a.", "Accepted."],
  known_capex: 50_000,
  requires_cost_estimate: false,
  state_before: baselineSnapshot,
  state_after: afterAcceptSnapshot,
  rejected_candidate_snapshot: null,
};

export const sampleSessionAccepted: PlanningSessionState = {
  session_id: "session",
  original_requirements: sampleRequirements,
  current_factory: sampleFactoryAfterIteration1,
  current_layout: null,
  baseline_factory: sampleFactory,
  baseline_layout: null,
  baseline_simulation: baselineSim,
  current_simulation: afterAcceptSim,
  iterations: [acceptedIteration1],
  current_best_result: afterAcceptSim,
  cumulative_known_capex: 50_000,
  remaining_known_capex: null,
  stop_reason: "GOAL_REACHED",
  goal_reached: true,
  baseline_snapshot: baselineSnapshot,
  final_snapshot: afterAcceptSnapshot,
};

export const sampleExplanationAccepted: PlanningExplanation = {
  executive_summary: "Fabrivium reached the target of 500 units/day in one verified iteration.",
  goal_status: "Goal reached: target 500 units/day; final verified output is 500/500 units (demand met).",
  recommended_changes: ["Added parallel Machine A capacity."],
  verified_effects: ["Iteration 1: verified demand gap reduced from 200 to 0 units/day. Demand met."],
  tradeoffs: ["Known CAPEX committed: €50,000."],
  constraints_and_risks: ["No layout was supplied and no machines were forbidden."],
  stop_explanation: "Planning stopped because the target was reached and verified by simulation.",
  sections: [
    { title: "Executive Summary", content: "Fabrivium reached the target of 500 units/day in one verified iteration.", evidence_refs: ["stop_reason"] },
    { title: "Goal Status", content: "Goal reached.", evidence_refs: [] },
    { title: "What Changed", content: "Iteration 1: added parallel Machine A capacity.", evidence_refs: ["iteration:1:scenario_result"] },
    { title: "Tradeoffs", content: "Known CAPEX committed: €50,000.", evidence_refs: ["budget:cumulative_capex"] },
    { title: "Why Planning Stopped", content: "Planning stopped because the target was reached and verified by simulation.", evidence_refs: ["stop_reason"] },
    { title: "Next Information Needed", content: "No further information is required based on verified results.", evidence_refs: [] },
  ],
  source_type: "DETERMINISTIC",
};

// Two-iteration session (mirrors the backend's 1900/day demonstration:
// baseline -> +Machine A clone -> +Machine B clone -> goal reached) ---

const twoIterFactoryAfter1 = withClone(sampleFactory, "m-a-parallel-1", "m-a");
const twoIterFactoryAfter2 = withClone(twoIterFactoryAfter1, "m-b-parallel-1", "m-b");

const twoIterBaselineSim = simulation({ completed_units: 250, demand_met: false, demand_gap_units: 450, target_units: 700, system: { average_flow_time_seconds: 80, max_flow_time_seconds: 120, work_in_progress: 4, bottleneck_machine_id: "m-a" } });
const twoIterAfter1Sim = simulation({ completed_units: 500, demand_met: false, demand_gap_units: 200, target_units: 700, system: { average_flow_time_seconds: 60, max_flow_time_seconds: 90, work_in_progress: 2, bottleneck_machine_id: "m-b" } });
const twoIterAfter2Sim = simulation({ completed_units: 700, demand_met: true, demand_gap_units: 0, target_units: 700, system: { average_flow_time_seconds: 45, max_flow_time_seconds: 65, work_in_progress: 1, bottleneck_machine_id: "m-a" } });

const twoIterBaselineSnapshot = snapshot({ factory: sampleFactory, layout: null, simulation: twoIterBaselineSim, cumulative_known_capex: 0 });
const twoIterAfter1Snapshot = snapshot({ factory: twoIterFactoryAfter1, layout: null, simulation: twoIterAfter1Sim, cumulative_known_capex: 50_000 });
const twoIterAfter2Snapshot = snapshot({ factory: twoIterFactoryAfter2, layout: null, simulation: twoIterAfter2Sim, cumulative_known_capex: 80_000 });

function acceptedIteration(index: number, machineId: string, before: PlanningStateSnapshot, after: PlanningStateSnapshot): PlanningIteration {
  return {
    iteration_index: index,
    observation: `Demand gap: ${before.simulation.demand_gap_units}. Bottleneck: ${before.bottleneck_machine_id}.`,
    planning_agent_result: {},
    selected_proposal: {
      proposal_id: `proposal-cand-add-parallel-${machineId}`,
      scenario: {
        id: `cand-add-parallel-${machineId}`,
        name: `Add parallel ${machineId}`,
        description: "",
        actions: [{ action_type: "ADD_PARALLEL_MACHINE", machine_id: machineId }],
      },
      expected_effects: [],
      risks: [],
      confidence: 0.85,
      source: "DETERMINISTIC",
    },
    proposal_validation: [],
    scenario_result: {
      scenario_id: `cand-add-parallel-${machineId}`,
      scenario_name: `Add parallel ${machineId}`,
      baseline_result: before.simulation,
      candidate_result: after.simulation,
      verdict: "IMPROVED",
      verdict_reasons: ["Demand gap decreased."],
    },
    layout_validation: null,
    recommendation_snapshot: {},
    accepted: true,
    rejection_reason: null,
    trace: [`Iteration ${index + 1}:`, `Proposed: Add parallel machine at ${machineId}.`, "Accepted."],
    known_capex: after.cumulative_known_capex - before.cumulative_known_capex,
    requires_cost_estimate: false,
    state_before: before,
    state_after: after,
    rejected_candidate_snapshot: null,
  };
}

export const sampleSessionTwoIterations: PlanningSessionState = {
  session_id: "session",
  original_requirements: { ...sampleRequirements, target_units_per_day: 700 },
  current_factory: twoIterFactoryAfter2,
  current_layout: null,
  baseline_factory: sampleFactory,
  baseline_layout: null,
  baseline_simulation: twoIterBaselineSim,
  current_simulation: twoIterAfter2Sim,
  iterations: [
    acceptedIteration(0, "m-a", twoIterBaselineSnapshot, twoIterAfter1Snapshot),
    acceptedIteration(1, "m-b", twoIterAfter1Snapshot, twoIterAfter2Snapshot),
  ],
  current_best_result: twoIterAfter2Sim,
  cumulative_known_capex: 80_000,
  remaining_known_capex: null,
  stop_reason: "GOAL_REACHED",
  goal_reached: true,
  baseline_snapshot: twoIterBaselineSnapshot,
  final_snapshot: twoIterAfter2Snapshot,
};

// A session WITH a real budget, mirroring the verified backend numbers for
// the €220,000 / 1900-units-per-day run. Exists specifically so the KPI
// panel's budget rows can be tested per stage: every snapshot below carries
// its OWN remaining figure, exactly as app.services.budget computes it.

const BUDGET_MAX_CAPEX = 220_000;

const budgetedBaselineSim = simulation({ completed_units: 1105, demand_met: false, demand_gap_units: 795, target_units: 1900, system: { average_flow_time_seconds: 80, max_flow_time_seconds: 120, work_in_progress: 4, bottleneck_machine_id: "m-a" } });
const budgetedAfter1Sim = simulation({ completed_units: 1642, demand_met: false, demand_gap_units: 258, target_units: 1900, system: { average_flow_time_seconds: 70, max_flow_time_seconds: 100, work_in_progress: 3, bottleneck_machine_id: "m-b" } });
const budgetedAfter2Sim = simulation({ completed_units: 1900, demand_met: true, demand_gap_units: 0, target_units: 1900, system: { average_flow_time_seconds: 45, max_flow_time_seconds: 65, work_in_progress: 1, bottleneck_machine_id: "m-a" } });

const budgetedFactoryAfter1 = withClone(sampleFactory, "m-a-parallel-1", "m-a");
const budgetedFactoryAfter2 = withClone(budgetedFactoryAfter1, "m-b-parallel-1", "m-b");

const budgetedBaselineSnapshot = snapshot({
  factory: sampleFactory, layout: null, simulation: budgetedBaselineSim,
  cumulative_known_capex: 0, remaining_known_capex: BUDGET_MAX_CAPEX - 0,
});
const budgetedAfter1Snapshot = snapshot({
  factory: budgetedFactoryAfter1, layout: null, simulation: budgetedAfter1Sim,
  cumulative_known_capex: 85_000, remaining_known_capex: BUDGET_MAX_CAPEX - 85_000,
});
const budgetedAfter2Snapshot = snapshot({
  factory: budgetedFactoryAfter2, layout: null, simulation: budgetedAfter2Sim,
  cumulative_known_capex: 205_000, remaining_known_capex: BUDGET_MAX_CAPEX - 205_000,
});

export const sampleSessionBudgeted: PlanningSessionState = {
  session_id: "session-budgeted",
  original_requirements: { ...sampleRequirements, target_units_per_day: 1900, max_capex: BUDGET_MAX_CAPEX },
  current_factory: budgetedFactoryAfter2,
  current_layout: null,
  baseline_factory: sampleFactory,
  baseline_layout: null,
  baseline_simulation: budgetedBaselineSim,
  current_simulation: budgetedAfter2Sim,
  iterations: [
    acceptedIteration(0, "m-a", budgetedBaselineSnapshot, budgetedAfter1Snapshot),
    acceptedIteration(1, "m-b", budgetedAfter1Snapshot, budgetedAfter2Snapshot),
  ],
  current_best_result: budgetedAfter2Sim,
  cumulative_known_capex: 205_000,
  // Session-level figure == the FINAL stage's figure, by construction.
  remaining_known_capex: BUDGET_MAX_CAPEX - 205_000,
  stop_reason: "GOAL_REACHED",
  goal_reached: true,
  baseline_snapshot: budgetedBaselineSnapshot,
  final_snapshot: budgetedAfter2Snapshot,
};

const rejectedCandidateFactory = withClone(sampleFactory, "m-b-parallel-1", "m-b");
const rejectedCandidateSim = simulation({ completed_units: 300, demand_met: false, demand_gap_units: 200, target_units: 500 });
const rejectedCandidateSnapshot = snapshot({
  factory: rejectedCandidateFactory,
  layout: null,
  simulation: rejectedCandidateSim,
  cumulative_known_capex: 30_000,
});

const rejectedIteration: PlanningIteration = {
  iteration_index: 0,
  observation: "Demand gap: 200. Bottleneck: m-a.",
  planning_agent_result: {},
  selected_proposal: {
    proposal_id: "proposal-user-requested-m-b",
    scenario: {
      id: "user-requested-m-b",
      name: "Add parallel Machine B (user-requested)",
      description: "",
      actions: [{ action_type: "ADD_PARALLEL_MACHINE", machine_id: "m-b" }],
    },
    expected_effects: [],
    risks: [],
    confidence: 0.3,
    source: "DETERMINISTIC",
  },
  proposal_validation: [],
  scenario_result: {
    scenario_id: "user-requested-m-b",
    scenario_name: "Add parallel Machine B (user-requested)",
    baseline_result: baselineSim,
    candidate_result: rejectedCandidateSim,
    verdict: "NEUTRAL",
    verdict_reasons: ["No material change."],
  },
  layout_validation: null,
  recommendation_snapshot: {},
  accepted: false,
  rejection_reason: "No verified improvement (no verified improvement over the current state).",
  trace: ["Iteration 1:", "Proposed: Add parallel machine at m-b.", "Rejected: no verified improvement."],
  known_capex: 30_000,
  requires_cost_estimate: false,
  state_before: baselineSnapshot,
  state_after: null,
  rejected_candidate_snapshot: rejectedCandidateSnapshot,
};

export const sampleSessionRejected: PlanningSessionState = {
  session_id: "session",
  original_requirements: { ...sampleRequirements, forbidden_machine_ids: ["m-a"] },
  current_factory: sampleFactory,
  current_layout: null,
  baseline_factory: sampleFactory,
  baseline_layout: null,
  baseline_simulation: baselineSim,
  current_simulation: baselineSim,
  iterations: [rejectedIteration],
  current_best_result: baselineSim,
  cumulative_known_capex: 0,
  remaining_known_capex: null,
  stop_reason: "REPEATED_PROPOSAL",
  goal_reached: false,
  baseline_snapshot: baselineSnapshot,
  final_snapshot: baselineSnapshot,
};

export const sampleExplanationRejected: PlanningExplanation = {
  executive_summary: "Fabrivium did not reach the target. Fabrivium stopped because the only available proposal had already been evaluated without producing a verified improvement; repeating it would not change the outcome.",
  goal_status: "Goal not reached: target 500 units/day; final verified output is 300/500 units (demand gap: 200 units, demand not met).",
  recommended_changes: [],
  verified_effects: ["Final verified state does not meet demand: a gap of 200 units/day remains."],
  tradeoffs: ["No CAPEX was committed and no tradeoffs were incurred."],
  constraints_and_risks: ["Iteration 1 rejected: No verified improvement (no verified improvement over the current state)."],
  stop_explanation: "Fabrivium stopped because the only available proposal had already been evaluated without producing a verified improvement; repeating it would not change the outcome.",
  sections: [
    { title: "Executive Summary", content: "Fabrivium did not reach the target.", evidence_refs: ["stop_reason"] },
    { title: "Goal Status", content: "Goal not reached.", evidence_refs: [] },
    { title: "What Changed", content: "No verified changes were made.", evidence_refs: [] },
    { title: "Tradeoffs", content: "No CAPEX was committed and no tradeoffs were incurred.", evidence_refs: [] },
    { title: "Why Planning Stopped", content: "Fabrivium stopped because the only available proposal had already been evaluated without producing a verified improvement; repeating it would not change the outcome.", evidence_refs: ["stop_reason"] },
    { title: "Next Information Needed", content: "No further information is required based on verified results.", evidence_refs: [] },
  ],
  source_type: "DETERMINISTIC",
};

// Phase 7C — conversational copilot fixtures
//
// Mirrors the backend's ConversationSession/PlanningBranch shape exactly.
// Branch metrics are copied from sampleSessionAccepted so a test can assert
// that the panel renders VERIFIED backend values rather than anything the
// frontend derived.

export function makeBranchMetrics(overrides: Partial<BranchMetrics> = {}): BranchMetrics {
  return {
    goal_reached: true,
    stop_reason: "GOAL_REACHED",
    demand_met: true,
    completed_units: 500,
    target_units: 500,
    demand_gap_units: 0,
    work_in_progress: 2,
    average_flow_time_seconds: 60,
    bottleneck_machine_id: "m-a",
    max_capex: 220_000,
    cumulative_known_capex: 205_000,
    remaining_known_capex: 15_000,
    added_machine_ids: ["m-a"],
    accepted_iterations: 1,
    total_iterations: 1,
    warnings: [],
    ...overrides,
  };
}

export function makeBranch(overrides: Partial<PlanningBranch> = {}): PlanningBranch {
  const metrics = overrides.metrics ?? makeBranchMetrics();
  return {
    branch_id: "branch-0-aaa",
    parent_branch_id: null,
    originating_turn_index: 0,
    label: "Plan A",
    base_mode: "ORIGINAL_BASELINE",
    status: metrics.goal_reached ? "GOAL_REACHED" : "GOAL_NOT_REACHED",
    active_requirements: { ...sampleRequirements, max_capex: 220_000 },
    metrics,
    verified_factory: sampleFactoryAfterIteration1,
    verified_layout: null,
    summary: "Target reached at 500/day for EUR 205,000.",
    ...overrides,
  };
}

export function makeTurn(overrides: Partial<ConversationTurn> = {}): ConversationTurn {
  return {
    turn_index: 0,
    raw_user_message: "We need 700 units/day.",
    status: "APPLIED",
    interpreted_update: null,
    intent_summary: "Set a daily production target.",
    requirements_before: null,
    requirements_after: sampleRequirements,
    changes: ["Objective: MEET_DEMAND", "Target: 700/day"],
    branch_id: "branch-0-aaa",
    base_mode: "ORIGINAL_BASELINE",
    clarification: null,
    explanation: sampleExplanationAccepted,
    provenance: {
      update_source: "DETERMINISTIC",
      planning_source: "DETERMINISTIC",
      explanation_source: "DETERMINISTIC",
      fallback_used: false,
      provider_name: null,
      model_name: null,
      prompt_tokens: null,
      completion_tokens: null,
      total_tokens: null,
    },
    warnings: [],
    errors: [],
    ...overrides,
  };
}

export function makeConversation(overrides: Partial<ConversationSession> = {}): ConversationSession {
  const branches = overrides.branches ?? [makeBranch()];
  return {
    conversation_id: "conv-test",
    product_id: "p-widget",
    baseline_factory: sampleFactory,
    baseline_layout: null,
    turns: overrides.turns ?? [makeTurn()],
    branches,
    active_branch_id: branches[branches.length - 1]?.branch_id ?? null,
    active_requirements: sampleRequirements,
    status: "ACTIVE",
    max_iterations: 5,
    ...overrides,
  };
}

/** A full POST /conversation/start response for the App integration test. */
export function conversationTurnResponse(): ConversationTurnResponse {
  return {
    session: makeConversation(),
    turn: makeTurn(),
    planning_session: sampleSessionAccepted,
  };
}

/** A two-branch conversation: Plan A meets the target expensively, Plan B is
 * cheaper and misses it — the Phase 7C scenario-A shape. */
export function makeTwoBranchConversation(): ConversationSession {
  const planA = makeBranch();
  const planB = makeBranch({
    branch_id: "branch-1-bbb",
    parent_branch_id: planA.branch_id,
    originating_turn_index: 1,
    label: "Plan B",
    active_requirements: { ...sampleRequirements, max_capex: 150_000 },
    metrics: makeBranchMetrics({
      goal_reached: false,
      demand_met: false,
      stop_reason: "BUDGET_EXHAUSTED",
      completed_units: 420,
      demand_gap_units: 80,
      max_capex: 150_000,
      cumulative_known_capex: 85_000,
      remaining_known_capex: 65_000,
    }),
    verified_factory: sampleFactory,
    summary: "Target not reached: 420/500/day (80 short) for EUR 85,000.",
  });
  return makeConversation({
    branches: [planA, planB],
    turns: [
      makeTurn(),
      makeTurn({
        turn_index: 1,
        raw_user_message: "That's too expensive. Keep it below €150k.",
        changes: ["Max CAPEX: EUR 220,000 -> EUR 150,000"],
        branch_id: planB.branch_id,
        requirements_before: { ...sampleRequirements, max_capex: 220_000 },
        requirements_after: { ...sampleRequirements, max_capex: 150_000 },
      }),
    ],
    active_requirements: { ...sampleRequirements, max_capex: 150_000 },
  });
}

export const sampleBranchComparison: BranchComparison = {
  branch_a_id: "branch-0-aaa",
  branch_b_id: "branch-1-bbb",
  label_a: "Plan A",
  label_b: "Plan B",
  metrics: [
    { metric: "goal_reached", label: "Target reached", value_a: true, value_b: false, delta: null, unit: null },
    { metric: "completed_units", label: "Completed units", value_a: 500, value_b: 420, delta: -80, unit: "units/day" },
    {
      metric: "cumulative_known_capex", label: "Known CAPEX",
      value_a: 205_000, value_b: 85_000, delta: -120_000, unit: "EUR",
    },
  ],
  machines_only_in_a: [],
  machines_only_in_b: [],
  constraint_differences: ["Budget: Plan A EUR 220,000, Plan B EUR 150,000"],
  unknown_information: [],
  headline: "Plan A reaches the target and costs EUR 120,000 more; Plan B does not.",
};

// Phase 8B — optimization arena fixtures
//
// Deliberately built as the honest hard case: Plan A is fully priced and
// misses the target, Plan B reaches it with a LOWER known CAPEX but has two
// unpriced components. Any UI that quietly treats unknown as zero will call
// Plan B "cheaper" and these fixtures will catch it.

export function makeStrategyMetrics(overrides: Partial<StrategyMetrics> = {}): StrategyMetrics {
  return {
    goal_met: true,
    stop_reason: "GOAL_REACHED",
    completed_units: 1900,
    target_units: 1900,
    demand_gap_units: 0,
    throughput_per_hour: 79.2,
    work_in_progress: 6,
    average_flow_time_seconds: 640,
    bottleneck_machine_id: "m-b",
    operator_utilization: 0.72,
    operator_constrained: false,
    max_buffer_full_fraction: 0.3,
    total_upstream_blocked_seconds: 0,
    ...overrides,
  };
}

export function makeStrategyActions(overrides: Partial<StrategyActionSummary> = {}): StrategyActionSummary {
  return {
    action_count: 1,
    added_machine_ids: [],
    added_machine_count: 0,
    added_shift_count: 0,
    hours_per_shift_delta: 0,
    operator_delta: 0,
    buffer_changes: [],
    action_types: [],
    ...overrides,
  };
}

export const shiftCostGap: InformationGap = {
  gap_type: "SHIFT_COST",
  action_type: "CHANGE_SHIFT_CONFIGURATION",
  description:
    "The operating cost of the changed shift pattern is not known. Supply it to compare this option financially against options whose cost is already established.",
  required_for: "Commercial comparison against other strategies.",
  expected_category: "OPEX_PER_DAY",
  severity: "BLOCKING",
};

export const operatorCostGap: InformationGap = {
  gap_type: "OPERATOR_COST",
  action_type: "CHANGE_OPERATOR_CAPACITY",
  description:
    "The employment cost of the additional operators is not known. Supply it to compare this option financially against options whose cost is already established.",
  required_for: "Commercial comparison against other strategies.",
  expected_category: "OPEX_PER_YEAR",
  severity: "BLOCKING",
};

/** Fully priced, but falls short of the target. */
export const strategyA: VerifiedStrategyOption = {
  strategy_id: "strategy-equipment_expansion",
  family: "EQUIPMENT_EXPANSION",
  label: "Plan A",
  title: "Add parallel capacity at the bottleneck",
  requirements: sampleRequirements,
  metrics: makeStrategyMetrics({
    goal_met: false,
    stop_reason: "NO_FURTHER_IMPROVEMENT",
    completed_units: 1619,
    demand_gap_units: 281,
  }),
  actions: makeStrategyActions({
    action_count: 1,
    added_machine_ids: ["m-a"],
    added_machine_count: 1,
    action_types: ["ADD_PARALLEL_MACHINE"],
  }),
  cost: {
    known_capex: 85_000,
    components: [
      { label: "Parallel machine at m-a", category: "CAPEX", amount: 85_000, source: "CATALOG" },
    ],
    information_gaps: [],
  },
  operationally_verified: true,
  commercially_complete: true,
  rationale: "Add parallel capacity at the bottleneck: reaches 1,619/day with 1 change, for EUR 85,000 of known CAPEX.",
  tradeoffs: ["Falls 281 units/day short; other options reach the target."],
  warnings: [],
};

/** Reaches the target, lower known CAPEX, and TWO unpriced components. */
export const strategyB: VerifiedStrategyOption = {
  strategy_id: "strategy-hybrid-no-equipment",
  family: "HYBRID",
  label: "Plan B",
  title: "Combine several levers without new equipment",
  requirements: sampleRequirements,
  metrics: makeStrategyMetrics(),
  actions: makeStrategyActions({
    action_count: 2,
    added_shift_count: 1,
    operator_delta: 2,
    action_types: ["CHANGE_OPERATOR_CAPACITY", "CHANGE_SHIFT_CONFIGURATION"],
  }),
  cost: {
    known_capex: 0,
    components: [
      { label: "Operating cost of the changed shift pattern (CHANGE_SHIFT_CONFIGURATION)", category: "OPEX_PER_DAY", amount: null, source: "CATALOG" },
      { label: "Employment cost of the additional operators (CHANGE_OPERATOR_CAPACITY)", category: "OPEX_PER_YEAR", amount: null, source: "CATALOG" },
    ],
    information_gaps: [shiftCostGap, operatorCostGap],
  },
  operationally_verified: true,
  commercially_complete: false,
  rationale: "Combine several levers without new equipment: reaches the target with 2 changes, at a cost that is not yet fully known.",
  tradeoffs: [
    "The only explored option that reaches the target.",
    "Lowest known CAPEX (EUR 0), but its commercial cost is incomplete.",
    "Requires no new equipment.",
  ],
  warnings: [],
};

export const sampleArena: StrategyArenaResult = {
  product_id: "p-1",
  baseline_metrics: makeStrategyMetrics({
    goal_met: false,
    stop_reason: "NONE",
    completed_units: 1105,
    demand_gap_units: 795,
    bottleneck_machine_id: "m-a",
    work_in_progress: 3,
  }),
  strategies: [strategyA, strategyB],
  frontiers: {
    commercially_complete_frontier: ["strategy-equipment_expansion"],
    operational_frontier: ["strategy-hybrid-no-equipment"],
    dominated_by: { "strategy-equipment_expansion": ["Plan B"] },
    commercial_dimensions: ["completed_units", "known_capex"],
    operational_dimensions: ["completed_units"],
  },
  recommended_strategy_id: "strategy-hybrid-no-equipment",
  stats: {
    families_attempted: 6,
    strategies_retained: 2,
    strategies_discarded: 1,
    simulations_run: 38,
    budget_exhausted: false,
    cache_hits: 121,
    elapsed_seconds: 7.4,
  },
  families_without_options: ["BUFFER_FLOW (no evidence supports this lever here)"],
  summary: "2 verified option(s); 1 reach the target, 0 of those are fully priced. Baseline: 1,105/day against 1,900.",
};

export const sampleStrategyComparison: StrategyComparison = {
  strategy_a_id: "strategy-equipment_expansion",
  strategy_b_id: "strategy-hybrid-no-equipment",
  label_a: "Plan A",
  label_b: "Plan B",
  family_a: "EQUIPMENT_EXPANSION",
  family_b: "HYBRID",
  metrics: [
    { metric: "goal_met", label: "Target reached", value_a: false, value_b: true, delta: null, unit: null },
    { metric: "completed_units", label: "Completed units", value_a: 1619, value_b: 1900, delta: 281, unit: "units/day" },
    { metric: "action_count", label: "Changes committed", value_a: 1, value_b: 2, delta: 1, unit: null },
  ],
  cost_rows: [
    { metric: "cost_CAPEX", label: "Capex", value_a: 85_000, value_b: 0, delta: -85_000, unit: "EUR" },
    // The row that must never render as 0: Plan B's per-day OPEX is UNKNOWN.
    { metric: "cost_OPEX_PER_DAY", label: "Opex Per Day", value_a: 0, value_b: null, delta: null, unit: "EUR" },
  ],
  machines_only_in_a: ["m-a"],
  machines_only_in_b: [],
  information_gaps_a: [],
  information_gaps_b: [shiftCostGap, operatorCostGap],
  comparable_on_cost: false,
  headline: "Plan B reaches the target (its full cost is not yet known); Plan A falls 281 units/day short.",
  notes: [
    "Not comparable on cost: Plan B still has unpriced components. Lower known CAPEX does not mean cheaper.",
  ],
};

export function makeStrategyAnswer(overrides: Partial<StrategyQueryAnswer> = {}): StrategyQueryAnswer {
  return {
    intent: "FEWEST_CHANGES",
    answer: "Plan A uses the fewest changes: 1 (ADD_PARALLEL_MACHINE).",
    strategy_ids: ["strategy-equipment_expansion"],
    comparison: null,
    information_gaps: [],
    cost_inputs: [],
    requires_repricing: false,
    simulations_run: 0,
    ...overrides,
  };
}

/** strategy_id -> verified session, as /strategies/explore returns it. */
export const sampleStrategySessions: Record<string, PlanningSessionState> = {
  "strategy-equipment_expansion": sampleSessionAccepted,
  "strategy-hybrid-no-equipment": sampleSessionTwoIterations,
};

/** The process-family catalog as `GET /process/families` returns it. */
export const PROCESS_FAMILY_CATALOG = {
  families: [
    { process_type: "assembly", label: "Assembly", aliases: ["assembl", "mounting"], has_reference_estimate: true, operation_noun: "assembly step", has_equipment_evidence: false },
    { process_type: "screwdriving", label: "Screwdriving", aliases: ["screwdriv"], has_reference_estimate: true, operation_noun: "screw", has_equipment_evidence: true },
    { process_type: "inspection", label: "Inspection", aliases: ["inspect"], has_reference_estimate: true, operation_noun: "check", has_equipment_evidence: true },
    { process_type: "packaging", label: "Packaging", aliases: ["packag"], has_reference_estimate: true, operation_noun: "packaging step", has_equipment_evidence: false },
    { process_type: "welding", label: "Welding", aliases: ["weld"], has_reference_estimate: false, operation_noun: null, has_equipment_evidence: false },
    { process_type: "soldering", label: "Soldering", aliases: ["solder"], has_reference_estimate: false, operation_noun: null, has_equipment_evidence: false },
    { process_type: "painting", label: "Painting", aliases: ["paint"], has_reference_estimate: false, operation_noun: null, has_equipment_evidence: false },
    { process_type: "machining", label: "Machining", aliases: ["machining"], has_reference_estimate: false, operation_noun: null, has_equipment_evidence: false },
    { process_type: "cleaning", label: "Cleaning", aliases: ["cleaning"], has_reference_estimate: false, operation_noun: null, has_equipment_evidence: false },
    { process_type: "labelling", label: "Labelling", aliases: ["labelling", "labeling"], has_reference_estimate: true, operation_noun: "label applied", has_equipment_evidence: true },
    { process_type: "curing", label: "Curing", aliases: ["curing"], has_reference_estimate: false, operation_noun: null, has_equipment_evidence: false },
    { process_type: "palletizing", label: "Palletizing", aliases: ["palletiz"], has_reference_estimate: false, operation_noun: null, has_equipment_evidence: false },
  ],
  families_with_reference_estimate: 5,
  families_with_equipment_evidence: 3,
  reference_dataset_name: "Electronics Assembly Demo Dataset",
};
