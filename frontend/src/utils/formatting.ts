/** Pure display-formatting helpers. */

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value);
}

export function formatCurrency(value: number): string {
  return `€${new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value)}`;
}

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

/** LAST-RESORT display name derived from a machine_id. */
export function friendlyMachineName(machineId: string | null | undefined): string {
  if (!machineId) return "—";
  const name = machineId.startsWith("m-") ? machineId.slice(2) : machineId;
  return name
    .replace(/-/g, " ")
    .replace(/_/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}

/** Anything that carries an id and the name a person gave it. */
export interface NamedThing {
  id: string;
  name: string;
}

/** The station's own name, resolved from the concept or factory that defines it. */
export function stationName(
  id: string | null | undefined,
  known: readonly NamedThing[] | null | undefined,
): string {
  if (!id) return "—";
  const match = known?.find((thing) => thing.id === id);
  return match ? match.name : friendlyMachineName(id);
}

/** A station name shortened to fit a fixed-width label, deterministically. */
export function compactStationName(name: string, maxChars = 20): string {
  const trimmed = name.trim();
  if (trimmed.length <= maxChars) return trimmed;

  // "…×6" is 3 characters that must survive; take them off the budget
  // rather than off the end.
  const multiplier = /(\s[×x]\s?\d+)$/.exec(trimmed);
  const suffix = multiplier ? multiplier[1].replace(/^\s/, " ") : "";
  const stem = multiplier ? trimmed.slice(0, trimmed.length - multiplier[1].length) : trimmed;

  const budget = maxChars - suffix.length - 1; // room for the ellipsis
  if (budget <= 0) return trimmed.slice(0, maxChars);

  const cut = stem.slice(0, budget);
  const lastSpace = cut.lastIndexOf(" ");
  // Only break on a word boundary when one is reasonably far in; otherwise a
  // long single word would collapse to two letters.
  const head = lastSpace > budget * 0.5 ? cut.slice(0, lastSpace) : cut;
  return `${head.trimEnd()}…${suffix}`;
}
