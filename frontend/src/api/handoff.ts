import { apiPost } from "./client";
import type { Factory, FactoryLayout } from "./types";

/** Phase 15C — engineering handoff into Siemens Plant Simulation. */

export type HandoffStatus =
  /** Everything transferred AND verified by read-back. */
  | "COMPLETE"
  /** A model exists but does not match what was sent; see the counts. */
  | "INCOMPLETE"
  /** Plant Simulation could not be reached at all on this machine. */
  | "UNAVAILABLE";

export interface PlantSimulationHandoffResult {
  status: HandoffStatus;
  /** Set ONLY after the backend found the file on disk at a plausible size. */
  model_path: string | null;
  /** The size that was actually measured on disk. */
  model_bytes: number | null;
  export_directory: string | null;
  /** Whether the SAVED FILE was re-opened and read back. */
  saved_model_verified: boolean | null;
  /** Counts read out of the REOPENED file, not out of the build session. */
  saved_stations_verified: number | null;
  saved_connections_verified: number | null;
  /**
   * Which Plant Simulation release wrote the file, as its own automation
   * type library reports it. `null` means UNKNOWN and is shown as UNKNOWN —
   * an .spp is version-bound, so a guess would mislead the recipient.
   */
  product_version: string | null;
  /** The localisation the receiving model answered to ("de" / "en"). */
  language: string | null;

  stations_created: number;
  stations_verified: number;
  connections_created: number;
  connections_verified: number;
  cycle_times_verified: number;

  /** GEOMETRY — Phase 15D. */
  /** "normalised-concept" (the session's arrangement, scaled) or
   *  "generated-line" (a clean engineering line down the route). */
  layout_mode: string | null;
  /** Why the session's own arrangement was not used, when it was not. */
  layout_reason: string | null;
  /** Objects found at the position they were given. */
  positions_verified: number;
  positions_checked: number;
  /** Smallest centre-to-centre separation, in frame units. An icon is 41. */
  layout_min_separation: number | null;
  /** Overlapping pairs. Empty is the only passing value. */
  overlaps: string[];

  /** True only when the model was walked Source → Drain through every object that was created. */
  route_complete: boolean | null;
  /** The route as walked out of the model itself. */
  route_walked: string[];
  /** Objects that exist but sit off the route. */
  disconnected: string[];

  /** Units that reached the drain in the short verification run. */
  traversal_units: number | null;
  traversal_verified: boolean | null;

  /** Stations whose selected-equipment metadata was read back and matched. */
  equipment_verified: number;
  equipment_transferred: number;

  /** Present only when a run was requested and completed. */
  simulated_units: number | null;
  simulated_seconds: number | null;
  station_utilisation: Record<string, number>;

  /** The four independent verdicts. */
  verification: VerificationTier[];

  /** What the .spp actually contains. */
  export_scope: string;
  export_scope_label: string;
  /** Named things the selected plan would change that are NOT in the file. */
  export_excludes: string[];
  /** The engineering manifest written beside the model, if it was. */
  manifest_path: string | null;

  warnings: string[];
  errors: string[];
}

export type TierName = "STRUCTURE" | "LAYOUT" | "FLOW" | "RUNTIME";
/** NOT_RUN is not a pass and is never rendered as one. */
export type TierStatus = "VERIFIED" | "FAILED" | "NOT_RUN";

export interface VerificationTier {
  tier: TierName;
  status: TierStatus;
  /** The evidence behind the verdict, in the product's own counts. */
  detail: string;
}

/** One superseded selection, kept so "why this machine?" stays answerable. */
export interface SupersededSelection {
  candidate_id: string;
  manufacturer: string;
  model: string;
  selected_at: string;
  superseded_at: string;
}

/** The equipment recorded as UNDER CONSIDERATION for one station. */
export interface EquipmentSelectionMetadata {
  manufacturer: string;
  model: string;
  source_url?: string | null;
  /** Which record was chosen. */
  candidate_id?: string;
  station_id?: string;
  selected_at?: string;
  /** The requirement bounds in force when this was chosen. */
  bounds?: { field: string; label: string; unit: string | null; value: number | string | null }[];
  /** Oldest first. */
  superseded?: SupersededSelection[];
}

export interface PlantSimulationHandoffRequest {
  factory: Factory;
  product_id: string;
  layout?: FactoryLayout | null;
  run_simulation?: boolean;
  /** Keyed by station id. */
  equipment_selections?: Record<string, EquipmentSelectionMetadata> | null;
}

/** Generate a Siemens Plant Simulation model from the current concept. */
export function handoffToPlantSimulation(
  request: PlantSimulationHandoffRequest,
): Promise<PlantSimulationHandoffResult> {
  return apiPost<PlantSimulationHandoffResult>("/handoff/plant-simulation", {
    factory: request.factory,
    product_id: request.product_id,
    layout: request.layout ?? null,
    run_simulation: request.run_simulation ?? false,
    // The station-by-station record of which real machine is on the table.
    // It was in this function's own request type and in the backend's, and
    // was the one field the body did not carry — so an engineer who picked
    // equipment and exported the model handed over a .spp that had never
    // heard of it.
    equipment_selections: request.equipment_selections ?? null,
  });
}
