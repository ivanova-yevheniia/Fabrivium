import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SensitivityPanel } from "./SensitivityPanel";
import { EquipmentDiscovery } from "./EquipmentDiscovery";
import { deriveThreshold, runSensitivity } from "../../api/uncertainty";
import type { FactoryConceptDraft } from "../../api/types";

/** Station-scoped analysis — reproduced in the human golden run. */

vi.mock("../../api/uncertainty", async () => {
  const actual = await vi.importActual<typeof import("../../api/uncertainty")>("../../api/uncertainty");
  return { ...actual, runSensitivity: vi.fn(), deriveThreshold: vi.fn() };
});

vi.mock("../../api/equipment", async () => {
  const actual = await vi.importActual<typeof import("../../api/equipment")>("../../api/equipment");
  return { ...actual, discoverEquipment: vi.fn(), selectEquipment: vi.fn() };
});

const sweepMock = vi.mocked(runSensitivity);
const thresholdMock = vi.mocked(deriveThreshold);

const SCREWDRIVING = "m-screwdriving";
const CABLE = "m-assembly-2";

const draft = {
  name: "CEC-120",
  stages: [
    { id: SCREWDRIVING, name: "Screw fastening ×6" },
    { id: CABLE, name: "Cable connection ×2" },
  ],
} as unknown as FactoryConceptDraft;

/** The golden-run sweep: 21.6 / 39.8 / 57.9 s across the estimated range. */
const screwSweep = {
  stage_id: SCREWDRIVING,
  stage_name: "Screw fastening ×6",
  parameter: "cycle_time",
  unit: "s",
  points: [
    { value: 21.6, unit: "s", completed_units: 1900, target_units: 1900, meets_target: true, bottleneck_machine_id: CABLE },
    { value: 39.8, unit: "s", completed_units: 1900, target_units: 1900, meets_target: true, bottleneck_machine_id: SCREWDRIVING },
    { value: 57.9, unit: "s", completed_units: 1490, target_units: 1900, meets_target: false, bottleneck_machine_id: SCREWDRIVING },
  ],
  simulations_run: 3,
  monotonic: true,
  summary: "The target is met up to 39.8 s and missed beyond it.",
};

const screwThreshold = {
  stage_id: SCREWDRIVING,
  stage_name: "Screw fastening ×6",
  parameter: "cycle_time",
  unit: "s",
  threshold: 41.1,
  target_units: 1900,
  simulations_run: 15,
  monotonic: true,
  statement:
    "To achieve 1,900 units/day with this configuration, Screw fastening ×6 must operate at 41.1 s/unit or faster.",
  requirement_value: {
    value: 41.1,
    source: "CALCULATED" as const,
    detail: "Derived from 15 simulations",
  },
};

/** Stands in for ConceptVerified, which owns the one selected station. */
function Harness({ start = SCREWDRIVING }: { start?: string } = {}) {
  const [stationId, setStationId] = useState(start);
  const name = draft.stages.find((s) => s.id === stationId)?.name ?? stationId;
  return (
    <>
      <select
        aria-label="Station"
        value={stationId}
        onChange={(event) => setStationId(event.target.value)}
        data-testid="station-select"
      >
        {draft.stages.map((stage) => (
          <option key={stage.id} value={stage.id}>
            {stage.name}
          </option>
        ))}
      </select>
      <SensitivityPanel draft={draft} stageId={stationId} stageName={name} />
    </>
  );
}

beforeEach(() => {
  sweepMock.mockReset();
  thresholdMock.mockReset();
  sweepMock.mockResolvedValue(screwSweep);
  thresholdMock.mockResolvedValue(screwThreshold);
});

describe("changing station discards the previous station's analysis", () => {
  it("hides a sweep that belongs to the station just left", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByTestId("sensitivity-run"));
    expect(await screen.findByTestId("sensitivity-result")).toBeInTheDocument();
    expect(screen.getByTestId("sweep-point-39.8")).toBeInTheDocument();

    await user.selectOptions(screen.getByTestId("station-select"), CABLE);

    // The exact defect: 21.6 / 39.8 / 57.9 under Cable connection ×2.
    expect(screen.queryByTestId("sensitivity-result")).not.toBeInTheDocument();
    expect(screen.queryByTestId("sweep-point-39.8")).not.toBeInTheDocument();
    expect(screen.getByTestId("sensitivity-panel")).not.toHaveTextContent("57.9");
  });

  it("hides a feasibility finding that belongs to the station just left", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByTestId("threshold-run"));
    expect(await screen.findByTestId("threshold-result")).toBeInTheDocument();

    await user.selectOptions(screen.getByTestId("station-select"), CABLE);

    expect(screen.queryByTestId("threshold-result")).not.toBeInTheDocument();
    expect(screen.getByTestId("sensitivity-panel")).not.toHaveTextContent("41.1");
  });

  it("updates the heading to the newly selected station", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByTestId("sensitivity-run"));
    await screen.findByTestId("sensitivity-result");
    expect(screen.getByTestId("sensitivity-panel")).toHaveTextContent(
      "Screw fastening ×6 — how much does this assumption matter?",
    );

    await user.selectOptions(screen.getByTestId("station-select"), CABLE);

    expect(screen.getByTestId("sensitivity-panel")).toHaveTextContent(
      "Cable connection ×2 — how much does this assumption matter?",
    );
    // Never relabelled: the old station's name is gone with its numbers.
    expect(screen.getByTestId("sensitivity-panel")).not.toHaveTextContent("Screw fastening");
  });

  it("returns the buttons to their un-run state", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByTestId("sensitivity-run"));
    await screen.findByTestId("sensitivity-result");

    await user.selectOptions(screen.getByTestId("station-select"), CABLE);

    expect(screen.getByTestId("sensitivity-run")).toHaveTextContent("Test the range");
    expect(screen.getByTestId("sensitivity-run")).toBeEnabled();
    expect(screen.getByTestId("threshold-run")).toHaveTextContent("Can improving this station reach the target?");
    expect(screen.getByTestId("threshold-run")).toBeEnabled();
  });

  it("runs no simulation merely because the station changed", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByTestId("sensitivity-run"));
    await screen.findByTestId("sensitivity-result");
    expect(sweepMock).toHaveBeenCalledTimes(1);

    await user.selectOptions(screen.getByTestId("station-select"), CABLE);

    // Selecting a station asks a question. It does not answer it, and
    // spending real simulations on a selector change would decide for the
    // engineer what they wanted to know.
    expect(sweepMock).toHaveBeenCalledTimes(1);
    expect(thresholdMock).not.toHaveBeenCalled();
  });

  it("stays cleared when the engineer switches back", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByTestId("sensitivity-run"));
    await screen.findByTestId("sensitivity-result");

    await user.selectOptions(screen.getByTestId("station-select"), CABLE);
    await user.selectOptions(screen.getByTestId("station-select"), SCREWDRIVING);

    // The deterministic choice: cleared, not cached. A restored result would
    // be arithmetic over a draft that may have moved since, shown as
    // current — and the engineer cannot tell by looking how old it is.
    expect(screen.queryByTestId("sensitivity-result")).not.toBeInTheDocument();
    expect(sweepMock).toHaveBeenCalledTimes(1);
  });
});

describe("a result is never rendered against the wrong station", () => {
  it("refuses a response whose stage_id is not the selected station", async () => {
    // The race the clearing effect alone cannot cover: a sweep started on
    // one station and resolving after the engineer moved to another. Effects
    // a table of someone else's numbers.
    sweepMock.mockResolvedValue({ ...screwSweep, stage_id: SCREWDRIVING });
    const user = userEvent.setup();
    render(<Harness start={CABLE} />);

    await user.click(screen.getByTestId("sensitivity-run"));

    // The response arrived, and belongs to a station that is not selected.
    expect(await screen.findByTestId("sensitivity-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("sensitivity-result")).not.toBeInTheDocument();
    expect(screen.getByTestId("sensitivity-panel")).not.toHaveTextContent("39.8");
  });

  it("refuses a threshold whose stage_id is not the selected station", async () => {
    thresholdMock.mockResolvedValue({ ...screwThreshold, stage_id: SCREWDRIVING });
    const user = userEvent.setup();
    render(<Harness start={CABLE} />);

    await user.click(screen.getByTestId("threshold-run"));

    expect(await screen.findByTestId("sensitivity-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("threshold-result")).not.toBeInTheDocument();
    expect(screen.getByTestId("sensitivity-panel")).not.toHaveTextContent("41.1");
  });

  it("shows a result for the station it belongs to", async () => {
    // The guard must not be so strict that nothing renders at all.
    sweepMock.mockResolvedValue({
      ...screwSweep,
      stage_id: CABLE,
      stage_name: "Cable connection ×2",
    });
    const user = userEvent.setup();
    render(<Harness start={CABLE} />);

    await user.click(screen.getByTestId("sensitivity-run"));

    expect(await screen.findByTestId("sensitivity-result")).toBeInTheDocument();
  });
});

describe("one station, shared by every panel in Handoff", () => {
  /** Mirrors ConceptVerified: one owner, both panels reading the same id. */
  function Handoff({ start = SCREWDRIVING }: { start?: string } = {}) {
    const [stationId, setStationId] = useState(start);
    const name = draft.stages.find((s) => s.id === stationId)?.name ?? stationId;
    return (
      <>
        <SensitivityPanel draft={draft} stageId={stationId} stageName={name} />
        <EquipmentDiscovery
          draft={draft}
          stationId={stationId}
          onStationChange={setStationId}
          strategyContext="Plan B"
        />
      </>
    );
  }

  it("the equipment selector drives the sensitivity panel above it", async () => {
    // The defect end to end: the selector at the bottom of Handoff moved and
    // the analysis above it did not.
    const user = userEvent.setup();
    render(<Handoff />);

    await user.click(screen.getByTestId("sensitivity-run"));
    expect(await screen.findByTestId("sensitivity-result")).toBeInTheDocument();

    await user.selectOptions(screen.getByTestId("equipment-station-select"), CABLE);

    expect(screen.getByTestId("sensitivity-panel")).toHaveTextContent(
      "Cable connection ×2 — how much does this assumption matter?",
    );
    expect(screen.queryByTestId("sensitivity-result")).not.toBeInTheDocument();
  });

  it("equipment discovery works on the station the engineer just chose", async () => {
    const user = userEvent.setup();
    render(<Handoff />);

    const picker = screen.getByTestId("equipment-station-select") as HTMLSelectElement;
    expect(picker.value).toBe(SCREWDRIVING);

    await user.selectOptions(picker, CABLE);

    // Still the selector's own value, and still what a search would use —
    // making the station controlled must not cost equipment discovery the
    // behaviour it already had.
    expect((screen.getByTestId("equipment-station-select") as HTMLSelectElement).value).toBe(CABLE);
  });
});

describe("after a reload", () => {
  it("no station's analysis is restored under any station", () => {
    // Sensitivity and threshold results are never persisted — they are not
    // in ProjectState, and this is the test that says so on purpose rather
    // than by omission. A reopened project therefore cannot show station A's
    // table with station B selected, because it shows no table at all until
    // the engineer asks for one.
    render(<Harness start={CABLE} />);

    expect(screen.queryByTestId("sensitivity-result")).not.toBeInTheDocument();
    expect(screen.queryByTestId("threshold-result")).not.toBeInTheDocument();
    expect(screen.getByTestId("sensitivity-run")).toHaveTextContent("Test the range");
  });
});
