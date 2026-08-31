import { apiPost } from "./client";
import type {
  StrategyAskRequest,
  StrategyAskResponse,
  StrategyCompareRequest,
  StrategyComparison,
  StrategyExploreRequest,
  StrategyExploreResponse,
} from "./types";

/** Phase 8B optimization-arena endpoints. */

/** POST /strategies/explore — several verified strategies for one goal. */
export function exploreStrategies(request: StrategyExploreRequest): Promise<StrategyExploreResponse> {
  return apiPost<StrategyExploreResponse>("/strategies/explore", request);
}

/** POST /strategies/compare — deterministic comparison of two strategies. */
export function compareStrategyOptions(request: StrategyCompareRequest): Promise<StrategyComparison> {
  return apiPost<StrategyComparison>("/strategies/compare", request);
}

/** POST /strategies/ask — a follow-up about the options already on screen. */
export function askAboutStrategies(request: StrategyAskRequest): Promise<StrategyAskResponse> {
  return apiPost<StrategyAskResponse>("/strategies/ask", request);
}
