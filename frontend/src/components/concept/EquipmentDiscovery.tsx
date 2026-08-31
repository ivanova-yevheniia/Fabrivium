import { useEffect, useMemo, useState, type ReactNode } from "react";
import { AlertTriangle, Check, CircleAlert, ExternalLink, Loader2, Minus, RefreshCw, X } from "lucide-react";
import { SourceBadge } from "./SourceBadge";
import { describeRequestFailure } from "../../api/client";
import {
  discoverEquipment,
  selectEquipment,
  type CandidateAssessment,
  type CatalogKind,
  type CheckStatus,
  type CompatibilityCheck,
  type ConsultedCatalog,
  type EquipmentDiscoveryResult,
  type EquipmentSelectResult,
  type EvidenceSummary,
  type ParameterChange,
  type PublishedSpec,
} from "../../api/equipment";
import type { FactoryConceptDraft, ValueSource } from "../../api/types";
import {
  EQUIPMENT_STATE_LABEL,
  EQUIPMENT_STATE_NOTE,
  boundChanges,
  candidateState,
  checkTally,
  currentBounds,
  recordedBounds,
  type BoundChange,
  type EquipmentState,
} from "../../api/equipmentState";
import type { EquipmentSelectionMetadata } from "../../api/handoff";

/** Phase 16 — from a planning station to real equipment candidates. */
export function EquipmentDiscovery({
  draft,
  stationId,
  onStationChange,
  strategyContext,
  onSelected,
  onRequirementsComputed,
  storedSelections,
}: {
  draft: FactoryConceptDraft;
  /** The station being worked on. */
  stationId: string;
  /** Report the engineer's choice upward. */
  onStationChange: (stationId: string) => void;
  strategyContext?: string | null;
  onSelected?: (result: EquipmentSelectResult, bounds: EquipmentSelectionMetadata["bounds"]) => void;
  /** Fired when a station requirement has been computed, naming the station. */
  onRequirementsComputed?: (stationId: string) => void;
  /** What is already recorded as under consideration, per station. */
  storedSelections?: Record<string, EquipmentSelectionMetadata>;
}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<EquipmentDiscoveryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [comparing, setComparing] = useState(false);
  const [selection, setSelection] = useState<EquipmentSelectResult | null>(null);
  const [pendingReview, setPendingReview] = useState<ParameterChange[] | null>(null);

  // Which requirement bounds have moved since this shortlist was produced.
  //
  // Recomputed on every render from the CONCEPT, against the bounds the
  // backend reported using. That is a value comparison, not a second copy of
  // `requirement_from_concept` — the rule for what a requirement reads stays
  // where it belongs, and this only notices that the answer would differ.
  const staleBounds: BoundChange[] = useMemo(() => {
    if (!result) return [];
    return boundChanges(
      recordedBounds(result.requirement),
      currentBounds(draft, result.requirement.station_id),
    );
  }, [result, draft]);
  const stale = staleBounds.length > 0;

  // No sync effect any more: there is nothing to sync. The parent holds the
  // station, so re-verification moving the bottleneck reaches this picker as
  // an ordinary prop change rather than as two copies being reconciled.

  // A shortlist belongs to one station. Changing station therefore discards
  // it rather than leaving last station's answer on screen under this
  // station's name.
  useEffect(() => {
    if (result && result.requirement.station_id !== stationId) {
      setResult(null);
      setSelection(null);
      setPendingReview(null);
      setComparing(false);
    }
  }, [stationId, result]);

  const storedForStation = storedSelections?.[stationId] ?? null;

  // A stored selection is checked on its own, not only when a shortlist
  // happens to be on screen.
  //
  // This is the path that actually matters. Editing an engineering input
  // routes back to the concept builder, which unmounts this panel and takes
  // the live shortlist with it — so the state an engineer returns to is a
  // RESTORED selection with no shortlist behind it. Checking only the live
  // result would leave exactly that case unguarded, which is the case the
  // phase is about.
  const storedStale: BoundChange[] = useMemo(() => {
    if (!storedForStation?.bounds) return [];
    return boundChanges(storedForStation.bounds, currentBounds(draft, stationId));
  }, [storedForStation, draft, stationId]);

  async function find() {
    setBusy(true);
    setError(null);
    setSelection(null);
    setPendingReview(null);
    try {
      const found = await discoverEquipment(draft, stationId, strategyContext);
      setResult(found);
      onRequirementsComputed?.(found.requirement.station_id);
    } catch (err) {
      setError(describeRequestFailure(err));
    } finally {
      setBusy(false);
    }
  }

  async function choose(candidateId: string) {
    setError(null);
    try {
      const chosen = await selectEquipment(draft, stationId, candidateId);
      setSelection(chosen);
      // The bounds travel with the choice, so a reload can CHECK it rather
      // than trust it.
      onSelected?.(chosen, result ? recordedBounds(result.requirement) : undefined);
      // Adopting a manufacturer's figure into a verified concept is a
      // separate decision, so it is offered for review rather than done.
      setPendingReview(chosen.proposed_changes.length ? chosen.proposed_changes : null);
    } catch (err) {
      setError(describeRequestFailure(err));
    }
  }

  if (!result) {
    return (
      <div className="equipment" data-testid="equipment-discovery">
        {/* Before any shortlist exists, the only equipment evidence on screen
            is what the project restored — so it is checked here too. A
            selection made against a requirement that has since moved must
            never come back looking current. */}
        {storedForStation && storedStale.length > 0 && (
          <StoredSelectionStale
            manufacturer={storedForStation.manufacturer}
            model={storedForStation.model}
            changes={storedStale}
          />
        )}
        {storedForStation && storedStale.length === 0 && (
          <p className="equipment__stored" data-testid="equipment-stored-current">
            Under consideration for this station: {storedForStation.manufacturer}{" "}
            {storedForStation.model}. Still judged against the station's current requirements.
          </p>
        )}
        <div className="equipment__cta">
          <label className="equipment__picker">
            <span className="fm-label">Station</span>
            <select
              value={stationId}
              onChange={(event) => onStationChange(event.target.value)}
              data-testid="equipment-station-select"
            >
              {draft.stages.map((stage) => (
                <option key={stage.id} value={stage.id}>
                  {stage.name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="fm-btn-secondary"
            onClick={find}
            disabled={busy}
            aria-busy={busy}
            data-testid="concept-find-equipment"
          >
            {busy && <Loader2 size={14} strokeWidth={2} aria-hidden="true" className="equipment__spin" />}
            {busy ? "Searching equipment data…" : "Find equipment candidates"}
          </button>
          <span className="equipment__cta-label">
            Derives what this station must be able to do, then asks every bundled catalogue
            which records declare that capability. The catalogues ship with Fabrivium — no
            live manufacturer search is connected.
          </span>
        </div>
        {error && (
          <p className="equipment__error" data-testid="equipment-error">
            {error}
          </p>
        )}
      </div>
    );
  }

  const { requirement, assessments } = result;

  return (
    <div className="equipment" data-testid="equipment-discovery">
      <header className="equipment__head">
        <div>
          <p className="equipment__title">{requirement.station_name} — engineering requirements</p>
          <p className="equipment__provenance" data-testid="equipment-requirement-provenance">
            {requirement.provenance}
          </p>
        </div>
        {assessments.length > 0 && (
          <FreshnessBadge freshness={result.freshness} verifiedOn={result.verified_on} />
        )}
      </header>

      {/* The requirement below was true when this search ran and is not the
          station's requirement any more. Everything under it — the bounds,
          the verdicts, the shortlist — is an answer to the old question, so
          it is marked before it is read rather than after. */}
      {stale && <StaleFinding changes={staleBounds} busy={busy} onRerun={find} />}

      {requirement.required_capability && (
        <p className="equipment__capability" data-testid="equipment-capability">
          <strong>Required capability:</strong>{" "}
          {requirement.required_capability.replace(/_/g, " ").toLowerCase()} —{" "}
          {requirement.capability_statement}
        </p>
      )}

      <dl
        className={`equipment__requirement${stale ? " equipment__requirement--stale" : ""}`}
        data-testid="equipment-requirement"
        data-stale={stale}
      >
        <Bound label="Process" text={requirement.process_category} />
        <Bound
          label="Required cycle"
          value={requirement.max_cycle_time_seconds}
          format={(v) => `≤ ${v} s`}
          testId="equipment-required-cycle"
        />
        {requirement.operations_per_unit.value != null && (
          <Bound
            label="Operations / unit"
            value={requirement.operations_per_unit}
            format={(v) => `${v}`}
            testId="equipment-operations-per-unit"
          />
        )}
        <Bound label="Capacity" value={requirement.required_capacity} format={(v) => `≥ ${v}`} />
        <Bound label="Operators" value={requirement.operator_requirement} format={(v) => `≤ ${v}`} />
        <Bound
          label="Footprint"
          value={requirement.max_width_m}
          format={(v) =>
            requirement.max_length_m.value != null ? `≤ ${v} × ${requirement.max_length_m.value} m` : `≤ ${v} m`
          }
        />
        <Bound
          label="Budget"
          value={requirement.budget_limit}
          format={(v) => `≤ €${Number(v).toLocaleString("en-US")}`}
        />
      </dl>

      {requirement.optional_preferences.map((preference) => (
        <p key={preference} className="equipment__preference">
          {preference} — recorded as a preference, not checked against candidates.
        </p>
      ))}

      <CatalogStrip catalogs={result.catalogs} />

      {result.note && (
        <div className="equipment__toolbar">
          <p className="equipment__note" data-testid="equipment-note">
            {result.note}
          </p>
          <button
            type="button"
            className="fm-btn-secondary"
            onClick={() => setResult(null)}
            data-testid="equipment-change-station"
          >
            Change station
          </button>
        </div>
      )}

      {assessments.length > 0 && (
        <>
          <div className="equipment__toolbar">
            <p className="equipment__count" data-testid="equipment-candidate-count">
              {assessments.length} source-backed candidates
            </p>
            <button
              type="button"
              className="fm-btn-secondary"
              onClick={() => setResult(null)}
              data-testid="equipment-change-station"
            >
              Change station
            </button>
            <button
              type="button"
              className="fm-btn-secondary"
              onClick={() => setComparing((c) => !c)}
              aria-expanded={comparing}
              data-testid="equipment-compare-toggle"
            >
              {comparing ? "Hide comparison" : "Compare"}
            </button>
          </div>

          {comparing ? (
            <CompareTable assessments={assessments} />
          ) : (
            <ul className="equipment__cards">
              {assessments.map((assessment) => {
                // A selection made in THIS session wins over a stored one:
                // it is the more recent statement about the same station.
                const chosenId =
                  selection?.selection.candidate_id ?? storedForStation?.candidate_id ?? null;
                const isChosen = chosenId === assessment.candidate.candidate_id;
                return (
                  <CandidateCard
                    key={assessment.candidate.candidate_id}
                    assessment={assessment}
                    selected={isChosen}
                    state={candidateState(assessment, { stale, underConsideration: isChosen })}
                    onSelect={() => choose(assessment.candidate.candidate_id)}
                  />
                );
              })}
            </ul>
          )}
        </>
      )}

      {(selection || storedForStation) && (
        <div className="equipment__selected" data-testid="equipment-selected">
          <p className="equipment__selected-title">
            <Check size={14} strokeWidth={2.2} aria-hidden="true" />
            {/* "Under consideration for", not "selected for the concept". */}
            Under consideration for this station:{" "}
            {selection?.selection.manufacturer ?? storedForStation?.manufacturer}{" "}
            {selection?.selection.model ?? storedForStation?.model}
          </p>
          <p className="equipment__selected-note">
            {selection?.affects_simulation
              ? "This manufacturer publishes values that differ from the concept's. Nothing has been changed — review them below."
              : "Recorded as equipment under engineering consideration. It is not adopted, not purchased, and its cycle time is not proven. The concept's verified cycle time, capacity and operator count are unchanged."}
          </p>
          {!selection && storedStale.length > 0 && (
            <p className="equipment__selected-stale" data-testid="equipment-selection-stale">
              Chosen against requirements that have since changed:{" "}
              {storedStale.map((c) => c.description).join("; ")}.
            </p>
          )}
          {storedForStation?.superseded && storedForStation.superseded.length > 0 && (
            <ul className="equipment__superseded" data-testid="equipment-superseded">
              {storedForStation.superseded.map((previous) => (
                <li key={`${previous.candidate_id}-${previous.superseded_at}`}>
                  Previously under consideration: {previous.manufacturer} {previous.model}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {pendingReview && (
        <ParameterReview changes={pendingReview} onDismiss={() => setPendingReview(null)} />
      )}

      {error && (
        <p className="equipment__error" data-testid="equipment-error">
          {error}
        </p>
      )}
    </div>
  );
}

/** Which sources were asked, and which could not answer. */
function CatalogStrip({ catalogs }: { catalogs: ConsultedCatalog[] }) {
  if (!catalogs.length) return null;
  const answered = catalogs.filter((c) => c.available);
  const missing = catalogs.filter((c) => !c.available);

  return (
    <div className="equipment__catalogs" data-testid="equipment-catalogs">
      <p className="equipment__catalogs-line">
        <span className="fm-label">Sources asked</span>
        {answered.map((catalog) => (
          <span key={catalog.catalog_id} title={catalog.trust_statement}>
            {catalog.display_name} ({catalog.candidate_count})
          </span>
        ))}
      </p>
      {missing.map((catalog) => (
        <p
          key={catalog.catalog_id}
          className="equipment__catalogs-missing"
          data-testid={`equipment-catalog-unavailable-${catalog.catalog_id}`}
        >
          <CircleAlert size={12} strokeWidth={2.2} aria-hidden="true" />
          {catalog.display_name} could not be consulted. {catalog.unavailable_reason}
        </p>
      ))}
    </div>
  );
}

/** Where the manufacturer values come from — never left to the reader to
 * assume, and never implying a search that is not connected.
 *
 * §20: both branches say "bundled", because both are. There is no live
 * manufacturer feed in this build, and the word "cached" on its own invites
 * the reading that a live one exists and this happens to be a copy of it. */
function FreshnessBadge({ freshness, verifiedOn }: { freshness: string; verifiedOn: string | null }) {
  if (freshness === "LIVE") {
    // Reachable only if a future version adds a live feed. Until then this
    // branch cannot fire, and "Live data" would be a capability claim for
    // something that does not exist. The catalogue is bundled, and says so.
    return (
      <span className="equipment__freshness equipment__freshness--live" data-testid="equipment-freshness">
        Bundled catalogue
      </span>
    );
  }
  return (
    <span className="equipment__freshness" data-testid="equipment-freshness">
      Bundled manufacturer data · retrieved {verifiedOn ?? "on an unrecorded date"}
    </span>
  );
}

function Bound({
  label,
  value,
  text,
  format,
  testId,
}: {
  label: string;
  value?: { value: number | null; source: string; detail: string | null };
  text?: string;
  format?: (v: number) => string;
  testId?: string;
}) {
  return (
    <div>
      <dt className="fm-label">{label}</dt>
      <dd data-testid={testId}>
        {text ??
          (value && value.value != null ? (
            <>
              {format ? format(value.value) : value.value}{" "}
              <SourceBadge source={value.source as ValueSource} detail={value.detail} />
            </>
          ) : (
            <span className="equipment__unknown">Not established</span>
          ))}
      </dd>
    </div>
  );
}

/** This shortlist no longer answers the station in front of the engineer. */
function StaleFinding({
  changes,
  busy,
  onRerun,
}: {
  changes: BoundChange[];
  busy: boolean;
  onRerun: () => void;
}) {
  return (
    <div className="equipment__stale" role="status" data-testid="equipment-stale">
      <p className="equipment__stale-title">
        <AlertTriangle size={14} strokeWidth={2.2} aria-hidden="true" />
        This station's requirements changed after these candidates were found
      </p>
      <ul className="equipment__stale-changes" data-testid="equipment-stale-changes">
        {changes.map((change) => (
          <li key={change.field}>{change.description}</li>
        ))}
      </ul>
      <p className="equipment__stale-note">
        Everything below was judged against the previous requirement. A bound
        that has tightened can turn a match into a contradiction, so nothing
        here should be read as current until the search is run again.
      </p>
      <button
        type="button"
        className="fm-btn-secondary fm-btn--auto"
        onClick={onRerun}
        disabled={busy}
        data-testid="equipment-rerun"
      >
        {busy ? (
          <Loader2 size={13} strokeWidth={2} aria-hidden="true" className="equipment__spin" />
        ) : (
          <RefreshCw size={13} strokeWidth={2.2} aria-hidden="true" />
        )}
        Search again against the current requirement
      </button>
    </div>
  );
}

/** A selection the project restored, made against requirements that have since moved. */
function StoredSelectionStale({
  manufacturer,
  model,
  changes,
}: {
  manufacturer: string;
  model: string;
  changes: BoundChange[];
}) {
  return (
    <div className="equipment__stale" role="status" data-testid="equipment-stored-stale">
      <p className="equipment__stale-title">
        <AlertTriangle size={14} strokeWidth={2.2} aria-hidden="true" />
        {manufacturer} {model} was chosen against different requirements
      </p>
      <ul className="equipment__stale-changes" data-testid="equipment-stored-stale-changes">
        {changes.map((change) => (
          <li key={change.field}>{change.description}</li>
        ))}
      </ul>
      <p className="equipment__stale-note">
        It is still recorded as under consideration — that was your decision, not
        Fabrivium's to undo. Search again to see how it stands against the station
        as it is now.
      </p>
    </div>
  );
}

function CandidateCard({
  assessment,
  selected,
  state,
  onSelect,
}: {
  assessment: CandidateAssessment;
  selected: boolean;
  /** What this finding amounts to right now. */
  state: EquipmentState;
  onSelect: () => void;
}) {
  const { candidate, compatibility } = assessment;
  const source = candidate.sources[0];
  const tally = checkTally(assessment);

  return (
    <li className="equipment-card" data-testid={`equipment-card-${candidate.candidate_id}`}>
      <header className="equipment-card__head">
        <div>
          <p className="equipment-card__maker">{candidate.manufacturer}</p>
          <p className="equipment-card__model">{candidate.model}</p>
        </div>
        <span
          className={`equipment-state equipment-state--${state.toLowerCase()}`}
          data-testid={`equipment-state-${candidate.candidate_id}`}
          data-state={state}
        >
          {selected && <Check size={12} strokeWidth={2.4} aria-hidden="true" />}
          {EQUIPMENT_STATE_LABEL[state]}
        </span>
      </header>

      {/* §18 — the badge got shorter, so the qualification became explicit. */}
      <p className="equipment-card__state-note" data-testid={`equipment-state-note-${candidate.candidate_id}`}>
        {EQUIPMENT_STATE_NOTE[state]}
      </p>

      {/* The tally sits beside the state so neither can stand alone. */}
      <p className="equipment-card__tally" data-testid={`equipment-tally-${candidate.candidate_id}`}>
        {tally.passed} matched · {tally.contradicted} contradicted ·{" "}
        {tally.unconfirmable} not confirmable from published data
      </p>

      <p className="equipment-card__scope">{candidate.product_scope}</p>

      <p className={`equipment-card__claim equipment-card__claim--${assessment.claim.toLowerCase()}`}
         data-testid={`equipment-claim-${candidate.candidate_id}`}>
        {assessment.claim_text}
      </p>

      <p className="equipment-card__counts" data-testid={`equipment-counts-${candidate.candidate_id}`}>
        <StatusPill status="PASS" count={assessment.pass_count} />
        <StatusPill status="FAIL" count={assessment.fail_count} />
        <StatusPill status="UNKNOWN" count={assessment.unknown_count} />
      </p>

      <p className="equipment-card__origin" data-testid={`equipment-origin-${candidate.candidate_id}`}>
        <span className={`equipment-origin equipment-origin--${candidate.catalog_kind.toLowerCase()}`}>
          {CATALOG_KIND_LABEL[candidate.catalog_kind]}
        </span>
        <EvidenceLine evidence={assessment.evidence} />
      </p>

      {/* §19 — WHAT A FIRST GLANCE IS FOR. */}
      <dl className="equipment-card__specs">
        <Spec label="Cycle time" spec={candidate.cycle_time_seconds} unit="s" />
        <Spec label="Torque" spec={candidate.torque_max_nm} unit="Nm" prefix={candidate.torque_min_nm} />
        <Spec label="Footprint" spec={candidate.length_mm} unit="mm" second={candidate.width_mm} />
        <div className="equipment-card__interfaces">
          <dt className="fm-label">Interfaces</dt>
          <dd>
            {candidate.interfaces.length ? (
              candidate.interfaces.join(", ")
            ) : (
              <span className="equipment__unknown">Not published</span>
            )}
          </dd>
        </div>
        <div>
          <dt className="fm-label">Price</dt>
          <dd data-testid={`equipment-price-${candidate.candidate_id}`}>
            {candidate.price_status === "PUBLISHED" && candidate.price.value != null ? (
              `€${candidate.price.value.toLocaleString("en-US")}`
            ) : candidate.price_status === "QUOTE_REQUIRED" ? (
              // Not a hole in our data — it is how this market sells.
              <span className="equipment__unknown">Quote required</span>
            ) : (
              <span className="equipment__unknown">Not published</span>
            )}
          </dd>
        </div>
      </dl>

      {candidate.caveats.length > 0 && (
        <ul className="equipment-card__caveats" data-testid={`equipment-caveats-${candidate.candidate_id}`}>
          {candidate.caveats.map((caveat) => (
            <li key={caveat}>{caveat}</li>
          ))}
        </ul>
      )}

      <details className="equipment-card__more" data-testid={`equipment-more-${candidate.candidate_id}`}>
        <summary>More engineering details</summary>
        <dl className="equipment-card__specs">
          <Spec label="Weight" spec={candidate.weight_kg} unit="kg" />
          <div>
            <dt className="fm-label">CAD</dt>
            <dd>
              {candidate.cad_available === true ? (
                candidate.cad_format ?? "Available"
              ) : candidate.cad_available === false ? (
                "Not offered"
              ) : (
                <span className="equipment__unknown">Not established</span>
              )}
            </dd>
          </div>
        </dl>
      </details>

      <details className="equipment-card__why">
        <summary>Matched and unverified requirements</summary>
        <CheckGroup
          title="Matched"
          checks={compatibility.checks.filter((c) => c.status === "PASS")}
          empty="Nothing could be matched against published data."
        />
        <CheckGroup
          title="Contradicted"
          checks={compatibility.checks.filter((c) => c.status === "FAIL")}
          empty="Nothing is contradicted by a published value."
        />
        {/* Last and never collapsed away: the requirements nobody has
            answered are the ones an engineer would otherwise assume met. */}
        <CheckGroup
          title="Not verified"
          checks={compatibility.checks.filter((c) => c.status === "UNKNOWN")}
          empty="Every requirement this concept states was checked."
        />
      </details>

      <footer className="equipment-card__actions">
        {source && (
          <a
            className="fm-btn-secondary"
            href={source.url}
            target="_blank"
            rel="noreferrer noopener"
            data-testid={`equipment-source-${candidate.candidate_id}`}
          >
            <ExternalLink size={13} strokeWidth={2} aria-hidden="true" />
            View source
          </a>
        )}
        {/* Not "select for concept": nothing is written into the concept,
            nothing is bought, and no cycle time is proven. This records that
            the engineer wants this machine on the table for this station,
            which is the only claim the act supports.

            Once it IS on the table the control has to say so. In the golden
            run a candidate already marked UNDER CONSIDERATION still offered
            "Consider for this station", so the one button on the card gave
            no sign the click had landed and read as an action still to be
            taken. The state is now the label, and the affordance beside it
            is the one that remains available. */}
        {selected ? (
          <span
            className="equipment-card__considered"
            data-testid={`equipment-considered-${candidate.candidate_id}`}
          >
            <Check size={13} strokeWidth={2.4} aria-hidden="true" />
            Under consideration
          </span>
        ) : (
          <button
            type="button"
            className="fm-btn-primary"
            onClick={onSelect}
            data-testid={`equipment-select-${candidate.candidate_id}`}
          >
            Consider for this station
          </button>
        )}
      </footer>

      {source && (
        <p className="equipment-source" data-testid={`equipment-source-line-${candidate.candidate_id}`}>
          {/* §20 — two different things were reading as one. */}
          <span className="equipment-source__kind">Manufacturer source</span>
          <span>
            {source.title} · retrieved {source.retrieved_at}
          </span>
          <span className="equipment-source__kind">Fabrivium requirement check</span>
          <span>Against this station's current project revision</span>
        </p>
      )}
    </li>
  );
}

function Spec({
  label,
  spec,
  unit,
  second,
  prefix,
}: {
  label: string;
  spec: PublishedSpec;
  unit: string;
  second?: PublishedSpec;
  prefix?: PublishedSpec;
}) {
  let body: ReactNode = <span className="equipment__unknown">Not published</span>;
  if (spec.value != null) {
    if (second?.value != null) body = `${spec.value} × ${second.value} ${unit}`;
    else if (prefix?.value != null) body = `${prefix.value}–${spec.value} ${unit}`;
    else body = `${spec.value} ${unit}`;
  }
  return (
    <div>
      <dt className="fm-label">{label}</dt>
      <dd>{body}</dd>
    </div>
  );
}

/** How each kind of source may be described, in one short phrase. */
const CATALOG_KIND_LABEL: Record<CatalogKind, string> = {
  RESEARCHED_MANUFACTURER: "Manufacturer data",
  INTERNAL_ASSET_POOL: "Already owned",
  APPROVED_SUPPLIER: "Approved supplier",
  EXTERNAL_SOURCE: "External source",
};

/** Counts by evidence level, spelled out rather than scored. */
function EvidenceLine({ evidence }: { evidence: EvidenceSummary }) {
  const parts: string[] = [];
  if (evidence.known_specification) parts.push(`${evidence.known_specification} from source documents`);
  // Kept as its own phrase: a value WE computed is not a published one.
  if (evidence.source_derived) parts.push(`${evidence.source_derived} derived by Fabrivium`);
  if (evidence.estimated) parts.push(`${evidence.estimated} estimated`);
  if (evidence.quote_required) parts.push(`${evidence.quote_required} quote required`);
  if (evidence.unknown) parts.push(`${evidence.unknown} not published`);
  return <span className="equipment-card__evidence">{parts.join(" · ")}</span>;
}

/** One labelled group of checks. */
function CheckGroup({
  title,
  checks,
  empty,
}: {
  title: string;
  checks: CompatibilityCheck[];
  empty: string;
}) {
  return (
    <div className="equipment-card__group">
      <p className="fm-label">
        {title} ({checks.length})
      </p>
      {checks.length === 0 ? (
        <p className="equipment__unknown">{empty}</p>
      ) : (
        <ul>
          {checks.map((check) => (
            <li key={check.field}>
              <StatusIcon status={check.status} /> <strong>{check.label}</strong> — required{" "}
              {check.requirement_text}, published {check.candidate_text}
              {check.reason ? `. ${check.reason}` : ""}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The counts, in the product's own words. */
const STATUS_WORD: Record<CheckStatus, string> = {
  PASS: "matched",
  FAIL: "contradicted",
  UNKNOWN: "not verified",
};

function StatusPill({ status, count }: { status: CheckStatus; count: number }) {
  return (
    <span className={`equipment-pill equipment-pill--${status.toLowerCase()}`}>
      {count} {STATUS_WORD[status]}
    </span>
  );
}

function StatusIcon({ status }: { status: CheckStatus }) {
  const size = 12;
  if (status === "PASS") return <Check size={size} strokeWidth={2.6} aria-label="Pass" className="status-pass" />;
  if (status === "FAIL") return <X size={size} strokeWidth={2.6} aria-label="Fail" className="status-fail" />;
  return <Minus size={size} strokeWidth={2.6} aria-label="Unknown" className="status-unknown" />;
}

/** Side by side against the requirement — §19. */

/** The checks that belong in a first glance. */
const PRIMARY_CHECK_FIELDS = new Set([
  "capability",
  "cycle_time",
  "footprint_width",
  "footprint_length",
  "budget",
]);

function CompareTable({ assessments }: { assessments: CandidateAssessment[] }) {
  const [showAll, setShowAll] = useState(false);

  const allRows = assessments[0].compatibility.checks.map((c) => ({ field: c.field, label: c.label }));
  const primary = allRows.filter((row) => PRIMARY_CHECK_FIELDS.has(row.field));
  const secondary = allRows.filter((row) => !PRIMARY_CHECK_FIELDS.has(row.field));

  const checkRow = (row: { field: string; label: string }) => {
    const first = assessments[0].compatibility.checks.find((c) => c.field === row.field);
    return (
      <tr key={row.field}>
        <th scope="row">
          {row.label}
          <span>{first?.requirement_text}</span>
        </th>
        {assessments.map((a) => {
          const check = a.compatibility.checks.find((c) => c.field === row.field);
          return (
            <td key={a.candidate.candidate_id} data-status={check?.status ?? "UNKNOWN"}>
              <StatusIcon status={check?.status ?? "UNKNOWN"} />
              <span>{check?.candidate_text ?? "Not published"}</span>
            </td>
          );
        })}
      </tr>
    );
  };

  return (
    <div className="equipment__compare-wrap">
      <table className="equipment__compare" data-testid="equipment-compare">
        <thead>
          <tr>
            <th scope="col">Requirement</th>
            {assessments.map((a) => (
              <th scope="col" key={a.candidate.candidate_id}>
                {a.candidate.manufacturer}
                <span>{a.candidate.model}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">
              Assessment
              <span>the highest conclusion the evidence supports</span>
            </th>
            {assessments.map((a) => (
              <td key={a.candidate.candidate_id} data-claim={a.claim}>
                <span>{a.claim.replace(/_/g, " ").toLowerCase()}</span>
              </td>
            ))}
          </tr>

          {/* The size of the validation gap, before anything is expanded. */}
          <tr data-testid="compare-assessment">
            <th scope="row">
              Checked
              <span>how much of the requirement could be compared</span>
            </th>
            {assessments.map((a) => {
              const tally = checkTally(a);
              return (
                <td
                  key={a.candidate.candidate_id}
                  data-status={tally.contradicted > 0 ? "FAIL" : "INFO"}
                  data-testid={`compare-tally-${a.candidate.candidate_id}`}
                >
                  <span>
                    {tally.passed} matched · {tally.contradicted} contradicted ·{" "}
                    {tally.unconfirmable} not verified
                  </span>
                </td>
              );
            })}
          </tr>

          {primary.map(checkRow)}

          {/* Published specs an engineer chooses on that are not checks
              against a bound: the station states no torque requirement and no
              interface requirement, so there is nothing to compare them to —
              but they are how two otherwise indistinguishable machines
              differ, and they were only ever on the cards. */}
          <tr>
            <th scope="row">
              Torque
              <span>what the source publishes</span>
            </th>
            {assessments.map((a) => (
              <td
                key={a.candidate.candidate_id}
                data-status="INFO"
                data-testid={`compare-torque-${a.candidate.candidate_id}`}
              >
                <span>
                  {a.candidate.torque_max_nm.value != null ? (
                    a.candidate.torque_min_nm.value != null ? (
                      `${a.candidate.torque_min_nm.value}–${a.candidate.torque_max_nm.value} Nm`
                    ) : (
                      `${a.candidate.torque_max_nm.value} Nm`
                    )
                  ) : (
                    <span className="equipment__unknown">Not published</span>
                  )}
                </span>
              </td>
            ))}
          </tr>

          <tr>
            <th scope="row">
              Interfaces
              <span>how it integrates with the line</span>
            </th>
            {assessments.map((a) => (
              <td
                key={a.candidate.candidate_id}
                data-status="INFO"
                data-testid={`compare-interfaces-${a.candidate.candidate_id}`}
              >
                <span>
                  {a.candidate.interfaces.length ? (
                    a.candidate.interfaces.join(", ")
                  ) : (
                    <span className="equipment__unknown">Not published</span>
                  )}
                </span>
              </td>
            ))}
          </tr>

          {/* Price and source were on the cards and missing from the
              comparison, which is the one view an engineer uses to CHOOSE.
              Comparing four machines on capability and footprint while the
              commercial position and the provenance sit on another screen is
              how a decision gets made on half the evidence. */}
          <tr>
            <th scope="row">
              Price
              <span>what the source publishes</span>
            </th>
            {assessments.map((a) => (
              <td
                key={a.candidate.candidate_id}
                data-status="INFO"
                data-testid={`compare-price-${a.candidate.candidate_id}`}
              >
                <span>
                  {a.candidate.price_status === "PUBLISHED" && a.candidate.price.value != null ? (
                    `€${a.candidate.price.value.toLocaleString("en-US")}`
                  ) : a.candidate.price_status === "QUOTE_REQUIRED" ? (
                    // Not a hole in our data — it is how this market sells,
                    // and it must not read as a mark against the machine.
                    <span className="equipment__unknown">Quote required</span>
                  ) : (
                    <span className="equipment__unknown">Not published</span>
                  )}
                </span>
              </td>
            ))}
          </tr>

          {showAll && secondary.map(checkRow)}

          {secondary.length > 0 && (
            <tr className="equipment__compare-more">
              <th scope="row" colSpan={assessments.length + 1}>
                <button
                  type="button"
                  className="fm-btn-tertiary"
                  aria-expanded={showAll}
                  onClick={() => setShowAll((open) => !open)}
                  data-testid="equipment-compare-more"
                >
                  {showAll
                    ? "Hide the remaining engineering details"
                    : `More engineering details (${secondary.length})`}
                </button>
              </th>
            </tr>
          )}

          <tr>
            <th scope="row">
              Source
              <span>manufacturer data, and when it was read</span>
            </th>
            {assessments.map((a) => {
              const source = a.candidate.sources[0];
              return (
                <td
                  key={a.candidate.candidate_id}
                  data-status="INFO"
                  data-testid={`compare-source-${a.candidate.candidate_id}`}
                >
                  <span>
                    {source ? (
                      <>
                        <a href={source.url} target="_blank" rel="noreferrer noopener">
                          {source.title}
                        </a>
                        <em> · retrieved {source.retrieved_at}</em>
                      </>
                    ) : (
                      <span className="equipment__unknown">No source recorded</span>
                    )}
                  </span>
                </td>
              );
            })}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

/** The confirmation gate. */
function ParameterReview({ changes, onDismiss }: { changes: ParameterChange[]; onDismiss: () => void }) {
  return (
    <div className="equipment__review" data-testid="equipment-parameter-review">
      <p className="equipment__review-title">
        <CircleAlert size={14} strokeWidth={2.2} aria-hidden="true" />
        Published values differ from the concept
      </p>
      <ul>
        {changes.map((change) => (
          <li key={change.field}>
            Replace planning value{" "}
            <strong>
              {change.current_value ?? "not set"}
              {change.proposed_unit ? ` ${change.proposed_unit}` : ""}
            </strong>{" "}
            with manufacturer value{" "}
            <strong>
              {change.proposed_value}
              {change.proposed_unit ? ` ${change.proposed_unit}` : ""}
            </strong>
            ?
            {change.affects_simulation && (
              <em> Adopting this changes what the simulation computes; the concept would need re-verifying.</em>
            )}
          </li>
        ))}
      </ul>
      <p className="equipment__review-note">
        Nothing has been changed. The concept keeps its own values until each replacement is confirmed.
      </p>
      <button type="button" className="fm-btn-secondary" onClick={onDismiss} data-testid="equipment-review-dismiss">
        Keep the concept's values
      </button>
    </div>
  );
}
