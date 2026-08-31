/**
 * Pure client-side draft-layout data transforms — mirror
 * backend/app/services/layout.py's create_layout/place_machine/
 * move_machine/rotate_machine SHAPE exactly (plain placement-array
 * bookkeeping, no geometry/constraint math at all). These build the
 * candidate FactoryLayout sent to POST /layout/validate for the
 * authoritative answer (Phase 6B section 4/12) — they never decide
 * validity themselves.
 */

import type { Factory, FactoryLayout, MachinePlacement } from "../api/types";

export function createEmptyDraft(factory: Factory): FactoryLayout {
  return { factory_width: factory.width, factory_length: factory.length, placements: [], reserved_zones: [], aisle_zones: [] };
}

export function getPlacement(layout: FactoryLayout, machineId: string): MachinePlacement | null {
  return layout.placements.find((p) => p.machine_id === machineId) ?? null;
}

function replacePlacement(layout: FactoryLayout, next: MachinePlacement): FactoryLayout {
  return {
    ...layout,
    placements: layout.placements.map((p) => (p.machine_id === next.machine_id ? next : p)),
  };
}

export function placeMachineDraft(layout: FactoryLayout, machineId: string, x: number, y: number, rotationDeg = 0): FactoryLayout {
  if (getPlacement(layout, machineId)) return layout; // already placed — no-op, mirrors DuplicatePlacementError being a caller error
  const placement: MachinePlacement = { machine_id: machineId, x, y, z: 0, rotation_deg: rotationDeg };
  return { ...layout, placements: [...layout.placements, placement] };
}

export function moveMachineDraft(layout: FactoryLayout, machineId: string, x: number, y: number): FactoryLayout {
  const existing = getPlacement(layout, machineId);
  if (!existing) return layout;
  return replacePlacement(layout, { ...existing, x, y });
}

export function rotateMachineDraft(layout: FactoryLayout, machineId: string, rotationDeg: number): FactoryLayout {
  const existing = getPlacement(layout, machineId);
  if (!existing) return layout;
  return replacePlacement(layout, { ...existing, rotation_deg: rotationDeg });
}

/** Machines that exist in `factory` but have no placement in `layout` —
 * the "Unplaced equipment" list (Phase 6B section 9). */
export function unplacedMachines(factory: Factory, layout: FactoryLayout | null): Factory["machines"] {
  const placedIds = new Set((layout?.placements ?? []).map((p) => p.machine_id));
  return factory.machines.filter((m) => !placedIds.has(m.id));
}
