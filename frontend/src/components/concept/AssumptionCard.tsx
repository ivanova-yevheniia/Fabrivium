import { useState } from "react";
import { Info } from "lucide-react";
import type { EstimatedRange, StationAssumptionProposal } from "../../api/uncertainty";

/** Phase 18B — one station, one card. */
export function AssumptionCard({
  proposal,
  onAccept,
  busy,
}: {
  proposal: StationAssumptionProposal;
  /** Called with the fields the engineer chose to accept. */
  onAccept: (fields: string[]) => void;
  busy: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [chosen, setChosen] = useState<Record<string, boolean>>({
    cycle_time: true,
    capacity: true,
    operators: true,
  });

  const rows: { field: string; label: string; value: EstimatedRange | null }[] = [
    { field: "cycle_time", label: "Cycle time", value: proposal.cycle_time },
    { field: "capacity", label: "Capacity", value: proposal.capacity },
    { field: "operators", label: "Operators", value: proposal.operators },
  ];

  const available = rows.filter((r) => r.value !== null);
  const selected = available.filter((r) => chosen[r.field]).map((r) => r.field);

  return (
    <div className="assumptions" data-testid="assumption-card">
      <header className="assumptions__head">
        <p className="assumptions__title">Preliminary engineering assumptions</p>
        {proposal.fell_back && (
          <span className="assumptions__route" data-testid="assumption-route">
            Estimated locally
          </span>
        )}
      </header>

      <ul className="assumptions__rows">
        {rows.map(({ field, label, value }) => (
          <li key={field} className="assumptions__row" data-testid={`assumption-${field}`}>
            {editing && value && (
              <input
                type="checkbox"
                checked={chosen[field] ?? false}
                onChange={(e) => setChosen((c) => ({ ...c, [field]: e.target.checked }))}
                aria-label={`Accept ${label}`}
                data-testid={`assumption-toggle-${field}`}
              />
            )}
            <span className="fm-label assumptions__row-label">{label}</span>
            {value ? (
              <>
                <span className="assumptions__value" data-testid={`assumption-value-${field}`}>
                  {value.working_value} {value.unit === "units" ? "" : value.unit === "operators" ? "" : value.unit}
                </span>
                {value.low !== value.high && (
                  <span className="assumptions__range">
                    {value.low}–{value.high} {value.unit}
                  </span>
                )}
                <span className="assumptions__confidence">{value.confidence}</span>
                <ProvenanceInfo label={label} value={value} field={field} />
              </>
            ) : (
              <span className="assumptions__unknown" data-testid={`assumption-unknown-${field}`}>
                Not established
              </span>
            )}
          </li>
        ))}
      </ul>

      <p className="assumptions__caveat">
        Suitable for concept simulation. Not detailed engineering specifications.
      </p>

      <div className="assumptions__actions">
        <button
          type="button"
          className="fm-btn-primary fm-btn--auto"
          onClick={() => onAccept(editing ? selected : available.map((r) => r.field))}
          disabled={busy || (editing && selected.length === 0)}
          data-testid="assumption-accept-all"
        >
          {editing
            ? `Accept ${selected.length} of ${available.length}`
            : "Accept all for concept simulation"}
        </button>
        <button
          type="button"
          className="fm-btn-secondary fm-btn--auto"
          onClick={() => setEditing((e) => !e)}
          disabled={busy}
          data-testid="assumption-edit"
        >
          {editing ? "Accept everything instead" : "Edit individually"}
        </button>
      </div>
    </div>
  );
}

/** The ⓘ affordance. */
export function ProvenanceInfo({
  label,
  value,
  field,
  status,
}: {
  label: string;
  value: EstimatedRange;
  field: string;
  /** e.g. "Accepted for concept simulation" once it is on the stage. */
  status?: string;
}) {
  const [open, setOpen] = useState(false);
  const method =
    value.method === "LOCAL_HEURISTIC"
      ? "Fabrivium local engineering heuristic"
      : value.method === "LANGUAGE_MODEL"
        ? value.model_name ?? "Language model"
        : "Engineer";

  return (
    <span className="provenance">
      <button
        type="button"
        className="provenance__toggle"
        aria-expanded={open}
        aria-label={`Where ${label} came from`}
        onClick={() => setOpen((o) => !o)}
        data-testid={`assumption-info-${field}`}
      >
        <Info size={13} strokeWidth={2} aria-hidden="true" />
      </button>
      {open && (
        <div className="provenance__panel" role="note" data-testid={`assumption-detail-${field}`}>
          <dl>
            <div>
              <dt>Source</dt>
              <dd>{method}</dd>
            </div>
            <div>
              <dt>Basis</dt>
              <dd>{value.basis}</dd>
            </div>
            {value.low !== value.high && (
              <div>
                <dt>Estimated range</dt>
                <dd>
                  {value.low}–{value.high} {value.unit}
                </dd>
              </div>
            )}
            <div>
              <dt>Working value</dt>
              <dd>
                {value.working_value} {value.unit}
              </dd>
            </div>
            <div>
              <dt>Confidence</dt>
              <dd>{value.confidence}</dd>
            </div>
            {status && (
              <div>
                <dt>Status</dt>
                <dd>{status}</dd>
              </div>
            )}
          </dl>
        </div>
      )}
    </span>
  );
}
