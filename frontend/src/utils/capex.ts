import { formatCurrency } from "./formatting";

/** Audit §4 — how a known-CAPEX figure is allowed to appear on screen. */

export interface KnownCapexDisplay {
  /** The main figure, already formatted. */
  amount: string;
  /** A qualifier to render beside it, or null when none is needed. */
  qualifier: string | null;
  /** True when nothing at all has a price yet — no number should be shown. */
  nothingPriced: boolean;
}

export function describeKnownCapex(
  knownCapex: number,
  options: { commerciallyComplete: boolean },
): KnownCapexDisplay {
  const complete = options.commerciallyComplete;

  if (knownCapex === 0 && !complete) {
    // Showing "€0" here would state a cost we do not have.
    return { amount: "Nothing priced yet", qualifier: null, nothingPriced: true };
  }
  if (!complete) {
    return { amount: formatCurrency(knownCapex), qualifier: "+ unpriced", nothingPriced: false };
  }
  return { amount: formatCurrency(knownCapex), qualifier: null, nothingPriced: false };
}

/** One known figure of a kind that `known_capex` does not describe. */
export interface KnownCostDimension {
  /** Category key, e.g. "OPEX_PER_DAY". */
  category: string;
  /** Heading for the figure, e.g. "Additional OPEX". */
  label: string;
  /** Already formatted with its period attached, e.g. "€18,000/day". */
  amount: string;
}

export interface KnownCostDisplay extends KnownCapexDisplay {
  /** Known money outside CAPEX, in a fixed order. */
  otherDimensions: KnownCostDimension[];
}

/** Heading and period wording per category. */
const CATEGORY_DISPLAY: Record<string, { label: string; suffix: string }> = {
  CAPEX: { label: "Known CAPEX", suffix: "" },
  ONE_TIME_OTHER: { label: "One-off cost", suffix: "" },
  OPEX_PER_DAY: { label: "Additional OPEX", suffix: "/day" },
  OPEX_PER_YEAR: { label: "Additional OPEX", suffix: "/year" },
};

/** The order money is shown in. Fixed so one plan reads the same every time. */
const CATEGORY_ORDER = ["ONE_TIME_OTHER", "OPEX_PER_DAY", "OPEX_PER_YEAR"] as const;

/** Everything a plan is KNOWN to cost, ready to render (G14). */
export function describeKnownCost(
  cost: {
    known_capex: number;
    components?: { category: string; amount: number | null }[];
    known_by_category?: Partial<Record<string, number>> | null;
  },
  options: { commerciallyComplete: boolean },
): KnownCostDisplay {
  const base = describeKnownCapex(cost.known_capex, options);
  // Prefer the backend's own breakdown. Fall back to summing the components
  // for an arena STORED BEFORE G14: reopening such a project must not drop
  // a dimension the engineer had already established, and the components
  // carry the same categories the breakdown is built from. Unknown amounts
  // contribute nothing — a missing price is absent, never a zero.
  const known: Record<string, number> = { ...(cost.known_by_category ?? {}) } as Record<string, number>;
  if (Object.keys(known).length === 0) {
    for (const component of cost.components ?? []) {
      if (component.amount === null || component.amount === undefined) continue;
      known[component.category] = (known[component.category] ?? 0) + component.amount;
    }
  }

  const otherDimensions: KnownCostDimension[] = [];
  for (const category of CATEGORY_ORDER) {
    const amount = known[category];
    if (amount === undefined || amount === null) continue;
    const display = CATEGORY_DISPLAY[category];
    if (!display) continue;
    otherDimensions.push({
      category,
      label: display.label,
      amount: `${formatCurrency(amount)}${display.suffix}`,
    });
  }

  // A plan whose real money is all recurring must not read as unpriced
  // either: once its profile is complete, "Nothing priced yet" beside a
  // known €18,000/day is as wrong as a bare "€0" was.
  const amount = base.nothingPriced && otherDimensions.length > 0 ? "€0" : base.amount;
  const nothingPriced = base.nothingPriced && otherDimensions.length === 0;

  return { ...base, amount, nothingPriced, otherDimensions };
}
