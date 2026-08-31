import { apiPost } from "./client";
import type { FactoryConceptDraft } from "./types";

/** Phase 16 — equipment discovery. */

export type CheckStatus = "PASS" | "FAIL" | "UNKNOWN";
export type DataFreshness = "LIVE" | "CACHED";
export type PriceStatus = "PUBLISHED" | "QUOTE_REQUIRED" | "UNKNOWN";
export type SourceType =
  | "MANUFACTURER_PAGE"
  | "MANUFACTURER_DATASHEET"
  | "DISTRIBUTOR_PAGE"
  | "INTERNAL_ASSET_RECORD"
  | "APPROVED_SUPPLIER_LIST";

/** What the station must be able to DO. */
export type EquipmentCapability = "SCREW_FASTENING" | "VISUAL_INSPECTION" | "LABEL_APPLICATION";

/** How well one value is supported. */
export type EvidenceLevel =
  | "KNOWN_SPECIFICATION"
  | "SOURCE_DERIVED"
  | "ESTIMATED"
  | "UNKNOWN"
  | "QUOTE_REQUIRED";

/** The strongest claim allowed. There is deliberately no "COMPATIBLE". */
export type MatchClaim = "POTENTIALLY_SUITABLE" | "CANDIDATE" | "CONSTRAINT_MISMATCH";

export type CatalogKind =
  | "RESEARCHED_MANUFACTURER"
  | "INTERNAL_ASSET_POOL"
  | "APPROVED_SUPPLIER"
  | "EXTERNAL_SOURCE";

/** A value a source published — or explicitly did not. */
export interface PublishedSpec {
  value: number | null;
  unit: string | null;
  text: string | null;
  source_id: string | null;
  evidence: EvidenceLevel;
  /** Present for SOURCE_DERIVED and ESTIMATED: the arithmetic, in words. */
  basis: string | null;
}

export interface EvidenceSummary {
  known_specification: number;
  source_derived: number;
  estimated: number;
  unknown: number;
  quote_required: number;
}

export interface EquipmentSource {
  source_id: string;
  url: string;
  source_type: SourceType;
  title: string;
  retrieved_at: string;
}

/** A `Sourced*` value from the concept — mirrors the backend wrapper. */
export interface SourcedNumber {
  value: number | null;
  source: string;
  detail: string | null;
}

export interface EquipmentRequirement {
  station_id: string;
  station_name: string;
  process_category: string;
  /** null means Fabrivium has not researched this kind of station — never
   * "nothing suitable exists". */
  required_capability: EquipmentCapability | null;
  capability_statement: string;
  max_cycle_time_seconds: SourcedNumber;
  operations_per_unit: SourcedNumber;
  max_payload_kg: SourcedNumber;
  part_dimensions_text: string | null;
  part_dimensions_provenance: string | null;
  required_capacity: SourcedNumber;
  operator_requirement: SourcedNumber;
  max_width_m: SourcedNumber;
  max_length_m: SourcedNumber;
  max_height_m: SourcedNumber;
  budget_limit: SourcedNumber;
  required_interfaces: string[];
  optional_preferences: string[];
  strategy_context: string | null;
  provenance: string;
}

export interface EquipmentCandidate {
  candidate_id: string;
  manufacturer: string;
  model: string;
  category: string;
  /** What this equipment DECLARES it can do. */
  provides: EquipmentCapability[];
  /** Which catalogue the record came out of. */
  catalog_id: string;
  catalog_kind: CatalogKind;
  /** What the product is relative to a station — a whole cell, or a part. */
  product_scope: string;
  description: string;
  cycle_time_seconds: PublishedSpec;
  capacity: PublishedSpec;
  operators_required: PublishedSpec;
  width_mm: PublishedSpec;
  length_mm: PublishedSpec;
  height_mm: PublishedSpec;
  weight_kg: PublishedSpec;
  torque_min_nm: PublishedSpec;
  torque_max_nm: PublishedSpec;
  speed_max_rpm: PublishedSpec;
  interfaces: string[];
  price: PublishedSpec;
  price_status: PriceStatus;
  cad_available: boolean | null;
  cad_format: string | null;
  cad_url: string | null;
  documentation_url: string | null;
  sources: EquipmentSource[];
  caveats: string[];
}

export interface CompatibilityCheck {
  field: string;
  label: string;
  status: CheckStatus;
  requirement_text: string;
  candidate_text: string;
  reason: string;
}

export interface CompatibilityReport {
  candidate_id: string;
  station_id: string;
  checks: CompatibilityCheck[];
}

export interface CandidateAssessment {
  candidate: EquipmentCandidate;
  compatibility: CompatibilityReport;
  claim: MatchClaim;
  claim_text: string;
  pass_count: number;
  fail_count: number;
  unknown_count: number;
  specs_published: number;
  specs_considered: number;
  evidence: EvidenceSummary;
  catalog_id: string;
  catalog_kind: CatalogKind;
}

/** One source's answer — including the sources that could not answer. */
export interface ConsultedCatalog {
  catalog_id: string;
  kind: CatalogKind;
  display_name: string;
  trust_statement: string;
  available: boolean;
  unavailable_reason: string;
  candidate_count: number;
  verified_on: string | null;
}

export interface EquipmentDiscoveryResult {
  requirement: EquipmentRequirement;
  assessments: CandidateAssessment[];
  capability: EquipmentCapability | null;
  capability_statement: string;
  catalogs: ConsultedCatalog[];
  freshness: DataFreshness;
  verified_on: string | null;
  note: string | null;
}

export interface ParameterChange {
  field: string;
  label: string;
  current_value: number | null;
  current_source: string;
  proposed_value: number;
  proposed_unit: string;
  proposed_source_url: string | null;
  /** True when adopting this would change what the simulator computes. */
  affects_simulation: boolean;
}

export interface EquipmentSelection {
  station_id: string;
  candidate_id: string;
  manufacturer: string;
  model: string;
  source_url: string | null;
  selected_from: DataFreshness;
  adopted_parameters: string[];
}

export interface EquipmentSelectResult {
  selection: EquipmentSelection;
  /** What COULD be adopted. Nothing here has been applied. */
  proposed_changes: ParameterChange[];
  affects_simulation: boolean;
}

/** Derive engineering requirements for one station and return real candidates. */
export function discoverEquipment(
  draft: FactoryConceptDraft,
  stationId: string,
  strategyContext?: string | null,
): Promise<EquipmentDiscoveryResult> {
  return apiPost<EquipmentDiscoveryResult>("/equipment/discover", {
    draft,
    station_id: stationId,
    strategy_context: strategyContext ?? null,
  });
}

/** Record a candidate as selected, and learn what it COULD change. */
export function selectEquipment(
  draft: FactoryConceptDraft,
  stationId: string,
  candidateId: string,
): Promise<EquipmentSelectResult> {
  return apiPost<EquipmentSelectResult>("/equipment/select", {
    draft,
    station_id: stationId,
    candidate_id: candidateId,
  });
}
