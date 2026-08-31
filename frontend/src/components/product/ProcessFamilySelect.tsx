import { useEffect, useState } from "react";
import {
  fetchProcessFamilies,
  type ProcessFamily,
  type ProcessFamilyCatalog,
} from "../../api/processFamilies";
import { describeRequestFailure } from "../../api/client";

/** The one place a process family is chosen. */

/** The resolved catalog, once one attempt has succeeded. */
let cached: ProcessFamilyCatalog | null = null;

/** The IN-FLIGHT request, which is what actually does the deduplicating. */
let inFlight: Promise<ProcessFamilyCatalog> | null = null;

function loadCatalog(): Promise<ProcessFamilyCatalog> {
  if (cached !== null) return Promise.resolve(cached);
  if (inFlight !== null) return inFlight;

  inFlight = fetchProcessFamilies()
    .then((result) => {
      cached = result;
      inFlight = null;
      return result;
    })
    .catch((err) => {
      inFlight = null;
      throw err;
    });
  return inFlight;
}

export interface ProcessFamiliesState {
  catalog: ProcessFamilyCatalog | null;
  error: string | null;
  loading: boolean;
}

/** Fetch the catalog once per session. */
export function useProcessFamilies(): ProcessFamiliesState {
  const [catalog, setCatalog] = useState<ProcessFamilyCatalog | null>(cached);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(cached === null);

  useEffect(() => {
    if (cached !== null) return;
    let alive = true;
    loadCatalog()
      .then((result) => {
        if (alive) {
          setCatalog(result);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (alive) {
          setError(describeRequestFailure(err));
          setLoading(false);
        }
      });
    return () => {
      alive = false;
    };
  }, []);

  return { catalog, error, loading };
}

/** Reset the module-level cache. */
export function resetProcessFamilyCache(): void {
  cached = null;
  inFlight = null;
}

export function ProcessFamilySelect({
  value,
  onChange,
  state,
  label = "Process family",
  testId,
  ariaLabel,
  className,
}: {
  value: string;
  onChange: (processType: string) => void;
  state: ProcessFamiliesState;
  label?: string;
  testId?: string;
  ariaLabel?: string;
  className?: string;
}) {
  const { catalog, error, loading } = state;

  if (error !== null) {
    return (
      <span className="fm-note fm-note--warning" data-testid={testId ? `${testId}-error` : undefined}>
        Process families unavailable — {error}. An operation cannot be added until the
        vocabulary loads, because a family typed by hand would find no reference data.
      </span>
    );
  }

  const families: ProcessFamily[] = catalog?.families ?? [];

  return (
    <select
      className={className}
      value={value}
      aria-label={ariaLabel ?? label}
      disabled={loading || families.length === 0}
      onChange={(event) => onChange(event.target.value)}
      data-testid={testId}
    >
      {loading ? (
        <option value="">Loading process families…</option>
      ) : (
        families.map((family) => (
          <option key={family.process_type} value={family.process_type}>
            {family.label}
            {/* Coverage is stated at the moment of choosing rather than
                discovered later as an estimate button that does nothing. */}
            {family.has_reference_estimate ? "" : " — no reference estimate"}
          </option>
        ))
      )}
    </select>
  );
}

/** The family a select should start on: the first the catalog offers, so
 * the default is the server's own precedence rather than a literal. Empty
 * while loading, which is why every caller gates its submit on a non-empty
 * value. */
export function defaultProcessType(state: ProcessFamiliesState): string {
  return state.catalog?.families[0]?.process_type ?? "";
}
