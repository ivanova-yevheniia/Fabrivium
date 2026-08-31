import type { AppState } from "../state/types";
import type { StrategyMetrics } from "../api/types";

/** BASELINE / SELECTED PLAN — the words the comparison is allowed to use. */

export interface ScenarioWords {
  /** True when the factory being compared does not exist yet. */
  greenfield: boolean;
  /** The unchanged state, e.g. "Baseline concept" / "Today". */
  baseline: string;
  /** Short form for a tight label, e.g. "Baseline" / "Today". */
  baselineShort: string;
  /** Under the baseline figure, e.g. "as the concept stands". */
  baselineQualifier: string;
  /** The state with a plan applied, e.g. "Selected plan" / "With the plan". */
  selected: string;
  /** Short form. */
  selectedShort: string;
}

const GREENFIELD: ScenarioWords = {
  greenfield: true,
  baseline: "Baseline concept",
  baselineShort: "Baseline",
  baselineQualifier: "the concept as drawn, before any plan",
  selected: "Selected plan",
  selectedShort: "Selected plan",
};

const BROWNFIELD: ScenarioWords = {
  greenfield: false,
  baseline: "Today, without changes",
  baselineShort: "Today",
  baselineQualifier: "the line as it runs now",
  selected: "Selected plan",
  selectedShort: "Selected plan",
};

/** Which vocabulary this session's comparison should use. */
export function scenarioWords(state: Pick<AppState, "concept">): ScenarioWords {
  return state.concept.draft !== null ? GREENFIELD : BROWNFIELD;
}

/** "BASELINE CONCEPT → PLAN A", or "TODAY → PLAN A" on a real factory. */
export function transitionLabel(words: ScenarioWords, planLabel: string): string {
  return `${words.baselineShort} → ${planLabel}`;
}

/** The scenario a panel should describe right now. */
export interface ActiveScenario {
  /** The name to put in a heading, e.g. "Baseline concept" or "Plan B". */
  name: string;
  /** True when the baseline run is the one being described. */
  isBaseline: boolean;
  /** True when this is following a running playback rather than the
   * selection — the case the two headings used to disagree about. */
  fromPlayback: boolean;
  /** The verified metrics for this scenario, so scenario-dependent wording
   * (limiting stage, output, gap) follows the same run as the name. Null for
   * an intermediate planning iteration, which has no arena-level metrics —
   * better nothing than the wrong plan's figures. */
  metrics: StrategyMetrics | null;
}

export function activeScenario(
  state: Pick<AppState, "concept" | "arena" | "selectedStrategyId" | "playback">,
): ActiveScenario {
  const words = scenarioWords(state);
  const arena = state.arena;
  const selected = arena?.strategies.find((s) => s.strategy_id === state.selectedStrategyId) ?? null;

  const playing = state.playback.active && state.playback.stageKey !== null;
  const onBaseline = playing && state.playback.stageKey === "baseline";

  if (onBaseline) {
    return {
      name: words.baseline,
      isBaseline: true,
      fromPlayback: true,
      metrics: arena?.baseline_metrics ?? null,
    };
  }

  // Playing a non-baseline stage, or nothing playing: the selected plan is
  // the subject either way. An intermediate iteration (reachable only from
  // the Engineering timeline) keeps the selected plan's name but carries no
  // metrics of its own.
  return {
    name: selected ? selected.label : words.baselineShort.toLowerCase(),
    isBaseline: selected === null,
    fromPlayback: Boolean(playing),
    metrics: selected ? selected.metrics : (arena?.baseline_metrics ?? null),
  };
}
