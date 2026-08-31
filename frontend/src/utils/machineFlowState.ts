/**
 * Phase 9B — the fourth machine state, STARVED, derived honestly from two
 * fields the trace ALREADY reports (a machine's real processing_count, and
 * its wired inbound buffer's real level) — no new capture, no new trace
 * field, no fabrication. A machine is STARVED when it has a wired inbound
 * buffer that is currently empty and the machine itself is not processing:
 * it is ready to work but there is genuinely nothing to draw from yet.
 * Machines with no wired inbound buffer (e.g. the first stage of a route,
 * fed from outside the line) have no way to distinguish "starved" from
 * ordinary idle in the trace, so they only ever resolve to IDLE/PROCESSING/
 * BLOCKED — never a fabricated STARVED guess.
 */

import type { Factory } from "../api/types";
import type { BufferTraceSample, MachineTraceSample } from "../api/types";
import type { UnitVisualState } from "./traceIndex";

export type MachineFlowState = "idle" | "processing" | "blocked" | "starved";

/** machine_id -> the buffer_id that feeds it, for every WIRED buffer in the factory. */
export function buildInboundBufferByMachine(factory: Factory): Map<string, string> {
  const map = new Map<string, string>();
  for (const buffer of factory.buffers) {
    if (buffer.upstream_machine_id && buffer.downstream_machine_id) {
      map.set(buffer.downstream_machine_id, buffer.id);
    }
  }
  return map;
}

/**
 * Whether a machine's `queue_length` is ALREADY represented by its wired
 * inbound buffer's gauge — in which case drawing queue markers too would
 * show the same physical units twice.
 *
 * This is not a heuristic; it follows from how the simulator runs a stage
 * (`_run_step` in app/services/simulation.py). A unit is placed in the
 * inbound buffer by the UPSTREAM stage's `outbound.put()`, and the very
 * next thing that happens is the downstream stage calling
 * `queue_arrived()`. The unit then leaves the machine queue when the
 * machine resource is acquired, and is drawn out of the buffer by
 * `inbound.get()` immediately after. Both memberships therefore start and
 * end at the same instant: for a machine with a wired inbound buffer,
 * "waiting in the buffer" and "waiting in the queue" are one population
 * described twice.
 *
 * Measured on the flagship traces: `buffer.level === downstream
 * machine.queue_length` in 241/241 frames of BOTH the baseline and the
 * optimized run, for all three buffers, with a maximum absolute delta of
 * 0. In the congested BEFORE run that is ~50 units drawn twice.
 *
 * Ownership rule: the BUFFER owns them. It has a real recorded capacity
 * (50), so it can show a bounded, physically meaningful "50/50 FULL";
 * a machine queue has no recorded capacity, and the queue banding has to
 * fall back on a readability reference depth rather than a physical limit.
 * The buffer is also the actual place on the floor where the units sit.
 *
 * A machine with NO wired inbound buffer (e.g. the first stage of a route,
 * fed from outside the line) keeps its queue markers — there is no buffer
 * gauge for those units, so the queue visual is their only representation
 * and suppressing it would HIDE real WIP.
 */
export function queueIsOwnedByInboundBuffer(
  machineId: string,
  inboundBufferByMachine: Map<string, string>,
): boolean {
  return inboundBufferByMachine.has(machineId);
}

/** Whether a tracked unit should be drawn as its own travelling workpiece. */
export function unitIsOwnedByMachineProcessing(unit: UnitVisualState): boolean {
  return unit.status === "processing";
}

export function machineFlowState(
  machineId: string,
  sample: MachineTraceSample | undefined,
  inboundBufferByMachine: Map<string, string>,
  buffers: Map<string, BufferTraceSample>,
): MachineFlowState {
  if (!sample) return "idle";
  if (sample.blocked) return "blocked";
  if (sample.processing_count > 0) return "processing";

  const inboundBufferId = inboundBufferByMachine.get(machineId);
  if (inboundBufferId) {
    const inbound = buffers.get(inboundBufferId);
    if (inbound && inbound.level === 0) return "starved";
  }
  return "idle";
}
