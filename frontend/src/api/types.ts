/** Frontend types mirroring Fabrivium backend response structures (backend/app/models/*.py). */

// Factory domain (backend/app/models/factory.py)

export interface ProcessStep {
  name: string;
  machine_id: string;
  cycle_time: number;
}

// Equipment asset / lifecycle (backend/app/models/equipment.py) — Phase 6B

export type EquipmentAssetType = "EXACT_CAD" | "LIBRARY" | "PROXY" | "MISSING";
export type EquipmentAssetStatus = "AVAILABLE" | "MISSING" | "REQUESTED" | "PROCESSING";
export type EquipmentLifecycleStatus =
  | "EXISTING"
  | "PURCHASE_CANDIDATE"
  | "CUSTOM_DESIGN"
  | "ORDERED"
  | "APPROVED"
  | "INSTALLED";

export interface EquipmentAsset {
  asset_type: EquipmentAssetType;
  status: EquipmentAssetStatus;
  asset_uri: string | null;
  source_uri: string | null;
  manufacturer: string | null;
  model_number: string | null;
  license_name: string | null;
  attribution: string | null;
  file_format: string | null;
  notes: string | null;
}

/** Height + directional safety clearances beyond width/length (Phase 6B
 * section 2) — deliberately NOT symmetric; each side is independent,
 * mirroring backend/app/models/factory.py's MachineEnvelopeExtras exactly. */
export interface MachineEnvelopeExtras {
  height: number | null;
  safety_clearance_front: number;
  safety_clearance_back: number;
  safety_clearance_left: number;
  safety_clearance_right: number;
}

export interface Machine {
  id: string;
  name: string;
  process_type: string;
  cycle_time: number;
  setup_time: number;
  capacity: number;
  operators_required: number;
  purchase_cost: number;
  position_x: number;
  position_y: number;
  width: number;
  length: number;
  parallel_of_machine_id?: string | null;
  asset: EquipmentAsset | null;
  lifecycle_status: EquipmentLifecycleStatus;
  physical_envelope: MachineEnvelopeExtras | null;
}

export interface Product {
  id: string;
  name: string;
  demand_per_day: number;
  route: ProcessStep[];
}

export interface Buffer {
  id: string;
  name: string;
  capacity: number;
  /** Phase 8A — the two route stages this buffer sits between. */
  upstream_machine_id?: string | null;
  downstream_machine_id?: string | null;
  position_x: number;
  position_y: number;
}

export interface Factory {
  name: string;
  width: number;
  length: number;
  shifts_per_day: number;
  hours_per_shift: number;
  operators_available: number;
  budget: number;
  machines: Machine[];
  products: Product[];
  buffers: Buffer[];
}

// Layout (backend/app/models/layout.py) — Phase 6B: full fidelity, since
// the 2D planner reads/writes every field directly.
//
// Coordinate convention (must match backend exactly — never silently
// redefined, per Phase 6B section 1):
//   MachinePlacement.x/y = machine footprint CENTER.
//   LayoutZone.x/y       = zone rectangle LOWER-LEFT corner.

export interface MachinePlacement {
  machine_id: string;
  x: number;
  y: number;
  z: number;
  rotation_deg: number;
}

export type LayoutZoneType = "AISLE" | "SAFETY" | "RESERVED" | "INPUT" | "OUTPUT";

export interface LayoutZone {
  id: string;
  name: string;
  x: number;
  y: number;
  width: number;
  length: number;
  zone_type: LayoutZoneType;
}

export interface FactoryLayout {
  factory_width: number;
  factory_length: number;
  placements: MachinePlacement[];
  reserved_zones: LayoutZone[];
  aisle_zones: LayoutZone[];
}

// Simulation (backend/app/models/simulation.py)

export interface ProcessPoolKPI {
  process_step_name: string;
  reference_machine_id: string;
  machine_ids: string[];
  processed_units: number;
  utilization: number;
  average_queue_length: number;
  max_queue_length: number;
  average_wait_time_seconds: number;
  max_wait_time_seconds: number;
}

export interface MachineKPI {
  machine_id: string;
  machine_name: string;
  processed_units: number;
  busy_time_seconds: number;
  utilization: number;
  average_queue_length: number;
  max_queue_length: number;
  average_wait_time_seconds: number;
  max_wait_time_seconds: number;
}

export interface SystemKPI {
  average_flow_time_seconds: number;
  max_flow_time_seconds: number;
  work_in_progress: number;
  bottleneck_machine_id: string;
}

/** Phase 8A — workforce utilisation. */
export interface OperatorKPI {
  operators_available: number;
  operators_required_peak: number;
  peak_operators_in_use: number;
  average_operators_in_use: number;
  utilization: number;
  total_operator_wait_seconds: number;
  average_operator_wait_seconds: number;
  max_operator_wait_seconds: number;
  operations_delayed_by_operators: number;
  /** True only when units ACTUALLY waited for staff — the evidence gate. */
  operator_constrained: boolean;
}

/** Phase 8A — occupancy and blocking for one wired buffer. */
export interface BufferKPI {
  buffer_id: string;
  buffer_name: string;
  capacity: number;
  upstream_machine_id: string;
  downstream_machine_id: string;
  average_level: number;
  max_level: number;
  utilization: number;
  time_full_seconds: number;
  time_empty_seconds: number;
  full_fraction: number;
  empty_fraction: number;
  /** Time an upstream machine was held by a finished unit it could not hand on. */
  upstream_blocked_seconds: number;
  upstream_blocked_events: number;
  blocking_observed: boolean;
}

export interface SimulationResult {
  simulation_time_seconds: number;
  target_units: number;
  completed_units: number;
  throughput_per_hour: number;
  demand_per_day: number;
  demand_met: boolean;
  demand_gap_units: number;
  machine_kpis: MachineKPI[];
  system: SystemKPI;
  process_pool_kpis: ProcessPoolKPI[];
  /** Phase 8A. Optional so a response from an older backend still type-checks. */
  operator_kpi?: OperatorKPI | null;
  buffer_kpis?: BufferKPI[];
}

// Playback trace (backend/app/models/simulation_trace.py) — Phase 8C
//
// Nothing here is ever recomputed by the frontend: every number is read
// straight off these fields. Animation may INTERPOLATE a visual position
// between two known points; it must never derive a KPI number.

export type TraceMode = "NONE" | "SUMMARY" | "PLAYBACK";

export interface TracePlaybackConfig {
  max_tracked_units: number;
  sample_count_target: number;
}

export type UnitEventType =
  | "UNIT_RELEASED"
  | "UNIT_ENTERED_MACHINE_QUEUE"
  | "UNIT_STARTED_PROCESSING"
  | "UNIT_FINISHED_PROCESSING"
  | "UNIT_ENTERED_BUFFER"
  | "UNIT_LEFT_BUFFER"
  | "UNIT_COMPLETED"
  | "MACHINE_BLOCKED"
  | "MACHINE_UNBLOCKED";

export interface UnitEvent {
  timestamp: number;
  unit_id: number;
  event_type: UnitEventType;
  machine_id?: string | null;
  buffer_id?: string | null;
}

export interface MachineTraceSample {
  timestamp: number;
  machine_id: string;
  queue_length: number;
  processing_count: number;
  blocked: boolean;
  utilization_so_far: number;
}

export interface BufferTraceSample {
  timestamp: number;
  buffer_id: string;
  level: number;
  capacity: number;
  blocked_upstream: boolean;
}

export interface OperatorTraceSample {
  timestamp: number;
  operators_in_use: number;
  operators_available: number;
  waiting_operations: number;
}

export interface SystemTraceSample {
  timestamp: number;
  completed_units: number;
  released_units: number;
  current_bottleneck_machine_id?: string | null;
}

export type StoryMarkerType =
  | "QUEUE_GROWING"
  | "BUFFER_FULL"
  | "MACHINE_BLOCKED"
  | "OPERATOR_CONSTRAINED"
  | "TARGET_ACHIEVED"
  | "TARGET_MISSED";

export interface StoryMarker {
  timestamp: number;
  marker_type: StoryMarkerType;
  entity_id: string;
  title: string;
  evidence_ref: string;
}

/** A strict superset of SimulationResult — `summary` IS the same result
 * POST /simulation/run would return for this (factory, product_id). Used
 * to assert trace/KPI consistency at the point of use, never recomputed. */
export interface SimulationTrace {
  trace_version: number;
  horizon_seconds: number;
  sampled_interval_seconds: number;
  config: TracePlaybackConfig;
  events: UnitEvent[];
  machine_series: MachineTraceSample[];
  buffer_series: BufferTraceSample[];
  operator_series: OperatorTraceSample[];
  system_series: SystemTraceSample[];
  story_markers: StoryMarker[];
  tracked_unit_count: number;
  total_unit_count: number;
  summary: SimulationResult;
  metadata: Record<string, string>;
}

export interface SimulationPlaybackRequest {
  factory: Factory;
  product_id: string;
  layout?: FactoryLayout;
  trace_config?: TracePlaybackConfig;
}

// Scenario comparison (backend/app/models/comparison.py)

export type Verdict = "IMPROVED" | "NEUTRAL" | "DEGRADED";

export interface ScenarioResult {
  scenario_id: string;
  scenario_name: string;
  baseline_result: SimulationResult;
  candidate_result: SimulationResult;
  verdict: Verdict;
  verdict_reasons: string[];
}

// Constraints (backend/app/models/constraints.py)

export type ConstraintType =
  | "OUT_OF_BOUNDS"
  | "MACHINE_OVERLAP"
  | "SAFETY_CLEARANCE_OVERLAP"
  | "AISLE_BLOCKED"
  | "RESERVED_ZONE_OVERLAP"
  | "MISSING_PLACEMENT"
  | "UNKNOWN_MACHINE"
  | "DUPLICATE_PLACEMENT";

export interface ConstraintViolation {
  violation_type: ConstraintType;
  severity: "ERROR" | "WARNING";
  message: string;
  machine_ids: string[];
  zone_ids: string[];
  details: Record<string, number> | null;
}

export interface LayoutValidationResult {
  valid: boolean;
  error_count: number;
  warning_count: number;
  violations: ConstraintViolation[];
}

export interface LayoutValidateRequest {
  factory: Factory;
  layout: FactoryLayout;
  product_id?: string | null;
}

// Requirements (backend/app/models/agent.py)

export type OptimizationObjective =
  | "MEET_DEMAND"
  | "MAXIMIZE_THROUGHPUT"
  | "MINIMIZE_WIP"
  | "MINIMIZE_FLOW_TIME";

export interface PlanningRequirements {
  objective: OptimizationObjective;
  target_units_per_day: number | null;
  max_capex: number | null;
  max_additional_machines: number | null;
  max_additional_operators: number | null;
  max_floor_area: number | null;
  allowed_action_types: string[] | null;
  forbidden_machine_ids: string[];
  preserve_existing_layout: boolean;
  notes: string[];
  confidence: number;
  parse_warnings: string[];

  // Phase 8B soft PREFERENCES. Distinct from the hard constraints above:
  // a preference orders otherwise-comparable options and must never stop
  // Fabrivium exploring — or recommending — the plan that turns out to
  // be the only one reaching the target.
  prefer_no_new_machines: boolean;
  prefer_low_known_capex: boolean;
  prefer_few_changes: boolean;
  /** null = every family may be explored. */
  allowed_strategy_families: string[] | null;
}

export interface RequirementsParseResult {
  raw_user_request: string;
  parsed_requirements: PlanningRequirements;
  warnings: string[];
  parser_type: "DETERMINISTIC_FALLBACK" | "LLM";
  structured_output_valid: boolean;
}

// Scenario action (backend/app/models/scenario.py) — loosely typed union;
// the UI only ever reads action_type + the field relevant to it.

/** Mirrors backend/app/models/scenario.py's discriminated union. */
export interface ScenarioAction {
  action_type:
    | "ADD_PARALLEL_MACHINE"
    | "CHANGE_MACHINE_CYCLE_TIME"
    | "CHANGE_MACHINE_CAPACITY"
    | "REMOVE_MACHINE"
    | "CHANGE_DEMAND"
    // Phase 8A — shifts / operators / buffers
    | "CHANGE_SHIFT_CONFIGURATION"
    | "CHANGE_OPERATOR_CAPACITY"
    | "CHANGE_BUFFER_CAPACITY";
  machine_id?: string;
  cycle_time?: number;
  capacity?: number;
  // Phase 8A fields
  shifts_per_day?: number | null;
  hours_per_shift?: number | null;
  operators_available?: number;
  buffer_id?: string;
  new_capacity?: number;
}

export interface PlanningProposal {
  proposal_id: string;
  scenario: { id: string; name: string; description: string; actions: ScenarioAction[] };
  expected_effects: string[];
  risks: string[];
  confidence: number;
  source: "DETERMINISTIC" | "LLM";
}

// Orchestrator (backend/app/models/orchestrator.py)

export type PlanningStopReason =
  | "GOAL_REACHED"
  | "MAX_ITERATIONS"
  | "NO_VALID_PROPOSAL"
  | "NO_FEASIBLE_IMPROVEMENT"
  | "BUDGET_EXHAUSTED"
  | "CONSTRAINT_BLOCKED"
  | "REPEATED_PROPOSAL"
  | "USER_CONSTRAINTS_BLOCK_PROGRESS"
  | "ERROR";

/**
 * A complete, reproducible digital-twin state at one point in a planning
 * session (Phase 6A.1) — the SAME shape is used for an iteration's
 * before/after state and for the session's baseline/final state, so the
 * timeline only ever needs to handle one stage shape.
 */
export interface PlanningStateSnapshot {
  factory: Factory;
  /** null precisely when no layout was supplied to the session at all — never fabricated. */
  layout: FactoryLayout | null;
  simulation: SimulationResult;
  bottleneck_machine_id: string;
  cumulative_known_capex: number;
  /** Known CAPEX still available AT THIS EXACT STATE (max_capex minus this
   * snapshot's cumulative spend); null when the session set no budget.
   *
   * Always read this rather than `PlanningSessionState.remaining_known_capex`
   * when rendering a selected stage — the session field is the FINAL
   * remaining, and pairing it with a per-iteration cumulative reports two
   * numbers from different points in time. */
  remaining_known_capex: number | null;
}

export interface PlanningIteration {
  iteration_index: number;
  observation: string;
  /** Full audit record from the planning agent — not rendered in detail by Phase 6A UI. */
  planning_agent_result: unknown;
  selected_proposal: PlanningProposal | null;
  proposal_validation: string[];
  scenario_result: ScenarioResult | null;
  layout_validation: LayoutValidationResult | null;
  recommendation_snapshot: unknown;
  accepted: boolean;
  rejection_reason: string | null;
  trace: string[];
  known_capex: number | null;
  requires_cost_estimate: boolean;
  /** Exact verified state entering this iteration — always present. */
  state_before: PlanningStateSnapshot | null;
  /** Exact verified state after this iteration — set iff accepted. */
  state_after: PlanningStateSnapshot | null;
  /** The evaluated-but-rejected candidate's state — set iff NOT accepted
   * and a candidate was actually simulated. Never the accepted state. */
  rejected_candidate_snapshot: PlanningStateSnapshot | null;
}

export interface PlanningSessionState {
  session_id: string;
  original_requirements: PlanningRequirements;
  current_factory: Factory;
  current_layout: FactoryLayout | null;
  baseline_factory: Factory;
  baseline_layout: FactoryLayout | null;
  baseline_simulation: SimulationResult;
  current_simulation: SimulationResult;
  iterations: PlanningIteration[];
  current_best_result: SimulationResult;
  cumulative_known_capex: number;
  remaining_known_capex: number | null;
  stop_reason: PlanningStopReason | null;
  goal_reached: boolean;
  /** == (current_factory pre-iteration-0, current_layout, baseline_simulation, 0). */
  baseline_snapshot: PlanningStateSnapshot;
  /** Always == (current_factory, current_layout, current_simulation, cumulative_known_capex). */
  final_snapshot: PlanningStateSnapshot;
}

// Explanation (backend/app/models/explanation.py)

export type ExplanationSourceType = "DETERMINISTIC" | "LLM";

export interface ExplanationSection {
  title: string;
  content: string;
  evidence_refs: string[];
}

export interface PlanningExplanation {
  executive_summary: string;
  goal_status: string;
  recommended_changes: string[];
  verified_effects: string[];
  tradeoffs: string[];
  constraints_and_risks: string[];
  stop_explanation: string;
  sections: ExplanationSection[];
  source_type: ExplanationSourceType;
}

// POST /planning/run

export interface PlanningRunRequest {
  factory: Factory;
  product_id: string;
  user_request: string;
  layout?: FactoryLayout | null;
  max_iterations?: number;
  max_capex?: number | null;
}

/** Where each stage of a planning run's output actually came from (Phase 7A). */
export interface PlanningProvenance {
  requirements_source: "DETERMINISTIC" | "LLM";
  planning_source: "DETERMINISTIC" | "LLM" | "MIXED" | "NONE";
  /** NONE = this response carries no explanation at all — the strategy
   * arena returns verified options and deterministic rationales rather
   * than a PlanningExplanation. */
  explanation_source: "DETERMINISTIC" | "LLM" | "NONE";
  fallback_used: boolean;
  /** Phase 7B — which model was configured, e.g. */
  provider_name?: string | null;
  model_name?: string | null;
}

export interface PlanningRunResponse {
  parse_result: RequirementsParseResult;
  session: PlanningSessionState;
  explanation: PlanningExplanation;
  provenance: PlanningProvenance;
}

// Phase 7C — conversational engineering copilot
//
// These mirror app/models/conversation.py exactly. The session is
// round-tripped to a STATELESS backend, so it deliberately carries per-branch
// metrics and verified factories but NOT the full PlanningSessionState of
// every branch — the full session for a newly created branch arrives once, at
// the top level of a turn response, and the client caches it (see
// AppState.branchSessions). Switching branches is therefore a local lookup,
// never a re-plan, so it can never show a different answer than the one that
// was audited.

export type PlanningBaseMode = "ORIGINAL_BASELINE" | "CURRENT_VERIFIED_STATE";

export type TurnStatus =
  | "APPLIED"
  | "NO_CHANGE"
  | "CLARIFICATION_REQUIRED"
  | "REJECTED"
  | "PROVIDER_UNAVAILABLE";

export type UpdateSource = "LLM" | "DETERMINISTIC" | "NONE";
export type BranchStatus = "GOAL_REACHED" | "GOAL_NOT_REACHED";
export type ConversationStatus = "ACTIVE" | "AWAITING_CLARIFICATION";

export interface ClarificationRequest {
  question: string;
  ambiguous_fields: string[];
  safe_options: string[];
}

export interface RequirementUpdate {
  objective?: OptimizationObjective | null;
  target_units_per_day?: number | null;
  max_capex?: number | null;
  max_additional_machines?: number | null;
  max_additional_operators?: number | null;
  max_floor_area?: number | null;
  allowed_action_types?: string[] | null;
  preserve_existing_layout?: boolean | null;
  forbidden_machine_ids_add: string[];
  forbidden_machine_ids_remove: string[];
  reset_constraints: string[];
  explicit_intervention?: string | null;
  base_mode?: PlanningBaseMode | null;
  clarification_required: boolean;
  clarification?: ClarificationRequest | null;
  intent_summary: string;
}

/** A branch's VERIFIED KPI summary. */
export interface BranchMetrics {
  goal_reached: boolean;
  stop_reason: string;
  demand_met: boolean;
  completed_units: number;
  target_units: number;
  demand_gap_units: number;
  work_in_progress: number;
  average_flow_time_seconds: number;
  bottleneck_machine_id: string;
  max_capex: number | null;
  cumulative_known_capex: number;
  remaining_known_capex: number | null;
  added_machine_ids: string[];
  accepted_iterations: number;
  total_iterations: number;
  warnings: string[];
}

export interface PlanningBranch {
  branch_id: string;
  parent_branch_id: string | null;
  originating_turn_index: number;
  label: string;
  base_mode: PlanningBaseMode;
  status: BranchStatus;
  active_requirements: PlanningRequirements;
  metrics: BranchMetrics;
  verified_factory: Factory;
  verified_layout: FactoryLayout | null;
  summary: string;
}

export interface TurnProvenance {
  update_source: UpdateSource;
  planning_source: string;
  explanation_source: string;
  fallback_used: boolean;
  provider_name?: string | null;
  model_name?: string | null;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  total_tokens?: number | null;
}

export interface ConversationTurn {
  turn_index: number;
  raw_user_message: string;
  status: TurnStatus;
  interpreted_update?: RequirementUpdate | null;
  intent_summary: string;
  requirements_before?: PlanningRequirements | null;
  requirements_after?: PlanningRequirements | null;
  /** Deterministic diff rendered from the typed values — never model prose. */
  changes: string[];
  branch_id: string | null;
  base_mode?: PlanningBaseMode | null;
  clarification?: ClarificationRequest | null;
  explanation?: PlanningExplanation | null;
  provenance: TurnProvenance;
  warnings: string[];
  errors: string[];
}

export interface ConversationSession {
  conversation_id: string;
  product_id: string;
  baseline_factory: Factory;
  baseline_layout: FactoryLayout | null;
  turns: ConversationTurn[];
  branches: PlanningBranch[];
  active_branch_id: string | null;
  active_requirements: PlanningRequirements | null;
  status: ConversationStatus;
  max_iterations: number;
}

export interface ConversationStartRequest {
  factory: Factory;
  product_id: string;
  user_message: string;
  layout?: FactoryLayout;
  max_iterations?: number;
}

export interface ConversationTurnRequest {
  session: ConversationSession;
  user_message: string;
}

export interface ConversationTurnResponse {
  session: ConversationSession;
  turn: ConversationTurn;
  /** Populated ONLY when the turn produced a new branch. */
  planning_session: PlanningSessionState | null;
}

export interface BranchMetricDelta {
  metric: string;
  label: string;
  value_a: number | boolean | string | null;
  value_b: number | boolean | string | null;
  delta: number | null;
  unit: string | null;
}

export interface BranchComparison {
  branch_a_id: string;
  branch_b_id: string;
  label_a: string;
  label_b: string;
  metrics: BranchMetricDelta[];
  machines_only_in_a: string[];
  machines_only_in_b: string[];
  constraint_differences: string[];
  unknown_information: string[];
  headline: string;
}

export interface BranchComparisonRequest {
  session: ConversationSession;
  branch_a_id: string;
  branch_b_id: string;
}

// Phase 8B — multi-strategy optimization arena
//
// Mirrors backend/app/models/strategy.py. The rule these types encode: an
// UNKNOWN cost is not a zero cost. `known_capex` is only ever the sum of
// KNOWN CAPEX components, `commercially_complete` says whether anything is
// still unpriced, and there is deliberately no "total cost" field — CAPEX
// and OPEX are different kinds of number and are never summed.

export type OptimizationStrategyFamily =
  | "EQUIPMENT_EXPANSION"
  | "SHIFT_EXPANSION"
  | "WORKFORCE_EXPANSION"
  | "BUFFER_FLOW"
  | "PROCESS_IMPROVEMENT"
  | "HYBRID";

export type CostCategory = "CAPEX" | "OPEX_PER_DAY" | "OPEX_PER_YEAR" | "ONE_TIME_OTHER";

export type InformationGapType =
  | "SHIFT_COST"
  | "OPERATOR_COST"
  | "BUFFER_MODIFICATION_COST"
  | "PROCESS_IMPROVEMENT_COST"
  | "MACHINE_CAPACITY_COST";

export interface InformationGap {
  gap_type: InformationGapType;
  action_type: string;
  description: string;
  required_for: string;
  expected_category: CostCategory;
  severity: string;
}

export interface CostComponent {
  label: string;
  category: CostCategory;
  /** null = UNKNOWN. Never a placeholder zero. */
  amount: number | null;
  source: string;
}

export interface StrategyCostProfile {
  known_capex: number;
  components: CostComponent[];
  information_gaps: InformationGap[];
  /** Known money per category, e.g. */
  known_by_category?: Partial<Record<CostCategory, number>>;
}

export interface StrategyActionSummary {
  action_count: number;
  added_machine_ids: string[];
  added_machine_count: number;
  added_shift_count: number;
  hours_per_shift_delta: number;
  operator_delta: number;
  buffer_changes: string[];
  action_types: string[];
}

export interface StrategyMetrics {
  goal_met: boolean;
  /** What the line can actually produce per day under continuous demand. */
  capacity_units_per_day?: number | null;
  capacity_headroom_percent?: number | null;
  /** The honest form of "target achieved". */
  sustains_target_at_capacity?: boolean | null;
  stop_reason: string;
  completed_units: number;
  target_units: number;
  demand_gap_units: number;
  throughput_per_hour: number;
  work_in_progress: number;
  average_flow_time_seconds: number;
  bottleneck_machine_id: string;
  operator_utilization: number | null;
  operator_constrained: boolean;
  max_buffer_full_fraction: number;
  total_upstream_blocked_seconds: number;
}

export interface VerifiedStrategyOption {
  strategy_id: string;
  family: OptimizationStrategyFamily;
  label: string;
  title: string;
  requirements: PlanningRequirements;
  metrics: StrategyMetrics;
  actions: StrategyActionSummary;
  cost: StrategyCostProfile;
  /** A real simulation produced these KPIs. Independent of cost. */
  operationally_verified: boolean;
  /** Nothing about the cost is still unknown. */
  commercially_complete: boolean;
  rationale: string;
  tradeoffs: string[];
  warnings: string[];
}

export interface StrategyFrontiers {
  commercially_complete_frontier: string[];
  operational_frontier: string[];
  dominated_by: Record<string, string[]>;
  commercial_dimensions: string[];
  operational_dimensions: string[];
}

export interface StrategySearchStats {
  families_attempted: number;
  strategies_retained: number;
  strategies_discarded: number;
  simulations_run: number;
  budget_exhausted: boolean;
  cache_hits: number;
  elapsed_seconds: number;
}

export interface StrategyArenaResult {
  product_id: string;
  baseline_metrics: StrategyMetrics;
  strategies: VerifiedStrategyOption[];
  frontiers: StrategyFrontiers;
  recommended_strategy_id: string | null;
  stats: StrategySearchStats;
  families_without_options: string[];
  summary: string;
}

export interface StrategyMetricDelta {
  metric: string;
  label: string;
  value_a: number | boolean | string | null;
  value_b: number | boolean | string | null;
  delta: number | null;
  unit: string | null;
}

export interface StrategyComparison {
  strategy_a_id: string;
  strategy_b_id: string;
  label_a: string;
  label_b: string;
  family_a: OptimizationStrategyFamily;
  family_b: OptimizationStrategyFamily;
  metrics: StrategyMetricDelta[];
  cost_rows: StrategyMetricDelta[];
  machines_only_in_a: string[];
  machines_only_in_b: string[];
  information_gaps_a: InformationGap[];
  information_gaps_b: InformationGap[];
  comparable_on_cost: boolean;
  headline: string;
  notes: string[];
}

export interface UserCostInput {
  gap_type: InformationGapType;
  amount: number;
  category: CostCategory;
  note?: string;
}

export interface StrategyExploreRequest {
  factory: Factory;
  product_id: string;
  user_request: string;
  /** Earlier turns of this refinement, oldest first, WITHOUT the current one. */
  prior_requests?: string[];
  layout?: FactoryLayout;
  max_capex?: number | null;
  user_costs?: UserCostInput[];
}

export interface StrategyExploreResponse {
  parse_result: RequirementsParseResult;
  arena: StrategyArenaResult;
  /** strategy_id -> the EXACT verified session, so opening a card needs no
   * recomputation and no geometry reconstruction. */
  sessions: Record<string, PlanningSessionState>;
  provenance: PlanningProvenance;
}

export interface StrategyCompareRequest {
  strategy_a: VerifiedStrategyOption;
  strategy_b: VerifiedStrategyOption;
}

// Phase 8B section 15: follow-ups over verified strategy data
//
// Every intent below is answerable from an arena that already exists, so
// asking never re-runs engineering. `simulations_run` is 0 by construction
// and is surfaced in the type so the UI can prove it rather than promise it.

export type StrategyQueryIntent =
  | "CHEAPER_OPTION"
  | "NO_NEW_MACHINE"
  | "FEWEST_CHANGES"
  | "COMPARE"
  | "INFORMATION_NEEDED"
  | "PROVIDE_COST"
  | "UNRECOGNIZED";

export interface StrategyQueryAnswer {
  intent: StrategyQueryIntent;
  /** Deterministic sentence(s) built by the backend over verified values. */
  answer: string;
  strategy_ids: string[];
  comparison: StrategyComparison | null;
  information_gaps: InformationGap[];
  cost_inputs: UserCostInput[];
  /** True only when supplied costs must be folded back in — money only. */
  requires_repricing: boolean;
  simulations_run: number;
}

/** Body for POST /simulation/playback/verified. */
export interface VerifiedPlaybackRequest {
  factory: Factory;
  product_id: string;
  actions: StrategyActionSummary | null;
  expected: StrategyMetrics;
  layout?: FactoryLayout;
  trace_config?: TracePlaybackConfig;
}

export interface StrategyAskRequest {
  arena: StrategyArenaResult;
  question: string;
  /** Needed only for cost statements, which re-derive cost from them. */
  sessions?: Record<string, PlanningSessionState>;
  /** Costs already established on this project. */
  established_costs?: UserCostInput[];
}

export interface StrategyAskResponse {
  answer: StrategyQueryAnswer;
  /** Unchanged unless the question supplied costs. */
  arena: StrategyArenaResult;
  repriced: boolean;
}

// Phase 13 — factory concept builder

/** Where one concept value came from. */
export type ValueSource =
  | "CUSTOMER"
  | "MANUFACTURER"
  | "ENGINEERING_ESTIMATE"
  /** Typed in by the engineer. */
  | "ENGINEER"
  /** Read out of a document the engineer supplied, with a citation. */
  | "DOCUMENT"
  /** Observed on a real line. The only source that is not a prediction. */
  | "MEASURED"
  /** A named external system: a company catalog, a supplier price list. */
  | "EXTERNAL_DATA"
  /** Produced by running Fabrivium's simulator. Never an input. */
  | "SIMULATED"
  | "EXAMPLE_DATA"
  | "CATALOG_DEFAULT"
  | "CALCULATED"
  | "UNKNOWN";

/** A value that may legitimately be absent, and knows its own origin. */
export interface SourcedNumber {
  value: number | null;
  source: ValueSource;
  /** Attribution shown in the provenance view, e.g. the dataset name. */
  detail: string | null;
}

export interface ConceptStage {
  id: string;
  name: string;
  process_type: string;
  /** Engineering physics — required before simulation, never defaulted. */
  cycle_time: SourcedNumber;
  capacity: SourcedNumber;
  operators_required: SourcedNumber;
  /** Planning footprint. Never a simulation input. */
  width: SourcedNumber;
  length: SourcedNumber;
  purchase_cost: SourcedNumber;
  /** G10/G11 — the reviewed manufacturing operation this station was built
   * from, on a concept that came from the product route. A LINK, not a
   * copy: what that operation says is read live from the process draft, so
   * an operation edited after the concept was built is seen as edited.
   * Absent on a concept built from a brief by hand. */
  source_operation_id?: string | null;
  /** The range the cycle time was resolved from, when it came from an estimate. */
  cycle_time_estimate?: StageEstimateRecord | null;
}

/** What an accepted estimate recorded about how it was composed. */
export interface StageEstimateRecord {
  operations_per_unit?: number | null;
}

export interface ConceptBuffer {
  id: string;
  name: string;
  upstream_stage_id: string;
  downstream_stage_id: string;
  capacity: SourcedNumber;
}

export interface FactoryConceptDraft {
  name: string;
  customer_brief: string;
  /** Becomes Product.demand_per_day at conversion — the field the existing
   * pipeline already reads as the goal. */
  production_target: SourcedNumber;
  product_name: string;
  stages: ConceptStage[];
  buffers: ConceptBuffer[];
  shifts_per_day: SourcedNumber;
  hours_per_shift: SourcedNumber;
  operators_available: SourcedNumber;
  /** Layout only — the simulator reads no floor size. */
  floor_width: SourcedNumber;
  floor_length: SourcedNumber;
  budget: SourcedNumber;
  prefer_no_new_machines: boolean;
}

export interface ConceptGap {
  key: string;
  label: string;
  /** REQUIRED gaps block simulation; OPTIONAL ones never do. */
  severity: "REQUIRED" | "OPTIONAL";
  reason: string;
  stage_id: string | null;
}

export interface ConceptValidation {
  simulation_ready: boolean;
  blocking_gaps: ConceptGap[];
  optional_gaps: ConceptGap[];
  errors: string[];
}

export interface ConceptResponse {
  draft: FactoryConceptDraft;
  validation: ConceptValidation;
}

export interface ConceptBuildResponse {
  factory: Factory;
  product_id: string;
  /** An INITIAL planning layout, not an optimal one. */
  layout: FactoryLayout;
  validation: ConceptValidation;
}
