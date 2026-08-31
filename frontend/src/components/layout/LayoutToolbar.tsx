import { useAppContext } from "../../state/AppContext";

/** Phase 6B section 7/8 — explicit VIEW/EDIT_LAYOUT mode toggle plus the
 * Validate/Apply/Reset Draft draft-lifecycle buttons, and rotation
 * controls for the selected machine (section 5). Never mutates a
 * historical snapshot — editing always operates on `state.draftLayout`. */
export function LayoutToolbar() {
  const { state, setEditMode, enterEditMode, resetDraft, validateDraft, applyDraft, rotateMachine } = useAppContext();

  const canApply = Boolean(state.draftLayout) && state.layoutValidation !== null && state.layoutValidation.error_count === 0;
  const selectedPlacement = state.draftLayout?.placements.find((p) => p.machine_id === state.selectedMachineId) ?? null;

  return (
    <div className="layout-toolbar" data-testid="layout-toolbar">
      <div className="layout-toolbar__group">
        <button
          type="button"
          className={`fm-btn-secondary ${state.editMode === "VIEW" ? "fm-btn-secondary--active" : ""}`}
          onClick={() => setEditMode("VIEW")}
          data-testid="mode-view-button"
        >
          VIEW
        </button>
        <button
          type="button"
          className={`fm-btn-secondary ${state.editMode === "EDIT_LAYOUT" ? "fm-btn-secondary--active" : ""}`}
          onClick={enterEditMode}
          disabled={!state.factory}
          data-testid="mode-edit-button"
        >
          EDIT LAYOUT
        </button>
      </div>

      {state.editMode === "EDIT_LAYOUT" && (
        <div className="layout-toolbar__group">
          <button
            type="button"
            className="fm-btn-secondary"
            onClick={() => void validateDraft()}
            disabled={!state.draftLayout || state.layoutValidating}
            data-testid="validate-button"
          >
            {state.layoutValidating ? "Validating…" : "Validate"}
          </button>
          <button type="button" className="fm-btn" onClick={applyDraft} disabled={!canApply} data-testid="apply-button">
            Apply
          </button>
          <button
            type="button"
            className="fm-btn-secondary"
            onClick={resetDraft}
            disabled={!state.draftLayout}
            data-testid="reset-draft-button"
          >
            Reset Draft
          </button>
        </div>
      )}

      {state.editMode === "EDIT_LAYOUT" && selectedPlacement && (
        <div className="layout-toolbar__group">
          <span className="fm-label">Rotate {state.selectedMachineId}</span>
          <button
            type="button"
            className="fm-btn-secondary"
            onClick={() => rotateMachine(selectedPlacement.machine_id, selectedPlacement.rotation_deg - 90)}
            data-testid="rotate-minus-90"
          >
            -90°
          </button>
          <button
            type="button"
            className="fm-btn-secondary"
            onClick={() => rotateMachine(selectedPlacement.machine_id, selectedPlacement.rotation_deg + 90)}
            data-testid="rotate-plus-90"
          >
            +90°
          </button>
          <input
            type="number"
            className="layout-toolbar__rotation-input"
            aria-label="Rotation degrees"
            value={selectedPlacement.rotation_deg}
            onChange={(e) => {
              const value = Number(e.target.value);
              if (!Number.isNaN(value)) rotateMachine(selectedPlacement.machine_id, value);
            }}
            data-testid="rotation-input"
          />
        </div>
      )}

      {state.isDirty && (
        <span className="fm-badge fm-badge--unknown" data-testid="dirty-indicator">
          Unsaved draft
        </span>
      )}
    </div>
  );
}
