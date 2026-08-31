import { apiPost } from "./client";
import type {
  BranchComparison,
  BranchComparisonRequest,
  ConversationStartRequest,
  ConversationTurnRequest,
  ConversationTurnResponse,
} from "./types";

/** Phase 7C conversational copilot endpoints. */

/** POST /conversation/start — begin a conversation and run its first turn. */
export function startConversation(request: ConversationStartRequest): Promise<ConversationTurnResponse> {
  return apiPost<ConversationTurnResponse>("/conversation/start", request);
}

/** POST /conversation/turn — run one follow-up against an existing session. */
export function sendConversationTurn(request: ConversationTurnRequest): Promise<ConversationTurnResponse> {
  return apiPost<ConversationTurnResponse>("/conversation/turn", request);
}

/** POST /conversation/compare — deterministic comparison of two branches. */
export function compareBranches(request: BranchComparisonRequest): Promise<BranchComparison> {
  return apiPost<BranchComparison>("/conversation/compare", request);
}
