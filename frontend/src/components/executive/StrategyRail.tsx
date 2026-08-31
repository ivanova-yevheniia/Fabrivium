import { useAppContext } from "../../state/AppContext";
import { StrategyCard } from "../strategy/StrategyCard";

/**
 * The alternatives block: every verified option the arena produced, laid
 * out so a judge can compare them without scrolling anything sideways.
 *
 * Phase 12 §6 — finding and change.
 *
 * Finding: the rail was `display: flex; overflow-x: auto` with 240px
 * cards. Measured in the browser at 1366x768 its content was 1691px wide
 * inside a 1052px box, so a native horizontal scrollbar appeared under the
 * cards and two of the five plans — including Plan D, the OTHER option
 * that reaches the target — were off-screen. Sideways scrolling to
 * discover an option is not an acceptable competition interaction.
 *
 * Change: a responsive grid (`repeat(auto-fit, minmax(210px, 1fr))`). At
 * 1366 all five options fit on one row; narrower viewports wrap to a
 * second row instead of producing a scrollbar. No option is hidden, no
 * carousel state to get lost in, nothing to scroll.
 *
 * Phase 9A/9B semantics kept exactly:
 *
 * 11A: the recommended option is rendered FIRST. This reorders one
 *      component's JSX and nothing else — `arena.strategies`, the
 *      backend's deterministic ranking, `recommended_strategy_id` and
 *      Engineering View's `StrategyArenaPanel` are untouched. The same
 *      options, in the same evaluation order, presented recommended-first.
 *
 * 11B: when the user selects a plan that is not the recommended one, the
 *      screen must not let "the one I'm looking at" be mistaken for "the
 *      one the system recommends". The notice states both, explicitly, and
 *      only when they actually differ.
 *
 * Phase 11: the partition has THREE groups — the recommended option, any
 *      OTHER option that also reaches the target, then the options that
 *      fall short. With the grid this no longer decides what is visible,
 *      but it still decides reading order, and "which options actually
 *      meet the target?" stays answerable left-to-right.
 */
export function StrategyRail() {
  const { state, selectStrategy, compareWithStrategy } = useAppContext();
  const arena = state.arena;
  if (!arena) return null;

  const recommendedId = arena.recommended_strategy_id;
  const recommended = arena.strategies.find((s) => s.strategy_id === recommendedId);
  const selected = arena.strategies.find((s) => s.strategy_id === state.selectedStrategyId);

  // Display order only — a stable partition, never a re-ranking. Every
  // option that was in `arena.strategies` is still here, and within each
  // group the relative order is exactly the backend's.
  const rest = arena.strategies.filter((s) => s.strategy_id !== recommendedId);
  const ordered = recommended
    ? [recommended, ...rest.filter((s) => s.metrics.goal_met), ...rest.filter((s) => !s.metrics.goal_met)]
    : arena.strategies;

  const viewingDiffersFromRecommended =
    recommended !== undefined && selected !== undefined && selected.strategy_id !== recommended.strategy_id;

  const targetMetCount = arena.strategies.filter((s) => s.metrics.goal_met).length;

  return (
    <section className="strategy-rail" data-testid="strategy-rail" id="executive-alternatives">
      <header className="strategy-rail__head">
        <h2 className="fm-section__title">All verified options</h2>
        {/* States the comparison up front so the grid does not have to be
            read card by card to answer "how many actually work?". Both
            figures are counted from the backend's own `goal_met` flags. */}
        <p className="strategy-rail__summary">
          {targetMetCount} of {arena.strategies.length} reach the target
        </p>
      </header>

      {viewingDiffersFromRecommended && (
        <p className="strategy-rail__selection-notice" data-testid="strategy-selection-notice">
          <span>
            Recommended: <strong data-testid="strategy-selection-notice-recommended">{recommended.label}</strong>
          </span>
          <span className="strategy-rail__selection-sep">·</span>
          <span>
            Currently viewing: <strong data-testid="strategy-selection-notice-viewing">{selected.label}</strong>
          </span>
        </p>
      )}

      <div className="strategy-rail__cards">
        {ordered.map((option) => (
          <StrategyCard
            key={option.strategy_id}
            option={option}
            selected={option.strategy_id === state.selectedStrategyId}
            recommended={option.strategy_id === recommendedId}
            onSelect={() => selectStrategy(option.strategy_id)}
            onCompare={arena.strategies.length > 1 ? () => void compareWithStrategy(option.strategy_id) : undefined}
            comparing={state.comparing}
            allOptions={arena.strategies}
          />
        ))}
      </div>
    </section>
  );
}
