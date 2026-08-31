import { apiGet } from "./client";

/** The canonical process-family vocabulary, fetched rather than repeated. */

export interface ProcessFamily {
  /** The value that travels as a stage's `process_type`. */
  process_type: string;
  /** How the family is written on screen. */
  label: string;
  /** The words in a brief that select this family. */
  aliases: string[];
  /** Whether Fabrivium can offer an estimated cycle time for this family. */
  has_reference_estimate: boolean;
  /** What "one operation" means here ("screw", "check"), when known. */
  operation_noun: string | null;
  /** Whether a researched equipment catalogue exists for this family. */
  has_equipment_evidence: boolean;
}

export interface ProcessFamilyCatalog {
  families: ProcessFamily[];
  families_with_reference_estimate: number;
  families_with_equipment_evidence: number;
  reference_dataset_name: string;
}

export function fetchProcessFamilies(): Promise<ProcessFamilyCatalog> {
  return apiGet<ProcessFamilyCatalog>("/process/families");
}
