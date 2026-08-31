import { MoveRight } from "lucide-react";
import { useAppContext } from "../../state/AppContext";

/** WHY THE RECOMMENDATION CHANGED. */
export function RefinementTrace() {
  const { state } = useAppContext();
  const trace = state.refinementTrace;
  if (!trace) return null;

  return (
    <section className="refine-trace" data-testid="refinement-trace">
      <p className="refine-trace__tag">Refinement applied</p>

      <div className="refine-trace__body">
        <div className="refine-trace__constraint">
          <p className="fm-label">Constraint</p>
          <p className="refine-trace__request" data-testid="refinement-trace-request">
            “{trace.request}”
          </p>
        </div>

        <div className="refine-trace__outcome">
          <p className="fm-label">Recommendation</p>
          {trace.changed ? (
            <p className="refine-trace__move" data-testid="refinement-trace-change">
              <span className="refine-trace__previous">{trace.previousPlan}</span>
              <MoveRight size={14} strokeWidth={2.2} aria-hidden="true" />
              <span className="refine-trace__current">{trace.currentPlan}</span>
            </p>
          ) : (
            <p className="refine-trace__move" data-testid="refinement-trace-unchanged">
              <span className="refine-trace__current">{trace.currentPlan}</span>
              <span className="refine-trace__same">still recommended under this constraint</span>
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
