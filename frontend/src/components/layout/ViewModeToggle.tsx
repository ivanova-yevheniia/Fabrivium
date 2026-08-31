import { useAppContext } from "../../state/AppContext";

/** Phase 6C section 10 — 2D/3D is a view choice only; selecting it never
 * touches selectedMachineId/selectedIteration/editMode/draftLayout. */
export function ViewModeToggle() {
  const { state, setViewMode } = useAppContext();

  return (
    <div className="layout-toolbar__group" data-testid="view-mode-toggle">
      <button
        type="button"
        className={`fm-btn-secondary ${state.viewMode === "2D" ? "fm-btn-secondary--active" : ""}`}
        onClick={() => setViewMode("2D")}
        data-testid="view-mode-2d-button"
      >
        2D
      </button>
      <button
        type="button"
        className={`fm-btn-secondary ${state.viewMode === "3D" ? "fm-btn-secondary--active" : ""}`}
        onClick={() => setViewMode("3D")}
        data-testid="view-mode-3d-button"
      >
        3D
      </button>
    </div>
  );
}
