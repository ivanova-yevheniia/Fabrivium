import type { StrategyArenaResult } from "../../api/types";

/** What the search actually covered. */
export function SearchSpace({ arena }: { arena: StrategyArenaResult }) {
  const { stats, strategies, families_without_options } = arena;
  const verified = strategies.length;

  return (
    <details className="search-space" data-testid="search-space">
      <summary data-testid="search-space-summary">
        Highest-ranked option among {verified} explored {verified === 1 ? "candidate" : "candidates"}
        {" — how this was searched"}
      </summary>

      <div className="search-space__body">
        <p className="search-space__claim" data-testid="search-space-claim">
          Fabrivium compares candidates; it does not prove optimality. Every option below was
          generated from the baseline, simulated with the same deterministic engine, and ranked by
          a fixed rule — goal met first, then commercially complete, then fewer changes, then lower
          known cost.
        </p>

        <dl className="search-space__grid">
          <div>
            <dt>Strategy families attempted</dt>
            <dd className="fm-mono" data-testid="search-space-families">
              {stats.families_attempted}
            </dd>
          </div>
          <div>
            <dt>Options retained</dt>
            <dd className="fm-mono" data-testid="search-space-retained">
              {stats.strategies_retained}
            </dd>
          </div>
          <div>
            <dt>Options discarded</dt>
            <dd className="fm-mono" data-testid="search-space-discarded">
              {stats.strategies_discarded}
            </dd>
          </div>
          <div>
            <dt>Simulations run</dt>
            <dd className="fm-mono" data-testid="search-space-simulations">
              {stats.simulations_run}
            </dd>
          </div>
        </dl>

        {/* A truncated search that does not say so reads as an exhaustive one. */}
        {stats.budget_exhausted && (
          <p className="search-space__note" data-testid="search-space-truncated">
            The search stopped at its simulation budget, so the space was not explored to
            exhaustion. More candidates may exist.
          </p>
        )}

        {families_without_options.length > 0 && (
          <p className="search-space__note" data-testid="search-space-empty-families">
            Produced no viable option here: {families_without_options.join(", ")}. Reported rather
            than hidden — a family that yielded nothing is a finding about this line.
          </p>
        )}
      </div>
    </details>
  );
}
