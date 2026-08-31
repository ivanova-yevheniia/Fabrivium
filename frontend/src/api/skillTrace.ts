/** The skills that produced the results currently on screen. */

export interface SkillExecution {
  /** e.g. `factory_simulation` */
  readonly skillId: string;
  /** e.g. `1.0.0` — the version that produced this result, not the newest. */
  readonly version: string;
  /** SUCCESS | PARTIAL | BLOCKED | NOT_APPLICABLE | FAILED */
  readonly status: string;
  /** The endpoint whose response carried it. */
  readonly path: string;
}

export const SKILL_TRACE_HEADER = "X-FactoryMind-Skills";

/** Most recent last. Bounded so a long session cannot grow it without limit. */
const MAX_ENTRIES = 40;

let executions: SkillExecution[] = [];
const listeners = new Set<() => void>();

/** Parse one header value: `id@version:STATUS, id@version:STATUS`. */
export function parseSkillTrace(header: string, path: string): SkillExecution[] {
  return header
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const at = part.lastIndexOf("@");
      const colon = part.lastIndexOf(":");
      if (at < 0 || colon < at) {
        // Unrecognised shape. Recorded as-is rather than dropped: a trace
        // that quietly discards what it cannot parse is worse than one that
        // shows something odd.
        return { skillId: part, version: "", status: "", path };
      }
      return {
        skillId: part.slice(0, at),
        version: part.slice(at + 1, colon),
        status: part.slice(colon + 1),
        path,
      };
    });
}

export function recordSkillTrace(header: string | null, path: string): void {
  if (!header) return;
  const parsed = parseSkillTrace(header, path);
  if (parsed.length === 0) return;
  executions = [...executions, ...parsed].slice(-MAX_ENTRIES);
  listeners.forEach((listener) => listener());
}

export function getSkillExecutions(): readonly SkillExecution[] {
  return executions;
}

export function subscribeToSkillTrace(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Test seam. Not called by the application. */
export function resetSkillTrace(): void {
  executions = [];
  listeners.forEach((listener) => listener());
}
