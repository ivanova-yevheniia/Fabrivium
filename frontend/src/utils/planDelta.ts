import type {
  Factory,
  PlanningSessionState,
  StrategyActionSummary,
  StrategyMetrics,
} from "../api/types";
import { stationName } from "./formatting";

/** WHAT A PLAN ACTUALLY CHANGES, AS BEFORE → AFTER PAIRS. */

export interface PlanChange {
  /** Stable key for React and for tests. */
  key: string;
  /** What changed, in the engineer's words — a station or "Operating model". */
  subject: string;
  /** The property, e.g. "cycle time", "capacity", "shifts". */
  property: string;
  before: string;
  after: string;
}

export interface PlanChangeSet {
  changes: PlanChange[];
  /** Which evidence produced the list. */
  source: "SESSION" | "ACTION_SUMMARY" | "NONE";
  /** True when every change carries its before → after values. */
  complete: boolean;
  /** Levers the plan definitely pulled whose values this source cannot supply. */
  unvalued: string[];
}

const EMPTY: PlanChangeSet = { changes: [], source: "NONE", complete: true, unvalued: [] };

function seconds(value: number): string {
  // Cycle times are stored to sub-second precision; 78.5 s must not become
  // "79 s" in a panel whose whole purpose is to be exact about the change.
  return `${Number(value.toFixed(1))} s`;
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** Levers whose effect is a per-station VALUE rather than a count, so the
 * action summary records that they happened without recording what they
 * changed to. Named in the words the plan panel uses. */
const VALUE_ONLY_LEVERS: Record<string, string> = {
  CHANGE_MACHINE_CYCLE_TIME: "station cycle times",
  CHANGE_MACHINE_CAPACITY: "station capacities",
};

/**
 * The strong path: every difference between the factory the simulation
 * started from and the factory it ended on, in reading order — the line
 * first, then the operating model, then the buffers.
 */
function fromSession(session: PlanningSessionState): PlanChangeSet {
  const before: Factory = session.baseline_factory;
  const after: Factory = session.current_factory;
  const changes: PlanChange[] = [];

  const beforeMachines = new Map(before.machines.map((m) => [m.id, m]));
  const afterMachines = new Map(after.machines.map((m) => [m.id, m]));

  // Per-station changes, walked in the AFTER factory's order so a station
  // added by the plan appears where it sits on the line.
  for (const machine of after.machines) {
    const was = beforeMachines.get(machine.id);
    if (!was) {
      changes.push({
        key: `add-${machine.id}`,
        subject: machine.name,
        property: "station",
        before: "not in the concept",
        after: `added${machine.capacity > 1 ? `, capacity ${machine.capacity}` : ""}`,
      });
      continue;
    }
    if (was.cycle_time !== machine.cycle_time) {
      changes.push({
        key: `cycle-${machine.id}`,
        subject: machine.name,
        property: "cycle time",
        before: seconds(was.cycle_time),
        after: seconds(machine.cycle_time),
      });
    }
    if (was.capacity !== machine.capacity) {
      changes.push({
        key: `capacity-${machine.id}`,
        subject: machine.name,
        property: "capacity",
        before: String(was.capacity),
        after: String(machine.capacity),
      });
    }
  }

  // A station the plan removed is a change too, and silence about it would
  // be the most misleading omission on the list.
  for (const machine of before.machines) {
    if (!afterMachines.has(machine.id)) {
      changes.push({
        key: `remove-${machine.id}`,
        subject: machine.name,
        property: "station",
        before: "in the concept",
        after: "removed",
      });
    }
  }

  if (before.shifts_per_day !== after.shifts_per_day) {
    changes.push({
      key: "shifts",
      subject: "Operating model",
      property: "shifts per day",
      before: plural(before.shifts_per_day, "shift", "shifts"),
      after: plural(after.shifts_per_day, "shift", "shifts"),
    });
  }
  if (before.hours_per_shift !== after.hours_per_shift) {
    changes.push({
      key: "hours",
      subject: "Operating model",
      property: "hours per shift",
      before: `${before.hours_per_shift} h`,
      after: `${after.hours_per_shift} h`,
    });
  }
  if (before.operators_available !== after.operators_available) {
    changes.push({
      key: "operators",
      subject: "Workforce",
      property: "operators available",
      before: plural(before.operators_available, "operator", "operators"),
      after: plural(after.operators_available, "operator", "operators"),
    });
  }

  const beforeBuffers = new Map(before.buffers.map((b) => [b.id, b]));
  for (const buffer of after.buffers) {
    const was = beforeBuffers.get(buffer.id);
    if (was && was.capacity !== buffer.capacity) {
      changes.push({
        key: `buffer-${buffer.id}`,
        subject: buffer.name,
        property: "buffer capacity",
        before: `${was.capacity} units`,
        after: `${buffer.capacity} units`,
      });
    }
  }

  return { changes, source: "SESSION", complete: true, unvalued: [] };
}

/**
 * The weaker path: the backend's own verified action summary, read against
 * the concept factory this project holds.
 *
 * Every value here is exact. `added_shift_count` and friends were computed
 * by the backend from the same two factories `fromSession` diffs, so adding
 * a delta to the baseline gives the plan's real absolute figure — it is
 * arithmetic on verified numbers, not an estimate of one.
 *
 * The incompleteness is reported, never papered over: see `VALUE_ONLY_LEVERS`.
 */
function fromActions(actions: StrategyActionSummary, baseline: Factory): PlanChangeSet {
  const changes: PlanChange[] = [];

  for (const id of actions.added_machine_ids) {
    changes.push({
      key: `add-${id}`,
      subject: stationName(id, baseline.machines),
      property: "station",
      before: "not in the concept",
      after: "added",
    });
  }

  if (actions.added_shift_count !== 0) {
    changes.push({
      key: "shifts",
      subject: "Operating model",
      property: "shifts per day",
      before: plural(baseline.shifts_per_day, "shift", "shifts"),
      after: plural(baseline.shifts_per_day + actions.added_shift_count, "shift", "shifts"),
    });
  }
  if (actions.hours_per_shift_delta !== 0) {
    changes.push({
      key: "hours",
      subject: "Operating model",
      property: "hours per shift",
      before: `${baseline.hours_per_shift} h`,
      after: `${Number((baseline.hours_per_shift + actions.hours_per_shift_delta).toFixed(2))} h`,
    });
  }
  if (actions.operator_delta !== 0) {
    changes.push({
      key: "operators",
      subject: "Workforce",
      property: "operators available",
      before: plural(baseline.operators_available, "operator", "operators"),
      after: plural(baseline.operators_available + actions.operator_delta, "operator", "operators"),
    });
  }

  // The backend writes these as "buf-1: 50 -> 100" — already a before/after
  // pair, so it is split rather than reformatted.
  for (const change of actions.buffer_changes) {
    const match = /^(.*?):\s*(.*?)\s*->\s*(.*)$/.exec(change);
    if (match) {
      changes.push({
        key: `buffer-${match[1]}`,
        subject: stationName(match[1], baseline.buffers),
        property: "buffer capacity",
        before: `${match[2]} units`,
        after: `${match[3]} units`,
      });
    } else {
      changes.push({
        key: `buffer-${change}`,
        subject: "Buffer",
        property: "capacity",
        before: "—",
        after: change,
      });
    }
  }

  const unvalued = actions.action_types
    .filter((type) => type in VALUE_ONLY_LEVERS)
    .map((type) => VALUE_ONLY_LEVERS[type]);

  return { changes, source: "ACTION_SUMMARY", complete: unvalued.length === 0, unvalued };
}

/** What the selected plan changes, from the best evidence available. */
export function planChanges(
  session: PlanningSessionState | undefined | null,
  actions?: StrategyActionSummary | null,
  baseline?: Factory | null,
): PlanChangeSet {
  if (session) return fromSession(session);
  if (actions && baseline) return fromActions(actions, baseline);
  return EMPTY;
}

// Bottleneck migration

export interface LimitingStageMove {
  fromId: string;
  toId: string;
  from: string;
  to: string;
}

/** Did the plan MOVE the limiting stage? */
export function limitingStageMove(
  baseline: StrategyMetrics,
  selected: StrategyMetrics,
  factory: Factory | null,
): LimitingStageMove | null {
  const fromId = baseline.bottleneck_machine_id;
  const toId = selected.bottleneck_machine_id;
  if (!fromId || !toId || fromId === toId) return null;
  const machines = factory?.machines ?? null;
  return {
    fromId,
    toId,
    from: stationName(fromId, machines),
    to: stationName(toId, machines),
  };
}
