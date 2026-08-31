import { useState } from "react";
import { CheckCircle2, ChevronDown, CircleAlert, Factory, Play, Layers } from "lucide-react";
import { useAppContext } from "../../state/AppContext";
import { formatNumber } from "../../utils/formatting";
import { statsFromStrategyMetrics } from "../../utils/executiveSummary";
import { primaryInterventionPhrase, interventionPhrases } from "../../utils/interventionSummary";
import { describeKnownCost } from "../../utils/capex";
import { replaySupport } from "../../utils/replaySupport";
import { planChanges } from "../../utils/planDelta";
import { scenarioWords } from "../../utils/scenario";
import { groupGaps } from "../../utils/informationGaps";

/** Phase 12 §5 — the recommendation, as the one dominant object on the results screen. */
export function RecommendationHero() {
  const { state, openPlayback } = useAppContext();
  const [showChanges, setShowChanges] = useState(false);
  const arena = state.arena;
  const selected = arena?.strategies.find((s) => s.strategy_id === state.selectedStrategyId);
  if (!arena || !selected) return null;

  const capex = describeKnownCost(selected.cost, {
    commerciallyComplete: selected.commercially_complete,
  });
  // Can this plan be rebuilt from the saved project? Decides whether the
  // play action is offered at all once the session is gone.
  const replay = replaySupport(selected.actions);
  const recommended = arena.strategies.find((s) => s.strategy_id === arena.recommended_strategy_id);
  const isRecommended = recommended !== undefined && recommended.strategy_id === selected.strategy_id;

  const before = statsFromStrategyMetrics(arena.baseline_metrics);
  const after = statsFromStrategyMetrics(selected.metrics);
  const headline = primaryInterventionPhrase(selected.actions);
  const changes = interventionPhrases(selected.actions, state.factory?.machines);
  const words = scenarioWords(state);
  // The before -> after pairs. Preferred source is the verified session the
  // simulator produced for this strategy; a REOPENED project does not hold
  // those, so it falls back to the backend's own verified action summary
  // cannot value rather than dropping them. See utils/planDelta.ts.
  const deltas = planChanges(
    state.strategySessions[selected.strategy_id],
    selected.actions,
    state.factory,
  );
  // One line per distinct missing input rather than one per option: the same
  // shift cost blocking four plans is one thing to go and find out.
  const gapGroups = groupGaps(selected.cost.information_gaps);

  return (
    <section
      className={`rec-hero${after.met ? " rec-hero--achieved" : ""}`}
      data-testid="recommendation-hero"
      data-goal-met={after.met}
      aria-labelledby="rec-hero-plan"
    >
      <header className="rec-hero__head">
        <div className="rec-hero__identity">
          <span className="rec-hero__plan" id="rec-hero-plan">
            {selected.label}
          </span>
          {isRecommended ? (
            <span className="rec-hero__tag" data-testid="rec-hero-recommended">
              Recommended
            </span>
          ) : (
            <span className="rec-hero__tag rec-hero__tag--manual" data-testid="rec-hero-not-recommended">
              Your selection · recommended is {recommended?.label}
            </span>
          )}
        </div>
        {headline && (
          <p className="rec-hero__intervention" data-testid="rec-hero-intervention">
            {headline}
          </p>
        )}
      </header>

      {/* The result, as one sentence in numbers. */}
      <div className="rec-hero__result">
        <div className="rec-hero__figure rec-hero__figure--from">
          <span className="fm-label" data-testid="rec-hero-baseline-label">
            {words.baselineShort}
          </span>
          <span className="rec-hero__value fm-mono" data-testid="rec-hero-before">
            {formatNumber(before.completedUnits)}
          </span>
          <span className="rec-hero__unit">units/day</span>
        </div>

        <span className="rec-hero__arrow" aria-hidden="true" />

        <div className="rec-hero__figure rec-hero__figure--to">
          <span className="fm-label">With {selected.label}</span>
          <span className="rec-hero__value rec-hero__value--hero fm-mono" data-testid="rec-hero-after">
            {formatNumber(after.completedUnits)}
          </span>
          <span className="rec-hero__unit">units/day</span>
        </div>

        <div className="rec-hero__verdict">
          {after.met && after.sustainsTarget === false ? (
            /* The plan reaches the target only because the simulator released
               exactly the target and the line kept up. Simulated at continuous
               demand it produces less. "Target achieved" would be false. */
            <>
              <span className="rec-hero__verdict-line rec-hero__verdict-line--short" data-testid="rec-hero-verdict">
                <CircleAlert size={18} strokeWidth={2.2} aria-hidden="true" />
                No margin — reaches target only at full speed
              </span>
              <span className="rec-hero__verdict-sub fm-mono" data-testid="rec-hero-capacity">
                Line capacity {formatNumber(after.capacityUnits ?? 0)}/day against{" "}
                {formatNumber(after.targetUnits)} required
              </span>
            </>
          ) : after.met ? (
            <>
              <span className="rec-hero__verdict-line" data-testid="rec-hero-verdict">
                <CheckCircle2 size={18} strokeWidth={2.2} aria-hidden="true" />
                Target achieved
              </span>
              <span className="rec-hero__verdict-sub fm-mono" data-testid="rec-hero-capacity">
                {after.capacityHeadroomPercent != null
                  ? `Line capacity ${formatNumber(after.capacityUnits ?? 0)}/day — ${after.capacityHeadroomPercent}% headroom`
                  : `${formatNumber(after.targetUnits)} units/day required`}
              </span>
            </>
          ) : (
            <>
              <span className="rec-hero__verdict-line rec-hero__verdict-line--short" data-testid="rec-hero-verdict">
                <CircleAlert size={18} strokeWidth={2.2} aria-hidden="true" />
                Target not reached
              </span>
              <span className="rec-hero__verdict-sub fm-mono">
                {formatNumber(after.gapUnits)} units/day short
              </span>
            </>
          )}
        </div>
      </div>

      {/* Facts a decision actually turns on: what it changes, what it buys,
          what it is known to cost. Three columns, no boxes — spacing and a
          single hairline carry the grouping. */}
      <dl className="rec-hero__facts">
        <div className="rec-hero__fact">
          <dt className="fm-label">
            <Layers size={13} strokeWidth={2} aria-hidden="true" /> Changes
          </dt>
          <dd data-testid="rec-hero-changes">
            {changes.map((change) => (
              <span key={change} className="rec-hero__change">
                {change}
              </span>
            ))}
            {/* §4 — "3 changes" was where the explanation stopped. */}
            {deltas.changes.length > 0 && (
              <button
                type="button"
                className="rec-hero__changes-toggle"
                aria-expanded={showChanges}
                onClick={() => setShowChanges((open) => !open)}
                data-testid="rec-hero-changes-toggle"
              >
                <ChevronDown size={12} strokeWidth={2.4} aria-hidden="true" />
                {showChanges ? "Hide changes" : "View changes"}
              </button>
            )}
          </dd>
        </div>

        <div className="rec-hero__fact">
          <dt className="fm-label">
            <Factory size={13} strokeWidth={2} aria-hidden="true" /> New machines
          </dt>
          <dd className="fm-mono rec-hero__fact-value" data-testid="rec-hero-machines">
            {selected.actions.added_machine_count}
          </dd>
        </div>

        <div className="rec-hero__fact">
          <dt className="fm-label">Known CAPEX</dt>
          <dd className="fm-mono rec-hero__fact-value" data-testid="rec-hero-capex">
            {/* Never let €0 read as free — the plan whose only cost is an
                extra shift has known_capex 0 and a real operating cost,
                unknown before the engineer supplies it and large after.
                The shared rule in utils/capex owns that decision so every
                panel states it the same way. */}
            {capex.amount}
            {capex.qualifier && (
              <span className="rec-hero__capex-partial" data-testid="rec-hero-capex-partial">
                partial — operating cost not yet known
              </span>
            )}
            {/* G14 — the money CAPEX does not describe, rendered INSIDE the
                same fact as the CAPEX figure rather than as a sibling.
                As a sibling it was a fifth item in a four-column grid, so it
                wrapped to the next row and left "KNOWN CAPEX €0" sitting
                alone at the end of the first one — which is the misreading
                this fix exists to prevent. Kept together, the two figures
                are read as one answer. Never summed. */}
            {capex.otherDimensions.map((dimension) => (
              <span
                className="rec-hero__cost-extra"
                key={dimension.category}
                data-testid={`rec-hero-cost-${dimension.category.toLowerCase()}`}
              >
                {dimension.amount}
                <span className="rec-hero__cost-extra-label">{dimension.label}</span>
              </span>
            ))}
          </dd>
        </div>

      </dl>

      {showChanges && deltas.changes.length > 0 && (
        <div className="plan-delta" data-testid="rec-hero-change-list">
          <p className="plan-delta__title">
            What {selected.label} changes, against the {words.baselineShort.toLowerCase()}
          </p>
          <dl className="plan-delta__list">
            {deltas.changes.map((change) => (
              <div key={change.key} className="plan-delta__row" data-testid={`plan-delta-${change.key}`}>
                <dt className="plan-delta__subject">
                  {change.subject}
                  <span className="plan-delta__property">{change.property}</span>
                </dt>
                <dd className="plan-delta__values fm-mono">
                  <span className="plan-delta__before">{change.before}</span>
                  <span className="plan-delta__arrow" aria-hidden="true">
                    →
                  </span>
                  <span className="plan-delta__after">{change.after}</span>
                  <span className="fm-visually-hidden">
                    changes from {change.before} to {change.after}
                  </span>
                </dd>
              </div>
            ))}
          </dl>
          {deltas.unvalued.length > 0 && (
            <p className="plan-delta__unvalued" data-testid="plan-delta-unvalued">
              This plan also changes {deltas.unvalued.join(" and ")}. The per-station values are
              held in the simulation run that produced it — re-run the comparison to see them.
            </p>
          )}
          <p className="plan-delta__note">
            {deltas.source === "SESSION"
              ? "Read from the factory model this plan's simulation actually ran on."
              : "Read from the verified change summary this plan's simulation produced."}
          </p>
        </div>
      )}

      <footer className="rec-hero__foot">
        <div className="rec-hero__actions">
          {/* `openPlayback()` with no argument on purpose: it resolves the
              stage currently on screen, so the twin, the KPIs and this
              playback can never describe different scenarios (Phase 8C
              §28, and §19 of this phase — state continuity). The
              Before/After switch lives inside the playback bar. */}
          {/* Available from a REOPENED project too, not only while an
              exploration session is live. Playback is a visualisation of an
              already-verified result, and gating it on the transient session
              took it away from every saved project the moment the browser was
              reloaded — the numbers came back and the ability to watch them
              did not.
              Still gated on the plan being rebuildable from what was saved:
              `replaySupport` mirrors the backend rule, so a plan whose lever
              the summary does not fully record is not offered rather than
              offered and refused. */}
          {(state.session || replay.replayable) && !state.playback.active && (
            <button
              type="button"
              className="fm-btn rec-hero__cta"
              onClick={() => void openPlayback()}
              data-testid="rec-hero-play"
            >
              <Play size={15} strokeWidth={2.4} fill="currentColor" aria-hidden="true" />
              Play baseline / selected plan
            </button>
          )}
          <button
            type="button"
            className="fm-btn-secondary rec-hero__alt-link"
            onClick={() =>
              document
                .getElementById("executive-alternatives")
                ?.scrollIntoView({ behavior: "smooth", block: "start" })
            }
            data-testid="rec-hero-compare"
          >
            Compare {arena.strategies.length - 1} alternative
            {arena.strategies.length - 1 === 1 ? "" : "s"}
          </button>
        </div>
      </footer>

      {gapGroups.length > 0 && (
        <div className="rec-hero__gaps" data-testid="rec-hero-gaps">
          <p className="rec-hero__gaps-title">
            <CircleAlert size={14} strokeWidth={2} aria-hidden="true" />
            Commercial information still required
          </p>
          {/* Grouped and de-duplicated by what an engineer would go and do about it. */}
          {gapGroups.map((group) => (
            <div key={group.group} className="rec-hero__gap-group">
              <p className="fm-label">{group.group}</p>
              <ul>
                {group.items.map((item) => (
                  <li key={item.type} data-testid={`rec-hero-gap-${item.type}`}>
                    <strong>{item.title}</strong> — {item.description}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
