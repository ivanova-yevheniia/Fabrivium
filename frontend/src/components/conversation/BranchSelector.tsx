import { useAppContext } from "../../state/AppContext";
import { formatCurrency } from "../../utils/formatting";

/** Phase 7C section 18 — the alternatives this conversation has produced. */
export function BranchSelector() {
  const { state, selectBranch, compareWithBranch } = useAppContext();
  const branches = state.conversation?.branches ?? [];

  if (branches.length === 0) return null;

  return (
    <div className="fm-section" data-testid="branch-selector">
      <p className="fm-section__title">Options</p>
      <div className="branch-list">
        {branches.map((branch) => {
          const selected = branch.branch_id === state.selectedBranchId;
          const reached = branch.status === "GOAL_REACHED";
          return (
            <div
              key={branch.branch_id}
              className={`branch-card${selected ? " branch-card--selected" : ""}`}
              data-testid={`branch-card-${branch.branch_id}`}
              data-selected={selected}
            >
              <button
                type="button"
                className="branch-card__main"
                onClick={() => selectBranch(branch.branch_id)}
                aria-pressed={selected}
              >
                <span className="branch-card__head">
                  <span className="branch-card__label">{branch.label}</span>
                  <span className={`fm-badge fm-badge--${reached ? "verified" : "bad"}`}>
                    {reached ? "Target met" : "Target unmet"}
                  </span>
                </span>
                <span className="branch-card__capex fm-mono">
                  {formatCurrency(branch.metrics.cumulative_known_capex)}
                </span>
                <span className="branch-card__summary">{branch.summary}</span>
              </button>
              {branches.length > 1 && !selected && (
                <button
                  type="button"
                  className="branch-card__compare"
                  onClick={() => void compareWithBranch(branch.branch_id)}
                  disabled={state.comparing}
                  title={`Compare ${branch.label} with the option currently shown`}
                >
                  Compare
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
