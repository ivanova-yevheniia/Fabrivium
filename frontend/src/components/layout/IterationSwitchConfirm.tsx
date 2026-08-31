import { useAppContext } from "../../state/AppContext";

/** Phase 6B section 11: switching timeline stage while an uncommitted
 * draft exists must warn explicitly, never silently discard. */
export function IterationSwitchConfirm() {
  const { state, confirmIterationSwitch, cancelIterationSwitch } = useAppContext();
  if (state.pendingIterationSelection === null) return null;

  return (
    <div className="fm-error-banner" role="alertdialog" data-testid="discard-draft-confirm">
      <strong>Discard unsaved layout draft?</strong> Switching stages will discard your uncommitted edits.
      <div style={{ marginTop: 6, display: "flex", gap: 8 }}>
        <button type="button" className="fm-btn" onClick={confirmIterationSwitch} data-testid="confirm-discard-button">
          Discard &amp; Switch
        </button>
        <button type="button" className="fm-btn-secondary" onClick={cancelIterationSwitch} data-testid="cancel-discard-button">
          Cancel
        </button>
      </div>
    </div>
  );
}
