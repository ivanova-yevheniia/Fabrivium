import type { ManufacturingProcessDraft, ProposedOperation } from "./product";
import type { ConceptStage } from "./types";

/** What the reviewed process already says about one station — G10/G11. */

/** Where a repeat count shown in the estimator came from. */
export type RepeatCountSource =
  /** The reviewed manufacturing operation states it. */
  | "PROCESS"
  /** Recorded by an estimate the engineer already accepted for this station,
   * on a station whose reviewed operation states no count. */
  | "ESTIMATE"
  /** The engineer typed it into the estimator just now. */
  | "ENGINEER"
  /** Nothing knows it. */
  | "NONE";

/** What the estimator should open with for one station. */
export interface EstimatorContext {
  /** The reviewed operation behind the station, or null for a concept built
   * from a brief by hand. */
  operation: ProposedOperation | null;
  repeats: number | null;
  repeatSource: RepeatCountSource;
  /** The reviewed description, ready to be shown and refined. Empty when
   * there is nothing known to show. */
  description: string;
  /** True when `description` came from the reviewed operation rather than from the engineer. */
  descriptionFromProcess: boolean;
}

export const NO_CONTEXT: EstimatorContext = {
  operation: null,
  repeats: null,
  repeatSource: "NONE",
  description: "",
  descriptionFromProcess: false,
};

/** The reviewed operation a stage was built from, as it stands now. */
export function reviewedOperation(
  stage: Pick<ConceptStage, "source_operation_id">,
  process: ManufacturingProcessDraft | null,
): ProposedOperation | null {
  if (!stage.source_operation_id || !process) return null;
  const operation = process.operations.find((op) => op.id === stage.source_operation_id);
  if (!operation) return null;
  if (operation.status !== "ACCEPTED" && operation.status !== "MODIFIED") return null;
  return operation;
}

/** The repeat count an accepted estimate for this station was composed with. */
function acceptedEstimateRepeats(stage: ConceptStage): number | null {
  if (stage.cycle_time.source !== "ENGINEERING_ESTIMATE") return null;
  const recorded = stage.cycle_time_estimate?.operations_per_unit;
  return typeof recorded === "number" ? recorded : null;
}

/** Everything the estimator can open with, without asking the engineer. */
export function estimatorContext(
  stage: ConceptStage,
  process: ManufacturingProcessDraft | null,
): EstimatorContext {
  const operation = reviewedOperation(stage, process);
  const fromProcess = operation?.repeated_operations ?? null;
  const fromEstimate = acceptedEstimateRepeats(stage);

  const [repeats, repeatSource]: [number | null, RepeatCountSource] =
    fromProcess !== null
      ? [fromProcess, "PROCESS"]
      : fromEstimate !== null
        ? [fromEstimate, "ESTIMATE"]
        : [null, "NONE"];

  // The reviewed description first — it is the sentence the engineer
  // approved, and it already carries the repeat count in words. The
  // operation name is the fallback rather than the first choice: "Screw
  // fastening" is a label, and the estimator reads free text.
  const description = (operation?.description || operation?.name || "").trim();

  return {
    operation,
    repeats,
    repeatSource,
    description,
    descriptionFromProcess: Boolean(operation) && description.length > 0,
  };
}

/** Why one station's estimate no longer answers the reviewed process. */
export interface StaleEstimate {
  /** The count the accepted estimate was composed with. */
  estimatedFor: number;
  /** What the reviewed process says now. */
  reviewedAs: number;
}

export function staleEstimate(
  stage: ConceptStage,
  process: ManufacturingProcessDraft | null,
): StaleEstimate | null {
  const estimatedFor = acceptedEstimateRepeats(stage);
  if (estimatedFor === null) return null;

  const reviewedAs = reviewedOperation(stage, process)?.repeated_operations ?? null;
  if (reviewedAs === null || reviewedAs === estimatedFor) return null;

  return { estimatedFor, reviewedAs };
}
