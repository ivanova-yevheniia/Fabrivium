import { describe, expect, it } from "vitest";
import type { SimulationTrace } from "../api/types";
import { appReducer } from "./appReducer";
import { initialAppState, initialPlaybackState } from "./types";

const trace: SimulationTrace = {
  trace_version: 1,
  horizon_seconds: 100,
  sampled_interval_seconds: 10,
  config: { max_tracked_units: 40, sample_count_target: 10 },
  events: [],
  machine_series: [],
  buffer_series: [],
  operator_series: [],
  system_series: [{ timestamp: 100, completed_units: 5, released_units: 5, current_bottleneck_machine_id: "m-1" }],
  story_markers: [{ timestamp: 50, marker_type: "QUEUE_GROWING", entity_id: "m-1", title: "x", evidence_ref: "y" }],
  tracked_unit_count: 5,
  total_unit_count: 5,
  summary: {
    simulation_time_seconds: 100,
    target_units: 5,
    completed_units: 5,
    throughput_per_hour: 1,
    demand_per_day: 5,
    demand_met: true,
    demand_gap_units: 0,
    machine_kpis: [],
    system: { average_flow_time_seconds: 0, max_flow_time_seconds: 0, work_in_progress: 0, bottleneck_machine_id: "m-1" },
    process_pool_kpis: [],
  },
  metadata: {},
};

describe("appReducer — Phase 8C playback actions", () => {
  it("PLAYBACK_OPEN_START marks active/loading for the requested stage", () => {
    const state = appReducer(initialAppState, { type: "PLAYBACK_OPEN_START", stageKey: "final" });
    expect(state.playback.active).toBe(true);
    expect(state.playback.loading).toBe(true);
    expect(state.playback.stageKey).toBe("final");
  });

  it("PLAYBACK_OPEN_SUCCESS stores the trace and resets simTime/playing", () => {
    let state = appReducer(initialAppState, { type: "PLAYBACK_OPEN_START", stageKey: "final" });
    state = appReducer(state, { type: "PLAYBACK_OPEN_SUCCESS", stageKey: "final", trace });
    expect(state.playback.trace).toBe(trace);
    expect(state.playback.loading).toBe(false);
    expect(state.playback.simTime).toBe(0);
    expect(state.playback.playing).toBe(false);
  });

  it("PLAYBACK_OPEN_SUCCESS for a STALE stage (user reopened for a different one) is ignored", () => {
    let state = appReducer(initialAppState, { type: "PLAYBACK_OPEN_START", stageKey: "final" });
    // User already moved on to "baseline" before the "final" request resolved.
    state = appReducer(state, { type: "PLAYBACK_OPEN_START", stageKey: "baseline" });
    const before = state;
    state = appReducer(state, { type: "PLAYBACK_OPEN_SUCCESS", stageKey: "final", trace });
    expect(state).toBe(before); // untouched — the late "final" response never overwrites "baseline"
  });

  it("PLAYBACK_PLAY restarts from 0 when already at the end", () => {
    let state = appReducer(initialAppState, { type: "PLAYBACK_OPEN_START", stageKey: "final" });
    state = appReducer(state, { type: "PLAYBACK_OPEN_SUCCESS", stageKey: "final", trace });
    state = appReducer(state, { type: "PLAYBACK_SEEK", simTime: 100 });
    state = appReducer(state, { type: "PLAYBACK_PLAY" });
    expect(state.playback.simTime).toBe(0);
    expect(state.playback.playing).toBe(true);
  });

  it("PLAYBACK_SEEK clamps to [0, horizon] and auto-pauses at the end", () => {
    let state = appReducer(initialAppState, { type: "PLAYBACK_OPEN_START", stageKey: "final" });
    state = appReducer(state, { type: "PLAYBACK_OPEN_SUCCESS", stageKey: "final", trace });
    state = appReducer(state, { type: "PLAYBACK_PLAY" });
    state = appReducer(state, { type: "PLAYBACK_SEEK", simTime: 999 });
    expect(state.playback.simTime).toBe(100);
    expect(state.playback.playing).toBe(false);

    state = appReducer(state, { type: "PLAYBACK_SEEK", simTime: -50 });
    expect(state.playback.simTime).toBe(0);
  });

  it("PLAYBACK_SEEK to the same instant twice is idempotent (deterministic seek)", () => {
    let state = appReducer(initialAppState, { type: "PLAYBACK_OPEN_START", stageKey: "final" });
    state = appReducer(state, { type: "PLAYBACK_OPEN_SUCCESS", stageKey: "final", trace });
    const a = appReducer(state, { type: "PLAYBACK_SEEK", simTime: 42 });
    const b = appReducer(state, { type: "PLAYBACK_SEEK", simTime: 42 });
    expect(a.playback.simTime).toBe(b.playback.simTime);
  });

  it("PLAYBACK_RESET zeroes simTime and pauses", () => {
    let state = appReducer(initialAppState, { type: "PLAYBACK_OPEN_START", stageKey: "final" });
    state = appReducer(state, { type: "PLAYBACK_OPEN_SUCCESS", stageKey: "final", trace });
    state = appReducer(state, { type: "PLAYBACK_PLAY" });
    state = appReducer(state, { type: "PLAYBACK_SEEK", simTime: 60 });
    state = appReducer(state, { type: "PLAYBACK_RESET" });
    expect(state.playback.simTime).toBe(0);
    expect(state.playback.playing).toBe(false);
  });

  it("PLAYBACK_SET_SPEED changes only speed, never simTime/playing", () => {
    let state = appReducer(initialAppState, { type: "PLAYBACK_OPEN_START", stageKey: "final" });
    state = appReducer(state, { type: "PLAYBACK_OPEN_SUCCESS", stageKey: "final", trace });
    state = appReducer(state, { type: "PLAYBACK_SEEK", simTime: 30 });
    state = appReducer(state, { type: "PLAYBACK_SET_SPEED", speed: 20 });
    expect(state.playback.speed).toBe(20);
    expect(state.playback.simTime).toBe(30);
  });

  it("PLAYBACK_CLOSE fully resets playback state", () => {
    let state = appReducer(initialAppState, { type: "PLAYBACK_OPEN_START", stageKey: "final" });
    state = appReducer(state, { type: "PLAYBACK_OPEN_SUCCESS", stageKey: "final", trace });
    state = appReducer(state, { type: "PLAYBACK_CLOSE" });
    expect(state.playback).toEqual(initialPlaybackState);
  });

  it("REQUEST_CAMERA_FOCUS / CLEAR_CAMERA_FOCUS_REQUEST round-trip", () => {
    let state = appReducer(initialAppState, { type: "REQUEST_CAMERA_FOCUS", target: "bottleneck" });
    expect(state.cameraFocusRequest).toBe("bottleneck");
    state = appReducer(state, { type: "CLEAR_CAMERA_FOCUS_REQUEST" });
    expect(state.cameraFocusRequest).toBeNull();
  });

  it("RESET_SESSION clears playback and camera state along with everything else", () => {
    let state = appReducer(initialAppState, { type: "PLAYBACK_OPEN_START", stageKey: "final" });
    state = appReducer(state, { type: "PLAYBACK_OPEN_SUCCESS", stageKey: "final", trace });
    state = appReducer(state, { type: "REQUEST_CAMERA_FOCUS", target: "overview" });
    state = appReducer(state, { type: "RESET_SESSION" });
    expect(state.playback).toEqual(initialPlaybackState);
    expect(state.cameraFocusRequest).toBeNull();
  });
});
