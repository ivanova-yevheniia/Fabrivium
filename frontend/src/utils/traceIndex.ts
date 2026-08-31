/** Phase 8C — deterministic playback lookup over a SimulationTrace. */

import type {
  BufferTraceSample,
  MachineTraceSample,
  OperatorTraceSample,
  SimulationTrace,
  SystemTraceSample,
  UnitEvent,
  UnitEventType,
} from "../api/types";

/** Event types that mark a change in WHERE a unit visually is. */
const POSITION_EVENT_TYPES = new Set<UnitEventType>([
  "UNIT_RELEASED",
  "UNIT_ENTERED_MACHINE_QUEUE",
  "UNIT_STARTED_PROCESSING",
  "UNIT_FINISHED_PROCESSING",
  "UNIT_ENTERED_BUFFER",
  "UNIT_LEFT_BUFFER",
  "UNIT_COMPLETED",
]);

export type UnitStatus = "released" | "queued" | "processing" | "finished" | "buffered" | "completed";

export interface UnitVisualState {
  unitId: number;
  status: UnitStatus;
  /** machine_id relevant to the current status (queue/processing/finished target), if any. */
  atMachineId: string | null;
  /** buffer_id relevant to the current status (entered/left), if any. */
  atBufferId: string | null;
  /** 0..1 — how far between this event and the NEXT known positional event *simTime* is. */
  progress: number;
}

export interface TraceStateAt {
  timestamp: number;
  /** machine_id -> its sample at/just before this instant. */
  machines: Map<string, MachineTraceSample>;
  /** buffer_id -> its sample at/just before this instant. */
  buffers: Map<string, BufferTraceSample>;
  operators: OperatorTraceSample | null;
  system: SystemTraceSample | null;
  units: UnitVisualState[];
}

function lastAtOrBefore<T>(sorted: T[], t: number, getTime: (item: T) => number): number {
  // Standard "rightmost index with time <= t" binary search. Returns -1 if
  // every element is after t (nothing has happened yet at this instant).
  let lo = 0;
  let hi = sorted.length - 1;
  let result = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (getTime(sorted[mid]) <= t) {
      result = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return result;
}

function firstAfter<T>(sorted: T[], t: number, getTime: (item: T) => number): number {
  let lo = 0;
  let hi = sorted.length - 1;
  let result = sorted.length;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (getTime(sorted[mid]) > t) {
      result = mid;
      hi = mid - 1;
    } else {
      lo = mid + 1;
    }
  }
  return result;
}

const STATUS_BY_EVENT: Record<string, UnitStatus> = {
  UNIT_RELEASED: "released",
  UNIT_ENTERED_MACHINE_QUEUE: "queued",
  UNIT_STARTED_PROCESSING: "processing",
  UNIT_FINISHED_PROCESSING: "finished",
  UNIT_ENTERED_BUFFER: "buffered",
  UNIT_LEFT_BUFFER: "queued",
  UNIT_COMPLETED: "completed",
};

export class TraceIndex {
  readonly trace: SimulationTrace;
  readonly horizonSeconds: number;

  private readonly machineByMachineId = new Map<string, MachineTraceSample[]>();
  private readonly bufferByBufferId = new Map<string, BufferTraceSample[]>();
  private readonly operatorSeries: OperatorTraceSample[];
  private readonly systemSeries: SystemTraceSample[];
  private readonly positionEventsByUnit = new Map<number, UnitEvent[]>();

  constructor(trace: SimulationTrace) {
    this.trace = trace;
    this.horizonSeconds = trace.horizon_seconds;

    for (const sample of trace.machine_series) {
      const list = this.machineByMachineId.get(sample.machine_id) ?? [];
      list.push(sample);
      this.machineByMachineId.set(sample.machine_id, list);
    }
    for (const sample of trace.buffer_series) {
      const list = this.bufferByBufferId.get(sample.buffer_id) ?? [];
      list.push(sample);
      this.bufferByBufferId.set(sample.buffer_id, list);
    }
    this.operatorSeries = trace.operator_series;
    this.systemSeries = trace.system_series;

    for (const event of trace.events) {
      if (!POSITION_EVENT_TYPES.has(event.event_type)) continue;
      const list = this.positionEventsByUnit.get(event.unit_id) ?? [];
      list.push(event);
      this.positionEventsByUnit.set(event.unit_id, list);
    }
  }

  private machineAt(machineId: string, t: number): MachineTraceSample | undefined {
    const series = this.machineByMachineId.get(machineId);
    if (!series) return undefined;
    const idx = lastAtOrBefore(series, t, (s) => s.timestamp);
    return idx >= 0 ? series[idx] : series[0];
  }

  private bufferAt(bufferId: string, t: number): BufferTraceSample | undefined {
    const series = this.bufferByBufferId.get(bufferId);
    if (!series) return undefined;
    const idx = lastAtOrBefore(series, t, (s) => s.timestamp);
    return idx >= 0 ? series[idx] : series[0];
  }

  private unitStateAt(unitId: number, t: number): UnitVisualState | null {
    const events = this.positionEventsByUnit.get(unitId);
    if (!events || events.length === 0) return null;

    const idx = lastAtOrBefore(events, t, (e) => e.timestamp);
    if (idx < 0) return null; // not released yet at this instant

    const current = events[idx];
    const next = idx + 1 < events.length ? events[idx + 1] : null;
    const progress = next
      ? Math.min(1, Math.max(0, (t - current.timestamp) / Math.max(1e-6, next.timestamp - current.timestamp)))
      : 0;

    return {
      unitId,
      status: STATUS_BY_EVENT[current.event_type] ?? "queued",
      atMachineId: current.machine_id ?? next?.machine_id ?? null,
      atBufferId: current.buffer_id ?? null,
      progress,
    };
  }

  /** The single entry point for playback rendering. */
  stateAt(simTimeSeconds: number): TraceStateAt {
    const t = Math.min(this.horizonSeconds, Math.max(0, simTimeSeconds));

    const machines = new Map<string, MachineTraceSample>();
    for (const machineId of this.machineByMachineId.keys()) {
      const sample = this.machineAt(machineId, t);
      if (sample) machines.set(machineId, sample);
    }

    const buffers = new Map<string, BufferTraceSample>();
    for (const bufferId of this.bufferByBufferId.keys()) {
      const sample = this.bufferAt(bufferId, t);
      if (sample) buffers.set(bufferId, sample);
    }

    const operatorIdx = lastAtOrBefore(this.operatorSeries, t, (s) => s.timestamp);
    const operators = operatorIdx >= 0 ? this.operatorSeries[operatorIdx] : null;

    const systemIdx = lastAtOrBefore(this.systemSeries, t, (s) => s.timestamp);
    const system = systemIdx >= 0 ? this.systemSeries[systemIdx] : null;

    const units: UnitVisualState[] = [];
    for (const unitId of this.positionEventsByUnit.keys()) {
      const state = this.unitStateAt(unitId, t);
      if (state && state.status !== "completed") units.push(state);
    }
    units.sort((a, b) => a.unitId - b.unitId);

    return { timestamp: t, machines, buffers, operators, system, units };
  }

  /** First sample timestamp strictly after `t`, or the horizon if none —
   * used to snap "next story marker" style seeking. */
  nextSystemSampleAfter(t: number): number {
    const idx = firstAfter(this.systemSeries, t, (s) => s.timestamp);
    return idx < this.systemSeries.length ? this.systemSeries[idx].timestamp : this.horizonSeconds;
  }
}
