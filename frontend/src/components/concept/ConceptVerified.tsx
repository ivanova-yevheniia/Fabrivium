import { useCallback, useRef, useState } from "react";
import { CheckCircle2, CircleAlert, FileOutput, Loader2, Send, SlidersHorizontal, XCircle } from "lucide-react";
import { useAppContext } from "../../state/AppContext";
import { statsFromStrategyMetrics } from "../../utils/executiveSummary";
import { effectiveStageLayout } from "../../utils/stage";
import { describeRequestFailure } from "../../api/client";
import {
  handoffToPlantSimulation,
  type PlantSimulationHandoffResult,
  type VerificationTier,
} from "../../api/handoff";
import { EquipmentDiscovery } from "./EquipmentDiscovery";
import { SensitivityPanel } from "./SensitivityPanel";
import { primaryInterventionPhrase } from "../../utils/interventionSummary";
import { ResolveInputs } from "./ResolveInputs";
import { EvidenceBadge, EvidenceNote } from "../project/EvidenceStatus";
import { statusOf } from "../../api/projects";

/** Phase 14 §10/§11 — what the concept has established, and what it has not. */
export function ConceptVerified() {
  const { state, updateConceptDraft, setEquipmentSelection, recordArtifact } = useAppContext();
  const [open, setOpen] = useState(false);
  const handoffRef = useRef<HTMLDivElement | null>(null);

  // The panel opens ~1,800 px below the button that opens it, so on a
  // 768px-tall screen nothing appears to happen — measured at y=2630 on the
  // results page. A pre-demo audit recorded this as the CTA "vanishing from
  // the DOM"; it had not, it was simply off-screen. On the last beat of the
  // golden path that reads as a dead end.
  const toggleHandoff = useCallback(() => {
    setOpen((current) => {
      const next = !current;
      if (next) {
        // After paint, so the panel exists to scroll to.
        requestAnimationFrame(() => {
          // jsdom has no scrollIntoView, and a test environment is not a
          // reason for the product to throw.
          handoffRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
        });
      }
      return next;
    });
  }, []);
  const [editingInputs, setEditingInputs] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PlantSimulationHandoffResult | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);

  // THE ONE SELECTED STATION for every station-specific panel below.
  //
  // The golden-run defect: the sensitivity panel was pinned to the verified
  // plan's bottleneck while the station picker was private to equipment
  // discovery, so changing the picker left a Screw fastening ×6 sweep on
  // screen with Cable connection ×2 selected. Two components, two answers to
  // "which station are we looking at", and the engineer could see both at
  // once.
  //
  // Null means "follow the plan" — the bottleneck stays the default and
  // still moves when re-verification moves it. It becomes a real id only
  // once the engineer chooses, and their choice then outranks the default.
  const [stationOverride, setStationOverride] = useState<string | null>(null);
  // The equipment an engineer has chosen to CONSIDER, per station. It goes
  // into the handoff as metadata so whoever opens the .spp knows which real
  // machine is on the table — and it stops there. Adopting a manufacturer's
  // cycle time into the concept is a separate, explicit decision made in
  // the review panel below; nothing here writes one into the model.
  //
  // P0 moved it out of this component's own useState and into the project.
  // It was engineering work that vanished on navigation — and, being local,
  // it could not be part of the project's dependency graph, so an engineer
  // could change what equipment was under consideration and the Siemens
  // export would go on presenting itself as current.
  const equipment = state.equipmentSelections;

  const arena = state.arena;
  const draft = state.concept.draft;
  const factory = state.factory;
  if (!arena || !factory || !draft) return null;

  const selected = arena.strategies.find((s) => s.strategy_id === state.selectedStrategyId);
  if (!selected) return null;

  // Falls back to the bottleneck when the chosen station is not in this
  // draft — a concept rebuilt without that station must not leave the panels
  // pointed at an id that no longer exists.
  const bottleneckStationId = selected.metrics.bottleneck_machine_id;
  const selectedStationId =
    stationOverride && draft.stages.some((stage) => stage.id === stationOverride)
      ? stationOverride
      : bottleneckStationId;
  const selectedStationName =
    draft.stages.find((stage) => stage.id === selectedStationId)?.name ?? selectedStationId;

  const after = statsFromStrategyMetrics(selected.metrics);
  const incompleteCost = arena.strategies.filter((s) => !s.commercially_complete).length;
  const verificationStale =
    statusOf(state.project.staleness, "SIMULATION_VERIFICATION") === "STALE";
  const equipmentCount = Object.keys(equipment).length;

  // The same resolver the 2D plan, the 3D twin and playback read, so the
  // model that reaches Plant Simulation is placed where the user last saw
  // it — including edits they applied themselves.
  const layout = effectiveStageLayout(state, state.selectedIteration);
  const productId = state.productId ?? arena.product_id;

  async function runHandoff() {
    if (!factory || !productId) return;
    setBusy(true);
    setResult(null);
    setRequestError(null);
    try {
      const outcome = await handoffToPlantSimulation({
        factory,
        product_id: productId,
        layout,
        equipment_selections: equipmentCount ? equipment : null,
      });
      setResult(outcome);
      // Only a handoff that actually verified is evidence. One that ran and
      // did not read back what it wrote is a report about a failure, and
      // stamping it would make a later input change look like the reason it
      // is not current.
      if (outcome.status === "COMPLETE") recordArtifact("SIEMENS_HANDOFF");
    } catch (error) {
      // The request itself failed — distinct from a handoff that ran and
      // did not verify, which comes back as a normal response.
      setRequestError(describeRequestFailure(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="concept-verified" data-testid="concept-verified">
      <header className="concept-verified__head">
        <p className="concept-verified__title">
          {/* "Verified" requires BOTH that the plan met the target and that
              the verification still answers the current inputs. Before P0
              only the first was checked, so changing a cycle time left the
              word "verified" standing over a run of the old one. */}
          {after.met && !verificationStale ? (
            <>
              <CheckCircle2 size={16} strokeWidth={2.2} aria-hidden="true" />
              Concept verified
            </>
          ) : (
            <>
              <CircleAlert size={16} strokeWidth={2.2} aria-hidden="true" />
              {verificationStale ? "Concept needs revalidation" : "Concept not yet verified"}
            </>
          )}
        </p>
        <p className="concept-verified__detail">
          What this concept has established, and what detailed engineering still has to decide.
        </p>
        {/* The badge, not the heading, is what an engineer scans. */}
        <EvidenceBadge artifact="SIMULATION_VERIFICATION" />
      </header>

      <EvidenceNote artifact="SIMULATION_VERIFICATION" />

      <dl className="concept-verified__grid">
        <div>
          <dt className="fm-label">Production target</dt>
          <dd data-testid="concept-verified-target">
            {after.met
              ? "Reached by the selected plan"
              : `Short by ${after.gapUnits.toLocaleString("en-US")}/day`}
          </dd>
        </div>
        <div>
          <dt className="fm-label">Process concept</dt>
          {/* Conditional, because it renders directly beneath a header that
              can read "Concept not yet verified". The unconditional form said
              "Validated by deterministic simulation" under that header — the
              most self-contradicting element in the product. Verification
              language appears only after the verification succeeded. */}
          <dd data-testid="concept-verified-process">
            {verificationStale
              ? "Simulated against inputs that have since changed"
              : after.met
                ? "Simulated deterministically — target met"
                : "Simulated deterministically — target not met"}
          </dd>
        </div>
        <div>
          <dt className="fm-label">Layout</dt>
          <dd>Concept level — not detailed engineering</dd>
        </div>
        <div>
          <dt className="fm-label">Equipment</dt>
          <dd data-testid="concept-verified-equipment">
            {/* "Under consideration", never "selected equipment": a
                candidate has not proved anything about the station's cycle
                time, and no line here may imply that it has. */}
            {equipmentCount === 0
              ? "Requirements defined · no specific machine selected"
              : `Requirements defined · ${equipmentCount} station${
                  equipmentCount === 1 ? "" : "s"
                } with equipment under consideration`}
          </dd>
        </div>
        <div>
          <dt className="fm-label">Commercial data</dt>
          <dd data-testid="concept-verified-cost">
            {incompleteCost === 0
              ? "Complete for every option"
              : `Incomplete for ${incompleteCost} of ${arena.strategies.length} options`}
          </dd>
        </div>
      </dl>

      <div className="concept-verified__actions">
        {/* An engineering input is not settled because a result was computed from it. */}
        <button
          type="button"
          className="fm-btn-secondary"
          onClick={() => setEditingInputs(true)}
          data-testid="concept-verified-edit-inputs"
        >
          <SlidersHorizontal size={14} strokeWidth={2} aria-hidden="true" />
          Change an engineering input
        </button>
        <button
          type="button"
          className="fm-btn-secondary"
          onClick={toggleHandoff}
          aria-expanded={open}
          data-testid="concept-handoff-toggle"
        >
          <FileOutput size={14} strokeWidth={2} aria-hidden="true" />
          {open ? "Hide handoff contents" : "Prepare engineering handoff"}
        </button>
      </div>

      {editingInputs && draft && (
        <ResolveInputs
          isExampleProject={Boolean(state.project?.isExample)}
          draft={draft}
          onClose={() => setEditingInputs(false)}
          onDraftChange={(next) => void updateConceptDraft(next)}
          onEstimateStage={() => setEditingInputs(false)}
        />
      )}

      {open && (
        <div className="concept-verified__handoff" data-testid="concept-handoff" ref={handoffRef}>
          {/* Audit §14 — the list above the button used to name eight
              things the CONCEPT holds, immediately above a button that
              transfers five of them. Nothing said so, and the natural
              reading is that pressing the button sends the list. Split, so
              the claim beside the button is the claim the button keeps. */}
          {/* §21 — THE EXPORT TARGET, BEFORE THE BUTTON. */}
          <div className="handoff-target" data-testid="handoff-target">
            <p className="handoff-target__what">
              {/* The exporter's own words for what it writes
                  (`export_scope_label`), so the statement before the button
                  and the one in the result cannot describe the same file
                  differently. */}
              Exporting:{" "}
              <strong data-testid="handoff-target-scope">Baseline engineering concept</strong>
            </p>
            <p className="handoff-target__why">
              The .spp contains the concept as it currently stands — not{" "}
              {selected.label}. A plan is a set of changes Fabrivium verified by simulation;
              no factory model has been built for one, so there is nothing of it to export.
            </p>
            {/* Stated as its own line rather than left inside the paragraph above. */}
            <p className="handoff-target__caveat" data-testid="handoff-plan-not-exported">
              {selected.label} is not exported:{" "}
              {primaryInterventionPhrase(selected.actions) ?? "its changes"} has no representation
              in the Plant Simulation handoff, so this model does not reproduce{" "}
              {selected.metrics.completed_units.toLocaleString("en-US")}/day.
            </p>
          </div>

          <p className="concept-verified__handoff-title">
            Transfers into the Plant Simulation model
          </p>
          <ul data-testid="handoff-contents-transferred">
            <li>Process graph and route order</li>
            <li>Per-station cycle time and capacity</li>
            <li>Layout coordinates</li>
            <li>Source and drain, and the flow connections between stages</li>
            {/* Buffers moved up from the "not carried" list when the
                cross-simulator work made them real. They are built as
                MaterialFlow buffers, wired between their two stations, and
                their capacity is read back out of the reopened model like
                every other value. Leaving them listed as retained-only
                understated the handoff — and it understated it on exactly
                the point that matters most: a Plant Simulation line built
                WITHOUT them is a zero-buffer blocking line, which measured
                1,413 units/day against the same line's 2,462. */}
            <li>Buffers, their capacity and their wiring between stages</li>
          </ul>

          <p className="concept-verified__handoff-title">
            Held in the concept, but not carried into Plant Simulation
          </p>
          <ul data-testid="handoff-contents-retained">
            {/* The workforce boundary, stated in the product rather than only in a report. */}
            <li>Operator demand per station, and the shared workforce pool</li>
            <li>Operating model — shifts and hours</li>
            <li>Verified simulation results for every explored option</li>
            <li>Assumptions, their sources, and what is still unresolved</li>
            {/* The equipment boundary belongs in this list, not only in the
                result panel's exclusions. A candidate travels as text on the
                station — manufacturer, model, source — and no supplier
                geometry or part number is instantiated, so the shapes in the
                model are Plant Simulation's generic ones. */}
            <li>
              Supplier equipment geometry and part numbers. A candidate under consideration
              travels as <strong>text metadata</strong> on the generic station — manufacturer,
              model and evidence source — so the shapes in the model are Plant Simulation's
              own. No supplier CAD is instantiated, and no unverified manufacturer performance
              figure is transferred.
            </li>
          </ul>

          <div className="concept-verified__transfer">
            <button
              type="button"
              className="fm-btn-primary"
              onClick={runHandoff}
              disabled={busy}
              aria-busy={busy}
              data-testid="handoff-plant-simulation"
            >
              {busy ? (
                <Loader2 size={14} strokeWidth={2} aria-hidden="true" className="concept-verified__spin" />
              ) : (
                <Send size={14} strokeWidth={2} aria-hidden="true" />
              )}
              {busy ? "Building the model in Plant Simulation…" : "Transfer to Siemens Plant Simulation"}
            </button>
            <span className="concept-verified__next-label">
              Builds the model through Plant Simulation's automation interface and reads it back to verify it.
            </span>
          </div>

          {/* The scope is stated once, above, where it can inform the
              decision to press the button. Repeating it underneath was the
              third statement of one fact on one screen. */}

          <div
            className="concept-verified__result"
            role="status"
            aria-live="polite"
            data-testid="handoff-result"
          >
            {busy && (
              <p className="concept-verified__result-line" data-testid="handoff-busy">
                Plant Simulation is building and verifying the model. This takes a few seconds.
              </p>
            )}

            {requestError && !busy && (
              <div className="concept-verified__result-fail" data-testid="handoff-request-error">
                <p className="concept-verified__result-title">
                  <XCircle size={14} strokeWidth={2.2} aria-hidden="true" />
                  Handoff could not start
                </p>
                <p className="concept-verified__result-line">{requestError}</p>
              </div>
            )}

            {result && !busy && <HandoffOutcome result={result} selectedEquipmentCount={equipmentCount} />}
          </div>

          {/* Phase 18 — before asking what equipment exists, ask what the
              equipment would have to achieve. The station is the concept's
              own bottleneck, so this follows the verified plan rather than
              a hard-coded id. */}
          <div className="concept-verified__next">
            <SensitivityPanel draft={draft} stageId={selectedStationId} stageName={selectedStationName} />
          </div>

          {/* Phase 16 — the next engineering step, now real. */}
          <div className="concept-verified__next">
            <EquipmentDiscovery
              draft={draft}
              stationId={selectedStationId}
              onStationChange={setStationOverride}
              strategyContext={selected.title}
              storedSelections={equipment}
              onSelected={(chosen, bounds) =>
                setEquipmentSelection(chosen.selection.station_id, {
                  manufacturer: chosen.selection.manufacturer,
                  model: chosen.selection.model,
                  source_url: chosen.selection.source_url ?? null,
                  // Recorded so a reload can CHECK this choice rather than
                  // trust it: the bounds it was judged against travel with
                  // it, and a station since narrowed will say so.
                  candidate_id: chosen.selection.candidate_id,
                  station_id: chosen.selection.station_id,
                  selected_at: new Date().toISOString(),
                  bounds,
                })
              }
              onRequirementsComputed={() => recordArtifact("EQUIPMENT_REQUIREMENTS")}
            />
          </div>
        </div>
      )}
    </section>
  );
}

/** The three outcomes, kept distinct on purpose. */
/** The four verdicts, each on its own line. */
function VerificationTiers({ tiers }: { tiers: VerificationTier[] }) {
  if (!tiers || tiers.length === 0) return null;
  return (
    <dl className="handoff-tiers" data-testid="handoff-tiers">
      {tiers.map((tier) => (
        <div key={tier.tier} className="handoff-tier" data-testid={`handoff-tier-${tier.tier}`}>
          <dt className="handoff-tier__name">{TIER_LABEL[tier.tier] ?? tier.tier}</dt>
          <dd>
            <span
              className={`handoff-tier__status handoff-tier__status--${tier.status.toLowerCase()}`}
              data-status={tier.status}
            >
              {tier.status === "NOT_RUN" ? "NOT RUN" : tier.status}
            </span>
            <span className="handoff-tier__detail">{tier.detail}</span>
          </dd>
        </div>
      ))}
    </dl>
  );
}

const TIER_LABEL: Record<string, string> = {
  STRUCTURE: "Structure",
  LAYOUT: "Layout",
  FLOW: "Flow",
  RUNTIME: "Runtime smoke test",
};

/** What this file contains, and what it does not. */
function ExportScope({ result }: { result: PlantSimulationHandoffResult }) {
  return (
    <div className="handoff-scope" data-testid="handoff-scope">
      <p className="handoff-scope__title">
        Exporting: <strong data-testid="handoff-scope-label">{result.export_scope_label}</strong>
      </p>
      {result.export_excludes.length > 0 && (
        <>
          <p className="handoff-scope__subtitle">Not in this file</p>
          <ul data-testid="handoff-scope-excludes">
            {result.export_excludes.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </>
      )}
      {result.manifest_path && (
        <p className="handoff-scope__manifest" data-testid="handoff-manifest">
          An engineering manifest listing every station, its transferred values and these
          limitations was written beside the model: {result.manifest_path}
        </p>
      )}
    </div>
  );
}

function HandoffOutcome({
  result,
  selectedEquipmentCount,
}: {
  result: PlantSimulationHandoffResult;
  /** How many stations have equipment under consideration in THIS project. */
  selectedEquipmentCount: number;
}) {
  if (result.status === "UNAVAILABLE") {
    return (
      <div className="concept-verified__result-warn" data-testid="handoff-unavailable">
        <p className="concept-verified__result-title">
          <CircleAlert size={14} strokeWidth={2.2} aria-hidden="true" />
          Plant Simulation not reachable
        </p>
        <p className="concept-verified__result-line">
          No Plant Simulation installation answered on this machine, so no model was created. The
          concept itself is unaffected.
        </p>
        {result.errors.map((error) => (
          <p key={error} className="concept-verified__result-line">
            {error}
          </p>
        ))}
      </div>
    );
  }

  if (result.status === "INCOMPLETE") {
    return (
      <div className="concept-verified__result-fail" data-testid="handoff-incomplete">
        <p className="concept-verified__result-title">
          <XCircle size={14} strokeWidth={2.2} aria-hidden="true" />
          Handoff not yet complete
        </p>
        <p className="concept-verified__result-line">
          The model was not verified as matching the concept, so it must not be treated as an
          engineering handoff.
        </p>
        <VerificationTiers tiers={result.verification} />
        <dl className="concept-verified__counts">
          <Count label="Stations verified" verified={result.stations_verified} total={result.stations_created} />
          <Count label="Cycle times verified" verified={result.cycle_times_verified} total={result.stations_created} />
          <Count
            label="Flow connections verified"
            verified={result.connections_verified}
            total={result.connections_created}
          />
          <Count
            label="Positions verified"
            verified={result.positions_verified}
            total={result.positions_checked}
          />
        </dl>
        <GeometryEvidence result={result} />
        {result.errors.map((error) => (
          <p key={error} className="concept-verified__result-line" data-testid="handoff-error">
            {error}
          </p>
        ))}
      </div>
    );
  }

  return (
    <div className="concept-verified__result-ok" data-testid="handoff-complete">
      <p className="concept-verified__result-title">
        <CheckCircle2 size={14} strokeWidth={2.2} aria-hidden="true" />
        {/* "verified" alone reads as Plant Simulation endorsing the model. */}
        {result.traversal_verified
          ? "Model transferred: laid out, connected end to end, and traversed in Plant Simulation"
          : "Model transferred: laid out, connected end to end, and read back"}
      </p>
      <VerificationTiers tiers={result.verification} />
      <dl className="concept-verified__counts">
        <Count label="Stations verified" verified={result.stations_verified} total={result.stations_created} />
        <Count label="Cycle times verified" verified={result.cycle_times_verified} total={result.stations_created} />
        <Count
          label="Flow connections verified"
          verified={result.connections_verified}
          total={result.connections_created}
        />
        <Count
          label="Positions verified"
          verified={result.positions_verified}
          total={result.positions_checked}
        />
      </dl>
      <GeometryEvidence result={result} />
      {result.equipment_transferred > 0 ? (
        <p className="concept-verified__result-line" data-testid="handoff-equipment">
          Equipment under consideration carried into the model as metadata on{" "}
          {result.equipment_verified} of {result.equipment_transferred} station
          {result.equipment_transferred === 1 ? "" : "s"}. The verified cycle times, capacities and
          operator counts are unchanged — no manufacturer figure was written into them.
        </p>
      ) : (
        selectedEquipmentCount > 0 && (
          // Silence here would be read as "it went across". What crossed is
          // the station's requirement; the machine an engineer is considering
          // did not, and the recipient must not open the .spp believing a
          // manufacturer was specified in it.
          <p className="concept-verified__result-line" data-testid="handoff-equipment-absent">
            {selectedEquipmentCount} station
            {selectedEquipmentCount === 1 ? " has" : "s have"} equipment under consideration, and
            none of it reached this model. What was exported is the station requirement — the
            candidate machines are recorded in this project only.
          </p>
        )
      )}
      <SavedFile result={result} />
      <ExportScope result={result} />
      <ViewFramingNote />
      {result.warnings.map((warning) => (
        <p key={warning} className="concept-verified__result-line" data-testid="handoff-warning">
          {warning}
        </p>
      ))}
    </div>
  );
}

/** §22 — WHAT THE AUTOMATION CANNOT DO, SAID PLAINLY. */
function ViewFramingNote() {
  return (
    <p className="handoff-view-note" data-testid="handoff-view-note">
      Plant Simulation may open the model at its default camera framing. Use{" "}
      <code>View → Show All</code> (<code>Ansicht → Alles zeigen</code>) to fit the whole model —
      its remote-control interface offers no command for this, so it cannot be done for you.
    </p>
  );
}

/** GEOMETRY AND ROUTE — the evidence the old panel had no way to show. */
function GeometryEvidence({ result }: { result: PlantSimulationHandoffResult }) {
  return (
    <div data-testid="handoff-geometry">
      {result.layout_min_separation !== null && (
        <p className="concept-verified__result-line" data-testid="handoff-spacing">
          {result.overlaps.length === 0
            ? `No two objects overlap — the closest pair sits ${result.layout_min_separation} frame units apart, against a 41-unit object.`
            : `${result.overlaps.length} pair(s) of objects overlap: ${result.overlaps[0]}.`}
        </p>
      )}
      {result.route_complete !== null && (
        <p className="concept-verified__result-line" data-testid="handoff-route">
          {result.route_complete
            ? `Material flow walked end to end: ${result.route_walked.join(" → ")}.`
            : `The route does not run from Source to Drain. ${
                result.disconnected.length
                  ? `Off the route: ${result.disconnected.join(", ")}.`
                  : ""
              }`}
        </p>
      )}
      {result.traversal_verified !== null && (
        <p className="concept-verified__result-line" data-testid="handoff-traversal">
          {result.traversal_verified
            ? `Plant Simulation ran the model: ${result.traversal_units} unit(s) reached the drain, so material genuinely travels the route.`
            : "Plant Simulation ran the model and no unit reached the drain."}
        </p>
      )}
      {result.layout_mode === "generated-line" && (
        <p className="concept-verified__result-line" data-testid="handoff-layout-mode">
          Arrangement: a generated engineering line, not the concept layout as drawn.
        </p>
      )}
    </div>
  );
}

/** What happened to the FILE, stated as evidence rather than as the word "saved". */
function SavedFile({ result }: { result: PlantSimulationHandoffResult }) {
  if (!result.model_path) {
    return (
      <p className="concept-verified__result-line" data-testid="handoff-no-file">
        The model was built in Plant Simulation but no file was written, so
        there is nothing to open later.
      </p>
    );
  }

  const megabytes = result.model_bytes ? (result.model_bytes / 1_000_000).toFixed(1) : null;

  return (
    <>
      <p className="concept-verified__result-line" data-testid="handoff-model-path">
        Saved to <code>{result.model_path}</code>
        {megabytes ? ` (${megabytes} MB on disk)` : ""}
      </p>
      {result.saved_model_verified === true && (
        <p className="concept-verified__result-line" data-testid="handoff-roundtrip">
          The saved file was re-opened and read back: {result.saved_stations_verified} stations
          and {result.saved_connections_verified} connections found in the file itself.
        </p>
      )}
      <p className="concept-verified__result-line" data-testid="handoff-version">
        {result.product_version
          ? `Written by ${result.product_version}. Opening it needs that release or newer.`
          : "The Plant Simulation release that wrote this file could not be determined, so which releases can open it is unknown."}
      </p>
    </>
  );
}

function Count({ label, verified, total }: { label: string; verified: number; total: number }) {
  return (
    <div>
      <dt className="fm-label">{label}</dt>
      <dd>
        {verified} of {total}
      </dd>
    </div>
  );
}
