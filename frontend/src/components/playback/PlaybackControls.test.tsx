import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SimulationTrace } from "../../api/types";
import { initialPlaybackState } from "../../state/types";
import { renderWithContext } from "../../test/testUtils";
import { PlaybackControls } from "./PlaybackControls";

const trace: SimulationTrace = {
  trace_version: 1,
  horizon_seconds: 3600,
  sampled_interval_seconds: 60,
  config: { max_tracked_units: 10, sample_count_target: 4 },
  events: [],
  machine_series: [],
  buffer_series: [],
  operator_series: [],
  system_series: [{ timestamp: 0, completed_units: 0, released_units: 0, current_bottleneck_machine_id: null }],
  story_markers: [
    { timestamp: 1800, marker_type: "BUFFER_FULL", entity_id: "b-1", title: "Buffer 1 reaches capacity", evidence_ref: "x" },
  ],
  tracked_unit_count: 0,
  total_unit_count: 0,
  summary: {
    simulation_time_seconds: 3600,
    target_units: 1,
    completed_units: 0,
    throughput_per_hour: 0,
    demand_per_day: 1,
    demand_met: false,
    demand_gap_units: 1,
    machine_kpis: [],
    system: { average_flow_time_seconds: 0, max_flow_time_seconds: 0, work_in_progress: 0, bottleneck_machine_id: "m-a" },
    process_pool_kpis: [],
  },
  metadata: {},
};

describe("PlaybackControls", () => {
  it("renders nothing when playback is not active", () => {
    const { container } = renderWithContext(<PlaybackControls />, { playback: initialPlaybackState });
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a loading message while the trace is being fetched", () => {
    renderWithContext(<PlaybackControls />, {
      playback: { ...initialPlaybackState, active: true, loading: true, stageKey: "final" },
    });
    expect(screen.getByTestId("playback-controls")).toHaveTextContent(/preparing the simulation playback/i);
  });

  it("renders the control bar with a formatted simulated clock once a trace is loaded", () => {
    renderWithContext(<PlaybackControls />, {
      playback: { ...initialPlaybackState, active: true, stageKey: "final", trace, simTime: 1800 },
    });
    expect(screen.getByTestId("playback-clock")).toHaveTextContent("00:30 / 01:00 simulated hours");
  });

  it("play/pause button toggles the playing action based on current state", () => {
    const pausePlayback = vi.fn();
    renderWithContext(
      <PlaybackControls />,
      { playback: { ...initialPlaybackState, active: true, stageKey: "final", trace, playing: true } },
      { pausePlayback },
    );
    fireEvent.click(screen.getByTestId("playback-play-pause"));
    expect(pausePlayback).toHaveBeenCalledTimes(1);
  });

  it("reset/speed/seek/close controls dispatch the corresponding actions", () => {
    const resetPlayback = vi.fn();
    const setPlaybackSpeed = vi.fn();
    const seekPlayback = vi.fn();
    const closePlayback = vi.fn();
    renderWithContext(
      <PlaybackControls />,
      { playback: { ...initialPlaybackState, active: true, stageKey: "final", trace } },
      { resetPlayback, setPlaybackSpeed, seekPlayback, closePlayback },
    );

    fireEvent.click(screen.getByTestId("playback-reset"));
    expect(resetPlayback).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("playback-speed-5"));
    expect(setPlaybackSpeed).toHaveBeenCalledWith(5);

    fireEvent.change(screen.getByTestId("playback-scrubber"), { target: { value: "900" } });
    expect(seekPlayback).toHaveBeenCalledWith(900);

    fireEvent.click(screen.getByLabelText("Close playback"));
    expect(closePlayback).toHaveBeenCalledTimes(1);
  });

  it("clicking a story marker seeks to its exact timestamp", () => {
    const seekPlayback = vi.fn();
    renderWithContext(
      <PlaybackControls />,
      { playback: { ...initialPlaybackState, active: true, stageKey: "final", trace } },
      { seekPlayback },
    );
    fireEvent.click(screen.getByTestId("playback-marker-BUFFER_FULL"));
    expect(seekPlayback).toHaveBeenCalledWith(1800);
  });

  it("shows a Before/After toggle only when a strategy is selected, and it seeks via viewStagePlayback", () => {
    const viewStagePlayback = vi.fn();
    renderWithContext(
      <PlaybackControls />,
      {
        playback: { ...initialPlaybackState, active: true, stageKey: "final", trace },
        selectedStrategyId: "strategy-e",
      },
      { viewStagePlayback },
    );
    expect(screen.getByTestId("playback-before-after")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("playback-view-before"));
    expect(viewStagePlayback).toHaveBeenCalledWith("baseline");
  });

  it("omits the Before/After toggle when no strategy is selected", () => {
    renderWithContext(<PlaybackControls />, {
      playback: { ...initialPlaybackState, active: true, stageKey: "final", trace },
      selectedStrategyId: null,
    });
    expect(screen.queryByTestId("playback-before-after")).not.toBeInTheDocument();
  });
});
