import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { FactoryLayout, SimulationTrace } from "../../api/types";
import { sampleSessionTwoIterations } from "../../test/fixtures";
import { renderWithContext } from "../../test/testUtils";
import { initialPlaybackState } from "../../state/types";
import { CenterWorkspace } from "./CenterWorkspace";

// The shared fixtures deliberately carry `layout: null` (Phase 6A section
// 11's "no layout" fallback path is what they exercise); Phase 8C's overlay
// only ever renders alongside a REAL layout (buffers/machines need real
// coordinates), so these tests seed one directly.
const testLayout: FactoryLayout = {
  factory_width: 20,
  factory_length: 10,
  placements: [
    { machine_id: "m-a", x: 5, y: 5, z: 0, rotation_deg: 0 },
    { machine_id: "m-b", x: 12, y: 5, z: 0, rotation_deg: 0 },
  ],
  reserved_zones: [],
  aisle_zones: [],
};

const sessionWithLayout = {
  ...sampleSessionTwoIterations,
  baseline_snapshot: { ...sampleSessionTwoIterations.baseline_snapshot, layout: testLayout },
};

vi.mock("@react-three/fiber", () => ({
  Canvas: ({ children, "data-testid": testId }: { children: React.ReactNode; "data-testid"?: string }) => (
    <div data-testid={testId}>{children}</div>
  ),
}));
vi.mock("@react-three/drei", () => ({
  Html: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  useGLTF: () => ({ scene: { clone: () => ({ traverse: () => {} }) } }),
  OrbitControls: () => null,
  PerspectiveCamera: () => null,
  Grid: () => null,
}));

const minimalTrace: SimulationTrace = {
  trace_version: 1,
  horizon_seconds: 100,
  sampled_interval_seconds: 25,
  config: { max_tracked_units: 10, sample_count_target: 4 },
  events: [],
  machine_series: [],
  buffer_series: [],
  operator_series: [],
  system_series: [{ timestamp: 0, completed_units: 0, released_units: 0, current_bottleneck_machine_id: null }],
  story_markers: [],
  tracked_unit_count: 0,
  total_unit_count: 0,
  summary: {
    simulation_time_seconds: 100,
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

describe("CenterWorkspace — Phase 8C playback / stage synchronization", () => {
  it("renders the playback overlay when the loaded trace matches the currently selected stage", () => {
    renderWithContext(<CenterWorkspace />, {
      session: sessionWithLayout,
      selectedIteration: "baseline",
      playback: { ...initialPlaybackState, active: true, stageKey: "baseline", trace: minimalTrace },
    });
    expect(screen.getByTestId("playback-overlay-2d")).toBeInTheDocument();
  });

  it("does NOT render the playback overlay when the loaded trace is for a DIFFERENT stage than currently selected — the exact desync bug class Phase 8C guards against", () => {
    renderWithContext(<CenterWorkspace />, {
      session: sessionWithLayout,
      selectedIteration: "final",
      // The trace was opened for "baseline"; the user has since moved the
      // timeline to "final" WITHOUT reopening playback.
      playback: { ...initialPlaybackState, active: true, stageKey: "baseline", trace: minimalTrace },
    });
    expect(screen.queryByTestId("playback-overlay-2d")).not.toBeInTheDocument();
  });

  it("does not render the overlay while a layout edit draft is active, even if playback is otherwise ready", () => {
    renderWithContext(<CenterWorkspace />, {
      session: sessionWithLayout,
      selectedIteration: "baseline",
      editMode: "EDIT_LAYOUT",
      draftLayout: testLayout,
      playback: { ...initialPlaybackState, active: true, stageKey: "baseline", trace: minimalTrace },
    });
    expect(screen.queryByTestId("playback-overlay-2d")).not.toBeInTheDocument();
  });

  it("renders nothing playback-related when playback was never opened", () => {
    renderWithContext(<CenterWorkspace />, { session: sampleSessionTwoIterations, selectedIteration: "baseline" });
    expect(screen.queryByTestId("playback-overlay-2d")).not.toBeInTheDocument();
  });
});
