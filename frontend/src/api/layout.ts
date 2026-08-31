import { apiGet, apiPost } from "./client";
import type { FactoryLayout, LayoutValidateRequest, LayoutValidationResult } from "./types";

/** GET /factory/example/layout — the bundled demo FactoryLayout. */
export function getExampleLayout(): Promise<FactoryLayout> {
  return apiGet<FactoryLayout>("/factory/example/layout");
}

/** POST /layout/validate — the SOLE authority on layout feasibility. */
export function validateLayout(request: LayoutValidateRequest): Promise<LayoutValidationResult> {
  return apiPost<LayoutValidationResult>("/layout/validate", request);
}
