import { apiPost } from "./client";
import type { PlanningRunRequest, PlanningRunResponse } from "./types";

/** POST /planning/run — parse the user's request, run the Phase 5C
 * orchestrator, and return the Phase 5D verified explanation. */
export function runPlanning(request: PlanningRunRequest): Promise<PlanningRunResponse> {
  return apiPost<PlanningRunResponse>("/planning/run", request);
}
