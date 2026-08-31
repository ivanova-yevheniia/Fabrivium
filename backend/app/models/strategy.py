"""Multi-strategy optimization domain models for Fabrivium Phase 8B."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, computed_field

from app.models.agent import PlanningRequirements


# Families


class OptimizationStrategyFamily(str, Enum):
    """The kind of engineering lever a strategy is built from."""

    EQUIPMENT_EXPANSION = "EQUIPMENT_EXPANSION"
    SHIFT_EXPANSION = "SHIFT_EXPANSION"
    WORKFORCE_EXPANSION = "WORKFORCE_EXPANSION"
    BUFFER_FLOW = "BUFFER_FLOW"
    PROCESS_IMPROVEMENT = "PROCESS_IMPROVEMENT"
    HYBRID = "HYBRID"


# Cost


class CostCategory(str, Enum):
    """What KIND of money an action costs."""

    CAPEX = "CAPEX"
    OPEX_PER_DAY = "OPEX_PER_DAY"
    OPEX_PER_YEAR = "OPEX_PER_YEAR"
    ONE_TIME_OTHER = "ONE_TIME_OTHER"


class InformationGapType(str, Enum):
    SHIFT_COST = "SHIFT_COST"
    OPERATOR_COST = "OPERATOR_COST"
    BUFFER_MODIFICATION_COST = "BUFFER_MODIFICATION_COST"
    PROCESS_IMPROVEMENT_COST = "PROCESS_IMPROVEMENT_COST"
    MACHINE_CAPACITY_COST = "MACHINE_CAPACITY_COST"


class InformationGap(BaseModel):
    """
    One thing Fabrivium needs to know before a strategy can be ranked on money (Phase 8B
    section 17).
    """

    model_config = {"frozen": True}

    gap_type: InformationGapType
    action_type: str = Field(..., description="The ScenarioAction type whose cost is unknown.")
    description: str = Field(..., description="Deterministic, templated. Never model prose.")
    required_for: str = Field(
        "commercial comparison",
        description="What this blocks. Operational verification never depends on cost.",
    )
    expected_category: CostCategory = Field(
        ..., description="What kind of number would fill this gap, so the answer can be asked for precisely."
    )
    severity: str = Field("BLOCKING", description="BLOCKING = the strategy cannot be ranked on cost without it.")


class CostComponent(BaseModel):
    """One priced (or unpriced) element of a strategy's cost."""

    model_config = {"frozen": True}

    label: str
    category: CostCategory
    amount: float | None = Field(None, description="None = unknown. Never a placeholder zero.")
    source: str = Field(
        "CATALOG",
        description="CATALOG = derived from factory data (e.g. machine purchase_cost). USER = supplied by the operator.",
    )


class StrategyCostProfile(BaseModel):
    """Everything known and unknown about what a strategy costs."""

    model_config = {"frozen": True}

    known_capex: float = Field(0.0, ge=0.0, description="Sum of KNOWN CAPEX components only.")
    components: list[CostComponent] = Field(default_factory=list)
    information_gaps: list[InformationGap] = Field(default_factory=list)

    @computed_field(  # type: ignore[prop-decorator]
        description=(
            "Known money per category, e.g. {'CAPEX': 0.0, 'OPEX_PER_DAY': 0.0}. Summed WITHIN "
            "a category and never across them, so this is a breakdown and still not a total. Present "
            "so that a reader of `known_capex` alone cannot mistake a CAPEX-free plan for a free one."
        )
    )
    @property
    def known_by_category(self) -> dict[CostCategory, float]:
        """Known money, kept apart by kind (G14)."""
        totals: dict[CostCategory, float] = {}
        for component in self.components:
            if component.amount is None:
                continue
            totals[component.category] = round(totals.get(component.category, 0.0) + component.amount, 6)
        return totals

    @property
    def known_non_capex(self) -> dict[CostCategory, float]:
        """The known money that `known_capex` does not describe."""
        return {k: v for k, v in self.known_by_category.items() if k is not CostCategory.CAPEX}

    @property
    def unknown_cost_components(self) -> list[str]:
        return [c.label for c in self.components if c.amount is None]

    @property
    def commercially_complete(self) -> bool:
        """True when every component of this strategy has a price."""
        return not any(c.amount is None for c in self.components)


class UserCostInput(BaseModel):
    """
    An explicit cost the operator supplied for a previously unknown component (Phase 8B
    section 18).
    """

    model_config = {"frozen": True}

    gap_type: InformationGapType
    amount: float = Field(..., ge=0.0)
    category: CostCategory
    note: str = ""


# Strategy


class StrategyActionSummary(BaseModel):
    """What a strategy actually DOES, counted from its accepted iterations."""

    model_config = {"frozen": True}

    action_count: int = Field(0, ge=0, description="Accepted interventions. The 'fewest changes' objective.")
    added_machine_ids: list[str] = Field(default_factory=list)
    added_machine_count: int = Field(0, ge=0)
    added_shift_count: int = Field(0, description="Net change in shifts per day. May be negative.")
    hours_per_shift_delta: float = Field(0.0)
    operator_delta: int = Field(0, description="Net change in simultaneous operator capacity.")
    buffer_changes: list[str] = Field(
        default_factory=list, description="Human-readable 'buf-1: 50 -> 100' entries, in accepted order."
    )
    action_types: list[str] = Field(default_factory=list, description="Distinct accepted action types, sorted.")


class StrategyMetrics(BaseModel):
    """A strategy's VERIFIED outcome, flattened for comparison."""

    model_config = {"frozen": True}

    goal_met: bool
    stop_reason: str
    completed_units: int
    target_units: int
    demand_gap_units: float
    throughput_per_hour: float
    work_in_progress: int
    average_flow_time_seconds: float
    bottleneck_machine_id: str

    # What the line can actually produce per day under continuous demand.
    capacity_units_per_day: int | None = None
    # `capacity / target - 1`, in whole percent.
    capacity_headroom_percent: int | None = None
    # The honest form of "target achieved".
    sustains_target_at_capacity: bool | None = None

    operator_utilization: float | None = None
    operator_constrained: bool = False
    max_buffer_full_fraction: float = Field(
        0.0, description="Worst full-fraction across wired buffers — the flow-health headline."
    )
    total_upstream_blocked_seconds: float = 0.0


class VerifiedStrategyOption(BaseModel):
    """One complete, simulation-verified engineering strategy."""

    model_config = {"frozen": True}

    strategy_id: str
    family: OptimizationStrategyFamily
    # A DISPLAY label and nothing else.
    label: str = Field(..., description="Short human name for display, e.g. 'Option 2'.")
    title: str = Field(..., description="Deterministic one-line description of the approach.")

    requirements: PlanningRequirements = Field(
        ..., description="The exact constraints this strategy was planned under — its audit record."
    )
    metrics: StrategyMetrics
    actions: StrategyActionSummary
    cost: StrategyCostProfile

    operationally_verified: bool = Field(
        ...,
        description=(
            "True when a real simulation produced this strategy's KPIs. Independent of cost: "
            "an unpriced plan can be perfectly verified as engineering (Phase 8B section 7)."
        ),
    )
    commercially_complete: bool = Field(
        ..., description="True when no cost component is still unknown. Mirrors StrategyCostProfile.commercially_complete."
    )

    rationale: str = Field(..., description="Deterministic template over verified values. Never LLM output.")
    tradeoffs: list[str] = Field(default_factory=list, description="Deterministic, comparative statements.")
    warnings: list[str] = Field(default_factory=list)


# Search budget


class StrategySearchBudget(BaseModel):
    """Hard bounds on the arena's search (Phase 8B section 5)."""

    model_config = {"frozen": True}

    max_strategy_families: int = Field(6, ge=1, le=12)
    max_actions_per_strategy: int = Field(4, ge=1, le=10, description="Accepted interventions per strategy.")
    max_total_simulations: int = Field(
        400, ge=1, description="Ceiling on simulations across the whole arena; the search stops early rather than exceeding it."
    )
    include_hybrid: bool = True


class StrategySearchStats(BaseModel):
    """What the search actually cost, for observability (section 26)."""

    model_config = {"frozen": True}

    families_attempted: int = 0
    strategies_retained: int = 0
    strategies_discarded: int = 0
    simulations_run: int = 0
    budget_exhausted: bool = False
    cache_hits: int = 0
    elapsed_seconds: float = 0.0


# Pareto


class StrategyFrontiers(BaseModel):
    """Two frontiers, deliberately not one (Phase 8B section 8)."""

    model_config = {"frozen": True}

    commercially_complete_frontier: list[str] = Field(default_factory=list)
    operational_frontier: list[str] = Field(default_factory=list)
    dominated_by: dict[str, list[str]] = Field(
        default_factory=dict, description="strategy_id -> ids that dominate it on the OPERATIONAL frontier."
    )
    commercial_dimensions: list[str] = Field(default_factory=list)
    operational_dimensions: list[str] = Field(default_factory=list)


# Arena result


class StrategyArenaResult(BaseModel):
    """Everything one arena exploration produced."""

    model_config = {"frozen": True}

    product_id: str
    baseline_metrics: StrategyMetrics
    strategies: list[VerifiedStrategyOption] = Field(default_factory=list)
    frontiers: StrategyFrontiers
    recommended_strategy_id: str | None = Field(
        None,
        description=(
            "The option a careful engineer would look at FIRST — goal met, then commercially "
            "complete, then fewer changes, then lower known CAPEX. Deliberately not a score: "
            "it is a deterministic sort, and every other option stays visible."
        ),
    )
    stats: StrategySearchStats
    families_without_options: list[str] = Field(
        default_factory=list,
        description="Families the evidence did not support, or that produced nothing. Reported rather than hidden.",
    )
    summary: str = Field("", description="Deterministic one-line overview.")


# Comparison


class StrategyMetricDelta(BaseModel):
    model_config = {"frozen": True}

    metric: str
    label: str
    value_a: float | int | bool | str | None = None
    value_b: float | int | bool | str | None = None
    delta: float | None = Field(None, description="B minus A. None whenever either side is unknown or non-numeric.")
    unit: str | None = None


class StrategyComparison(BaseModel):
    """A fully deterministic comparison of two verified strategies."""

    model_config = {"frozen": True}

    strategy_a_id: str
    strategy_b_id: str
    label_a: str
    label_b: str
    family_a: OptimizationStrategyFamily
    family_b: OptimizationStrategyFamily

    metrics: list[StrategyMetricDelta] = Field(default_factory=list)
    cost_rows: list[StrategyMetricDelta] = Field(
        default_factory=list, description="One row per CostCategory, never summed across categories."
    )
    machines_only_in_a: list[str] = Field(default_factory=list)
    machines_only_in_b: list[str] = Field(default_factory=list)
    information_gaps_a: list[InformationGap] = Field(default_factory=list)
    information_gaps_b: list[InformationGap] = Field(default_factory=list)
    comparable_on_cost: bool = Field(
        ..., description="False when either side has an unknown cost component — the comparison then states that plainly."
    )
    headline: str = Field("", description="Deterministic sentence stating the primary difference.")
    notes: list[str] = Field(default_factory=list)


# Conversational queries over verified strategy data (section 15)


class StrategyQueryIntent(str, Enum):
    """What a follow-up question is asking of an ALREADY-EXPLORED arena."""

    CHEAPER_OPTION = "CHEAPER_OPTION"
    """"Show me a cheaper option." — rank by KNOWN cost, honestly."""

    NO_NEW_MACHINE = "NO_NEW_MACHINE"
    """"Can we do it without another machine?\""""

    FEWEST_CHANGES = "FEWEST_CHANGES"
    """"Which plan uses the fewest changes?\""""

    COMPARE = "COMPARE"
    """"Compare Plan A and Plan C." — resolved to a StrategyComparison."""

    INFORMATION_NEEDED = "INFORMATION_NEEDED"
    """"What information do we still need before choosing Plan B?\""""

    PROVIDE_COST = "PROVIDE_COST"
    """"An extra shift costs EUR 18k/day." — fills a gap (section 18)."""

    UNRECOGNIZED = "UNRECOGNIZED"
    """Not a strategy question. The caller should handle it normally —
    never guessed at, because a wrong guess answers a question the user
    did not ask with numbers that look authoritative."""


class StrategyQueryAnswer(BaseModel):
    """A deterministic answer to a follow-up about existing strategies."""

    model_config = {"frozen": True}

    intent: StrategyQueryIntent
    answer: str = Field(..., description="Deterministic sentence(s) over verified values.")
    strategy_ids: list[str] = Field(
        default_factory=list, description="The strategies this answer is about, in the order it names them."
    )
    comparison: StrategyComparison | None = Field(
        None, description="Set only for COMPARE — the same deterministic comparison the UI renders."
    )
    information_gaps: list[InformationGap] = Field(default_factory=list)
    cost_inputs: list[UserCostInput] = Field(
        default_factory=list, description="Costs the user supplied in this message (PROVIDE_COST)."
    )
    requires_repricing: bool = Field(
        False,
        description=(
            "True only when supplied costs must be folded back into the cost profiles. "
            "Repricing re-derives money, never engineering — no simulation re-runs."
        ),
    )
    simulations_run: int = Field(
        0, ge=0, description="Always 0: every intent here is answered from existing verified data."
    )
