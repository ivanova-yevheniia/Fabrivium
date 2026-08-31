import { apiPost } from "./client";
import type {
  SimulationPlaybackRequest,
  SimulationTrace,
  VerifiedPlaybackRequest,
} from "./types";

/** POST /simulation/playback — Phase 8C. */
export function getSimulationPlayback(request: SimulationPlaybackRequest): Promise<SimulationTrace> {
  return apiPost<SimulationTrace>("/simulation/playback", request);
}

/** POST /simulation/playback/verified — replay a scenario from a SAVED project. */
export function getVerifiedPlayback(request: VerifiedPlaybackRequest): Promise<SimulationTrace> {
  return apiPost<SimulationTrace>("/simulation/playback/verified", request);
}
