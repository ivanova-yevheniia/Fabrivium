import { useAppContext } from "../../state/AppContext";
import type { PlaybackSpeed } from "../../state/types";
import { formatNumber } from "../../utils/formatting";
import { activeScenario, scenarioWords } from "../../utils/scenario";
import { usePlaybackClock } from "./usePlaybackClock";

const SPEEDS: PlaybackSpeed[] = [1, 5, 20];

function formatSimClock(seconds: number): string {
  const totalMinutes = Math.floor(seconds / 60);
  const hh = Math.floor(totalMinutes / 60);
  const mm = totalMinutes % 60;
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}

const MARKER_COLOR: Record<string, string> = {
  QUEUE_GROWING: "#e0a83a",
  BUFFER_FULL: "#e0563f",
  MACHINE_BLOCKED: "#e0563f",
  OPERATOR_CONSTRAINED: "#e0a83a",
  TARGET_ACHIEVED: "#35c37a",
  TARGET_MISSED: "#e0563f",
};

/**
 * Phase 8C — playback control bar: [Reset] [Play/Pause] [1x|5x|20x]
 * [scrubber with story markers] [simulated time]. Renders nothing until
 * `openPlayback()` has produced a trace (loading/error states are shown by
 * the small header instead of a broken control bar).
 *
 * Every value shown/consumed here comes straight from `SimulationTrace` —
 * scrubbing calls `seekPlayback`, which is a pure `stateAt(simTime)`
 * lookup wherever it is READ (2D/3D/HUDs); this component itself only
 * ever moves the playhead, never computes a KPI.
 *
 * ---------------------------------------------------------------------
 * WHICH RUN AM I WATCHING?
 *
 * The header used to read "Simulation playback — Final". Switching plan
 * between A, B, C and D reloaded the trace and the header did not change a
 * character, so an audience watching a line that suddenly kept up had no way
 * to tell whether they were seeing Plan A's extra shift or Plan D's extra
 * machine — or the unchanged concept. Worse, "Final" and "Baseline" are the
 * timeline's internal stage names; neither says which PLAN the stage belongs
 * to, and "Final" is not a thing a manufacturing engineer would call
 * anything.
 *
 * So the header now states the four things that fix a run: whose plan it is,
 * which state of it is playing, over what operating horizon, and what came
 * out against the target. All four are read from state that already exists —
 * the trace's own horizon, the arena's verified metrics for the stage on
 * screen — and none of them is computed here.
 *
 * The horizon is the TRACE's `horizon_seconds`, not the factory's shift
 * arithmetic. A plan that adds a shift is watched over a longer day than the
 * baseline, and that difference is a large part of why its output is higher;
 * stating a horizon derived anywhere else would be able to disagree with the
 * animation it labels.
 */
export function PlaybackControls() {
  usePlaybackClock();
  const { state, playPlayback, pausePlayback, resetPlayback, setPlaybackSpeed, seekPlayback, closePlayback, viewStagePlayback } =
    useAppContext();
  const { playback } = state;

  if (!playback.active) return null;

  if (playback.loading || !playback.trace) {
    return (
      <section className="bottom-panel fm-panel" data-testid="playback-controls">
        <div className="playback-controls__header">
          <p className="fm-section__title">Simulation playback</p>
          <button type="button" className="comparison-card__close" onClick={closePlayback} aria-label="Close playback">
            ×
          </button>
        </div>
        {playback.loading && <p className="fm-empty">Preparing the simulation playback…</p>}
        {playback.error && <p className="factory-workspace__notice">{playback.error.message}</p>}
      </section>
    );
  }

  const trace = playback.trace;
  const horizon = trace.horizon_seconds;
  const words = scenarioWords(state);

  const arena = state.arena;
  const selected = arena?.strategies.find((s) => s.strategy_id === state.selectedStrategyId) ?? null;
  const canToggleBaseline = Boolean(state.selectedStrategyId);
  const onBaseline = playback.stageKey === "baseline";

  // Which verified run this playback belongs to. `baseline` is always the
  // arena's own baseline metrics; anything else is the selected plan's. An
  // intermediate iteration (reachable only from the Engineering timeline)
  // has no arena-level metrics, so it gets the stage name and no figures
  // rather than the wrong plan's figures.
  //
  // The baseline/selected-plan decision comes from `activeScenario`, the
  // same helper the "Simulated factory — …" heading above the visualization
  // reads. That heading used to answer this question for itself, from
  // `selectedStrategyId`, and during baseline playback the two disagreed on
  // screen at the same time. One derivation now, so they cannot.
  //
  // The intermediate-stage names below are this panel's alone: they are
  // reachable only from the Engineering timeline and have no arena-level
  // identity for a heading to borrow.
  const scenario = activeScenario(state);
  const metrics = onBaseline || selected ? scenario.metrics : null;
  const scenarioName =
    onBaseline || selected
      ? scenario.name
      : playback.stageKey === "final"
        ? "Final plan"
        : `Iteration ${Number(playback.stageKey) + 1}`;
  const stateName = onBaseline ? words.baselineQualifier : selected ? "Selected plan" : "Planning stage";

  const horizonHours = Math.round(horizon / 3600);

  return (
    <section className="bottom-panel fm-panel" data-testid="playback-controls">
      <div className="playback-controls__header">
        <div className="playback-context" data-testid="playback-context">
          <p className="fm-section__title" data-testid="playback-scenario">
            Simulation playback — {scenarioName}
          </p>
          <p className="playback-context__line">
            <span data-testid="playback-state-name">{stateName}</span>
            <span className="playback-context__sep" aria-hidden="true">
              ·
            </span>
            <span className="fm-mono" data-testid="playback-horizon">
              {horizonHours} h operating horizon
            </span>
            {metrics && (
              <>
                <span className="playback-context__sep" aria-hidden="true">
                  ·
                </span>
                <span className="fm-mono" data-testid="playback-output">
                  Output {formatNumber(metrics.completed_units)}/day
                </span>
                <span className="playback-context__sep" aria-hidden="true">
                  ·
                </span>
                <span className="fm-mono" data-testid="playback-target">
                  Target {formatNumber(metrics.target_units)}/day
                </span>
                <span
                  className={`playback-context__verdict playback-context__verdict--${metrics.goal_met ? "met" : "short"}`}
                  data-testid="playback-verdict"
                >
                  {metrics.goal_met
                    ? "Target met"
                    : `Gap ${formatNumber(metrics.demand_gap_units)}/day`}
                </span>
              </>
            )}
          </p>
        </div>
        {canToggleBaseline && (
          <div className="playback-controls__before-after" data-testid="playback-before-after">
            <button
              type="button"
              className={`fm-badge ${onBaseline ? "fm-badge--verified" : "fm-badge--unknown"}`}
              onClick={() => void viewStagePlayback("baseline")}
              aria-pressed={onBaseline}
              data-testid="playback-view-before"
            >
              {words.baselineShort}
            </button>
            <button
              type="button"
              className={`fm-badge ${playback.stageKey === "final" ? "fm-badge--verified" : "fm-badge--unknown"}`}
              onClick={() => void viewStagePlayback("final")}
              aria-pressed={playback.stageKey === "final"}
              data-testid="playback-view-after"
            >
              {selected ? selected.label : "Selected plan"}
            </button>
          </div>
        )}
        <button type="button" className="comparison-card__close" onClick={closePlayback} aria-label="Close playback">
          ×
        </button>
      </div>

      <div className="playback-controls__bar">
        <button type="button" onClick={resetPlayback} data-testid="playback-reset" title="Reset">
          ⏮
        </button>
        <button
          type="button"
          onClick={() => (playback.playing ? pausePlayback() : playPlayback())}
          data-testid="playback-play-pause"
          title={playback.playing ? "Pause" : "Play"}
        >
          {playback.playing ? "⏸" : "▶"}
        </button>

        <div className="playback-controls__speeds" role="group" aria-label="Playback speed">
          {SPEEDS.map((speed) => (
            <button
              key={speed}
              type="button"
              className={playback.speed === speed ? "playback-controls__speed--active" : ""}
              onClick={() => setPlaybackSpeed(speed)}
              data-testid={`playback-speed-${speed}`}
              aria-pressed={playback.speed === speed}
            >
              {speed}×
            </button>
          ))}
        </div>

        <div className="playback-controls__scrubber-wrap">
          <input
            type="range"
            min={0}
            max={horizon}
            step={Math.max(1, horizon / 1000)}
            value={playback.simTime}
            onChange={(e) => seekPlayback(Number(e.target.value))}
            data-testid="playback-scrubber"
            aria-label="Playback position"
          />
          <div className="playback-controls__markers" data-testid="playback-story-markers">
            {trace.story_markers.map((marker) => (
              <button
                key={`${marker.marker_type}-${marker.timestamp}-${marker.entity_id}`}
                type="button"
                className="playback-controls__marker"
                style={{ left: `${(marker.timestamp / horizon) * 100}%`, ["--marker-color" as string]: MARKER_COLOR[marker.marker_type] ?? "#4fb3ff" }}
                onClick={() => seekPlayback(marker.timestamp)}
                title={marker.title}
                data-testid={`playback-marker-${marker.marker_type}`}
              />
            ))}
          </div>
        </div>

        <span className="fm-mono playback-controls__clock" data-testid="playback-clock">
          {formatSimClock(playback.simTime)} / {formatSimClock(horizon)} simulated hours
        </span>
      </div>
    </section>
  );
}
