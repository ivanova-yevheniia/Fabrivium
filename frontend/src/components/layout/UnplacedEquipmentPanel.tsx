import { useAppContext } from "../../state/AppContext";
import { assetLabel, assetVisualKind } from "../workspace/machineVisual";
import { unplacedMachines } from "../../utils/layoutDraft";

/** "Unplaced equipment" workflow (Phase 6B section 9): machines that
 * exist in the Factory but have no placement yet — e.g. a
 * PURCHASE_CANDIDATE/CUSTOM_DESIGN proxy under evaluation. Placing one
 * drops it at a fixed default position in factory-space; the user then
 * drags/rotates/validates/applies exactly like any other machine. */
export function UnplacedEquipmentPanel() {
  const { state, placeMachine } = useAppContext();
  if (state.editMode !== "EDIT_LAYOUT" || !state.draftLayout) return null;

  const factory = state.factory;
  if (!factory) return null;

  const unplaced = unplacedMachines(factory, state.draftLayout);
  if (unplaced.length === 0) return null;

  return (
    <div className="fm-section" data-testid="unplaced-equipment-panel">
      <p className="fm-section__title">Unplaced Equipment</p>
      <ul className="unplaced-list">
        {unplaced.map((machine) => {
          const kind = assetVisualKind(machine);
          const label = assetLabel(kind);
          return (
            <li key={machine.id} className="unplaced-list__item" data-testid={`unplaced-${machine.id}`}>
              <span>
                {machine.name}
                {label && <span className="fm-badge fm-badge--unknown" style={{ marginLeft: 6 }}>{label}</span>}
              </span>
              <button
                type="button"
                className="fm-btn-secondary"
                onClick={() => placeMachine(machine.id, factory.width / 2, factory.length / 2)}
                data-testid={`place-${machine.id}`}
              >
                Place on floor
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
