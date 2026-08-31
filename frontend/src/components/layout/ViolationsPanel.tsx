import { useAppContext } from "../../state/AppContext";
import { stationName } from "../../utils/formatting";

/** Renders backend-verified violations directly (Phase 6B section 6) —
 * never a frontend-invented verdict. Shown only for the draft being
 * edited; the authoritative source is always the last POST
 * /layout/validate response. */
export function ViolationsPanel() {
  const { state } = useAppContext();
  // The machines that define the names. A violation arrives as a list of
  // ids, and an engineer reading "two machines overlap" needs to know which
  // stations — "Assembly 3" is not one they can find on a floor.
  const machines = state.factory?.machines ?? null;
  if (state.editMode !== "EDIT_LAYOUT" || !state.draftLayout) return null;

  const result = state.layoutValidation;

  return (
    <div className="fm-section" data-testid="violations-panel">
      <p className="fm-section__title">Layout Validation</p>
      {result === null ? (
        <p className="fm-empty">Not yet validated — click Validate (or drag a machine to auto-validate).</p>
      ) : (
        <>
          <p className={`fm-badge fm-badge--${result.valid ? "verified" : "bad"}`} data-testid="validation-verdict">
            {result.valid ? "VALID" : `${result.error_count} error(s), ${result.warning_count} warning(s)`}
          </p>
          <ul className="violations-list">
            {result.violations.map((v, i) => (
              <li key={i} className={`violations-list__item violations-list__item--${v.severity.toLowerCase()}`} data-testid={`violation-${v.violation_type}`}>
                <span className={`fm-badge fm-badge--${v.severity === "ERROR" ? "bad" : "unknown"}`}>{v.violation_type}</span>{" "}
                {v.message}
                {(v.machine_ids.length > 0 || v.zone_ids.length > 0) && (
                  <span className="violations-list__refs">
                    {v.machine_ids.map((id) => stationName(id, machines)).join(", ")}
                    {v.machine_ids.length > 0 && v.zone_ids.length > 0 && "; "}
                    {v.zone_ids.join(", ")}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
