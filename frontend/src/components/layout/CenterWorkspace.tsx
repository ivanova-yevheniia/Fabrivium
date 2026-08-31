import { useMemo } from "react";
import { useAppContext } from "../../state/AppContext";
import { OperatorHud } from "../playback/OperatorHud";
import { PlaybackOverlay2D } from "../playback/PlaybackOverlay2D";
import { isAlarmBottleneck, limitingStageLabel } from "../../utils/limitingStage";
import { effectiveStageLayout, resolveStage } from "../../utils/stage";
import { TraceIndex } from "../../utils/traceIndex";
import { FactoryWorkspace } from "../workspace/FactoryWorkspace";
import { FactoryWorkspace3D } from "../workspace/FactoryWorkspace3D";
import { LayoutToolbar } from "./LayoutToolbar";
import { ViewModeToggle } from "./ViewModeToggle";

/** Wires application state into the props-only <FactoryWorkspace />/
 * <FactoryWorkspace3D /> contracts, plus the Phase 6B editing toolbar and
 * Phase 6C 2D/3D toggle above the canvas. Keeping this wiring separate
 * from the workspace components themselves is what let Phase 6C add a
 * whole second renderer without touching state management, the shell, or
 * the 2D component at all — same pattern extends to future views. */
export function CenterWorkspace() {
  const { state, selectMachine, moveMachine, currentStageFactory, clearCameraFocusRequest } = useAppContext();
  const stage = state.session ? resolveStage(state.session, state.selectedIteration) : null;

  const editing = state.editMode === "EDIT_LAYOUT" && Boolean(state.draftLayout);
  // Editing is only ever offered against a draft — never a rejected
  // candidate's read-only evaluated geometry, and never a bare view when
  // no draft has been started (see enterEditMode).
  const isReadOnlyStage = Boolean(stage?.isRejectedCandidate);

  const factory = editing ? currentStageFactory() : stage ? stage.snapshot.factory : state.factory;
  // Phase 12.1 — one resolver for the geometry, shared by the 2D plan, the
  // 3D scene and the playback overlay below, so an APPLIED layout edit is
  // what every renderer draws. Reading `stage.snapshot.layout` here was the
  // reason Apply looked like it reverted: the committed geometry lives
  // beside the snapshot, not inside it (see effectiveStageLayout).
  const layout = editing ? state.draftLayout : effectiveStageLayout(state, state.selectedIteration);
  const violations = state.layoutValidation?.violations ?? [];

  // Phase 9A section 8 — only pass the machine id through as an ALARM
  // highlight (shared red styling with genuine constraint violations) when
  // it is a real bottleneck (demand not met). When demand IS met, the same
  // field is still real and worth naming, but never as a red "fault".
  const alarmBottleneckId =
    stage && isAlarmBottleneck(stage.snapshot.simulation) ? stage.snapshot.bottleneck_machine_id : null;

  // §3 — the alarm and the camera are different questions. The stage that
  // limits throughput exists whether or not the target was met, so the
  // camera can always go to it; only the red styling and the word
  // "bottleneck" are conditional.
  const limitingStageId = stage?.snapshot.bottleneck_machine_id ?? null;
  const limitingLabel = stage ? limitingStageLabel(stage.snapshot.simulation) : "Limiting stage";

  // Phase 8C — only meaningful when the loaded trace is for THIS exact
  // stage; a stale trace (user switched timeline stage without reopening
  // playback) is never silently rendered — see PlaybackState's doc comment.
  const playback = state.playback;
  const playbackReady =
    playback.active && playback.trace && playback.stageKey === state.selectedIteration && !editing;
  const traceIndex = useMemo(
    () => (playbackReady && playback.trace ? new TraceIndex(playback.trace) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [playback.trace],
  );

  return (
    <div className="center-workspace" data-testid="center-workspace">
      <div className="workspace-toolbar-row" data-testid="workspace-toolbar-row">
        <LayoutToolbar />
        <ViewModeToggle />
      </div>
      {state.viewMode === "2D" ? (
        <div className="factory-workspace-2d-wrap">
          <FactoryWorkspace
            factory={factory}
            layout={layout}
            selectedMachineId={state.selectedMachineId}
            highlightedMachineIds={stage?.actionMachineIds ?? []}
            isRejectedCandidate={isReadOnlyStage}
            bottleneckMachineId={alarmBottleneckId}
            onSelectMachine={selectMachine}
            editable={editing && !isReadOnlyStage}
            violations={violations}
            onMoveMachine={editing && !isReadOnlyStage ? moveMachine : undefined}
            presentation={state.viewLevel}
          />
          {playbackReady && traceIndex && factory && layout && (
            <div className="playback-overlay-2d-wrap">
              <PlaybackOverlay2D
                factory={factory}
                layout={layout}
                traceIndex={traceIndex}
                simTime={playback.simTime}
                productId={state.productId}
              />
              <div className="operator-hud-2d-wrap">
                <OperatorHud traceIndex={traceIndex} simTime={playback.simTime} />
              </div>
            </div>
          )}
        </div>
      ) : (
        <FactoryWorkspace3D
          factory={factory}
          layout={layout}
          selectedMachineId={state.selectedMachineId}
          highlightedMachineIds={stage?.actionMachineIds ?? []}
          isRejectedCandidate={isReadOnlyStage}
          bottleneckMachineId={alarmBottleneckId}
          limitingStageId={limitingStageId}
          limitingStageLabel={limitingLabel}
          onSelectMachine={selectMachine}
          violations={violations}
          traceIndex={playbackReady ? traceIndex : null}
          simTime={playback.simTime}
          cameraFocusRequest={state.cameraFocusRequest}
          onCameraFocusHandled={clearCameraFocusRequest}
          presentation={state.viewLevel}
          productId={state.productId}
          // Phase 12.1 — identical guard to the 2D canvas above: editing is
          // only ever offered against a draft, never against a rejected
          // candidate's read-only evaluated geometry.
          editable={editing && !isReadOnlyStage}
          onMoveMachine={editing && !isReadOnlyStage ? moveMachine : undefined}
        />
      )}
    </div>
  );
}
