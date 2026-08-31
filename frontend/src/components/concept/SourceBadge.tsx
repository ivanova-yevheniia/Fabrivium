import type { SourcedNumber, ValueSource } from "../../api/types";

/** Phase 13 §6 — where one value came from. */

const LABELS: Record<ValueSource, string> = {
  CUSTOMER: "Customer",
  MANUFACTURER: "Manufacturer",
  // Phase 18B. "Our estimate" read as a hedge in the live walkthrough and
  // sat oddly beside "Customer" and "Manufacturer", which name a SOURCE
  // rather than an owner. "Estimated" states the value's status, which is
  // what the badge is for.
  ENGINEERING_ESTIMATE: "Estimated",
  ENGINEER: "Engineer",
  DOCUMENT: "Document",
  MEASURED: "Measured",
  EXTERNAL_DATA: "External data",
  // "Simulated" rather than "Calculated": a number a run produced and a
  // number arithmetic produced answer different questions, and only one of
  // them can disagree with the model it came from.
  SIMULATED: "Simulated",
  EXAMPLE_DATA: "Example data",
  CATALOG_DEFAULT: "Planning default",
  // The enum member is CALCULATED for backwards compatibility; the word an
  // engineer reads is COMPUTED, which is what the resolution UI calls it.
  CALCULATED: "Computed",
  UNKNOWN: "Unknown",
};

export function SourceBadge({ source, detail }: { source: ValueSource; detail?: string | null }) {
  return (
    <span
      className={`source-badge source-badge--${source.toLowerCase()}`}
      data-testid={`source-${source.toLowerCase()}`}
      title={detail ?? undefined}
    >
      {LABELS[source]}
    </span>
  );
}

/** A number with its provenance, or an explicit "not known yet". */
export function SourcedValue({
  value,
  unit,
  showSource = true,
}: {
  value: SourcedNumber;
  unit?: string;
  showSource?: boolean;
}) {
  if (value.value === null) {
    return (
      <span className="sourced-value sourced-value--unknown" data-testid="sourced-unknown">
        Not known yet
      </span>
    );
  }
  return (
    <span className="sourced-value">
      <span className="fm-mono sourced-value__number">
        {value.value.toLocaleString("en-US", { maximumFractionDigits: 2 })}
      </span>
      {unit && <span className="sourced-value__unit">{unit}</span>}
      {showSource && <SourceBadge source={value.source} detail={value.detail} />}
    </span>
  );
}
