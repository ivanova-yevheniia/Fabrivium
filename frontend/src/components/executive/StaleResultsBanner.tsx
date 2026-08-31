import { useState } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { useAppContext } from "../../state/AppContext";
import type { StaleReport } from "../../api/projects";
import type { StaleResults } from "../../state/types";

/** Results that no longer answer the current inputs. */

const RESULT_LABEL: Record<string, string> = {
  // The concept-level dependency graph (POST /concept/change-impact).
  SIMULATION_CONFIG: "the simulated configuration",
  BASELINE_RESULT: "baseline throughput",
  BOTTLENECK: "the limiting stage",
  STRATEGY_EVALUATION: "plan comparison",
  RECOMMENDATION: "the recommendation",
  SENSITIVITY: "sensitivity results",
  STATION_REQUIREMENT: "station requirements",
  // The project-level graph (P0). Same vocabulary where the two overlap, so
  // an engineer reads one set of names regardless of which produced the
  // report.
  PRODUCT_FACTS: "product facts",
  PROCESS_PROPOSAL: "the proposed manufacturing process",
  REQUIREMENT_COVERAGE: "requirement coverage",
  CONCEPT: "the factory concept",
  SIMULATION_VERIFICATION: "the verified simulation",
  STRATEGIES: "the explored plans",
  SELECTED_PLAN: "the selected plan",
  EQUIPMENT_REQUIREMENTS: "station equipment requirements",
  COMMERCIAL_COMPARISON: "the commercial comparison",
  LAYOUT_VALIDATION: "layout validation",
  LAYOUT: "the layout",
  SIEMENS_HANDOFF: "the Siemens export",
};

function label(node: string): string {
  return RESULT_LABEL[node] ?? node.replace(/_/g, " ").toLowerCase();
}

/** The project's own staleness report, in the shape this banner renders. */
function fromProject(report: StaleReport | null): StaleResults | null {
  if (!report || report.stale.length === 0) return null;

  const reasons: string[] = [];
  for (const item of report.stale) {
    for (const reason of item.reasons) {
      if (!reasons.includes(reason)) reasons.push(reason);
    }
  }

  return {
    stale: report.stale.map((item) => item.artifact),
    unaffected: report.current,
    summary: report.summary,
    changes: reasons,
  };
}

/** The distinct actions the report asks for, in the order it lists them. */
function actionsOf(report: StaleReport | null): string[] {
  const actions: string[] = [];
  for (const item of report?.stale ?? []) {
    if (!actions.includes(item.action)) actions.push(item.action);
  }
  return actions;
}

export function StaleResultsBanner() {
  const { state, buildConceptFactory } = useAppContext();
  const [open, setOpen] = useState(false);

  // Whichever graph is in charge answers BOTH ways. Falling back to the
  // concept-level result whenever the project reported nothing stale put a
  // "Re-verify" banner directly above a green VERIFIED badge — two graphs
  // disagreeing in the same viewport, which is worse than either of them
  // being wrong on its own. Inside a project the project decides, including
  const stale = state.project.id ? fromProject(state.project.staleness) : state.staleResults;
  const actions = state.project.id ? actionsOf(state.project.staleness) : [];

  if (!stale || stale.stale.length === 0) return null;

  // "Re-verify" rebuilds the concept and re-runs the simulator. That is the
  // right action when the simulation is what went out of date, and the wrong
  // one when a coverage link did — so the button appears only when it is
  const rebuildIsTheAction = actions.length === 0 || actions.some((a) => /verif|concept/i.test(a));

  return (
    <div className="stale-banner" role="status" data-testid="stale-results-banner">
      <div className="stale-banner__head">
        <AlertTriangle size={15} strokeWidth={2.2} aria-hidden="true" />
        <div className="stale-banner__text">
          <p className="stale-banner__title">
            These results were computed before the last change and have not been re-verified
          </p>
          <p className="stale-banner__detail" data-testid="stale-results-list">
            Out of date: {stale.stale.map(label).join(", ")}.
            {actions.length > 0 && ` Needed: ${actions.join(" · ")}.`}
          </p>
        </div>
        {rebuildIsTheAction ? (
          <button
            type="button"
            className="fm-btn-primary"
            onClick={() => void buildConceptFactory()}
            data-testid="stale-results-reverify"
          >
            <RefreshCw size={13} strokeWidth={2.2} aria-hidden="true" />
            Re-verify
          </button>
        ) : (
          <span className="stale-banner__detail" data-testid="stale-results-action">
            {actions.join(" · ")}
          </span>
        )}
      </div>

      <button
        type="button"
        className="fm-btn-tertiary stale-banner__more"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        data-testid="stale-results-toggle"
      >
        {open ? "Hide what changed" : "What changed?"}
      </button>

      {open && (
        <div className="stale-banner__body" data-testid="stale-results-detail">
          <p className="stale-banner__subtitle">Changed inputs</p>
          <ul>
            {stale.changes.map((change) => (
              <li key={change}>{change}</li>
            ))}
          </ul>

          {stale.unaffected.length > 0 && (
            <>
              <p className="stale-banner__subtitle">
                Unaffected — these cannot have changed
              </p>
              <ul data-testid="stale-results-unaffected">
                {stale.unaffected.map((node) => (
                  <li key={node}>{label(node)}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}
