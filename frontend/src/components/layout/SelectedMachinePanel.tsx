import { useAppContext } from "../../state/AppContext";
import { formatCurrency, formatNumber, formatPercent } from "../../utils/formatting";
import { getPlacement } from "../../utils/layoutDraft";
import { effectiveStageLayout, resolveStage } from "../../utils/stage";

function Row({ label, value, mono = true }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="inspector__row">
      <span className="inspector__row-label">{label}</span>
      <span className={`inspector__row-value${mono ? " fm-mono" : ""}`}>{value}</span>
    </div>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="inspector__group">
      <h3 className="fm-label inspector__group-title">{title}</h3>
      <div className="inspector__rows">{children}</div>
    </section>
  );
}

/** Selected-machine detail panel (Phase 6B section 3). */
export function SelectedMachinePanel() {
  const { state, currentStageFactory } = useAppContext();
  if (!state.selectedMachineId) {
    return (
      <div className="fm-section inspector inspector--empty" data-testid="selected-machine-empty">
        <p className="fm-label">Machine inspector</p>
        <p className="fm-empty">Select a station in the twin to inspect it.</p>
      </div>
    );
  }

  const factory = currentStageFactory();
  const machine = factory?.machines.find((m) => m.id === state.selectedMachineId);
  if (!machine) return null;

  // Phase 12.1 — the SAME resolver the workspace draws from. Reading
  // `snapshot.layout` directly here meant the inspector reported the
  // verified snapshot's coordinates while the twin drew the applied ones,
  // so an applied edit looked reverted in the panel even though the plan on
  // screen had moved. One reader, one answer.
  const layout = state.draftLayout ?? effectiveStageLayout(state, state.selectedIteration);
  const placement = layout ? getPlacement(layout, machine.id) : null;

  const simulation = state.session
    ? resolveStage(state.session, state.selectedIteration)?.snapshot.simulation
    : undefined;
  const kpi = simulation?.machine_kpis.find((k) => k.machine_id === machine.id) ?? null;

  return (
    <div className="fm-section inspector" data-testid="selected-machine-panel">
      <header className="inspector__head">
        <p className="inspector__name">{machine.name}</p>
        <p className="inspector__id fm-mono">{machine.id}</p>
      </header>

      <Group title="Identity">
        <Row label="Process type" value={machine.process_type} />
        <Row label="Lifecycle" value={machine.lifecycle_status} />
        <Row label="3D asset" value={machine.asset?.asset_type ?? "MISSING"} />
      </Group>

      <Group title="Process">
        <Row label="Cycle time" value={`${formatNumber(machine.cycle_time)} s`} />
        <Row label="Capacity" value={formatNumber(machine.capacity)} />
      </Group>

      <Group title="Economics">
        <Row label="Purchase cost" value={formatCurrency(machine.purchase_cost)} />
      </Group>

      <Group title="Layout">
        <Row label="Footprint" value={`${formatNumber(machine.width)} × ${formatNumber(machine.length)} m`} />
        <Row
          label="Height"
          value={
            machine.physical_envelope?.height != null
              ? `${formatNumber(machine.physical_envelope.height)} m`
              : "unknown"
          }
        />
        <Row
          label="Position"
          value={placement ? `${formatNumber(placement.x)}, ${formatNumber(placement.y)}` : "unplaced"}
        />
        <Row label="Rotation" value={placement ? `${formatNumber(placement.rotation_deg)}°` : "—"} />
      </Group>

      {kpi ? (
        <Group title={`Simulation — ${machine.name}`}>
          <Row label="Processed units" value={formatNumber(kpi.processed_units)} />
          <Row label="Utilization" value={formatPercent(kpi.utilization)} />
          <Row label="Avg queue length" value={formatNumber(kpi.average_queue_length)} />
          <Row label="Avg wait time" value={`${formatNumber(kpi.average_wait_time_seconds)} s`} />
        </Group>
      ) : (
        <p className="fm-empty" data-testid="selected-machine-no-kpi">
          No simulation KPI available for this machine at this stage.
        </p>
      )}
    </div>
  );
}
