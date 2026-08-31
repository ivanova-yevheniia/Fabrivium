import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { EstimateAssistant } from "./EstimateAssistant";
import { SensitivityPanel } from "./SensitivityPanel";
import {
  acceptStationAssumptions,
  applyEstimate,
  deriveThreshold,
  estimateCycleTime,
  runSensitivity,
} from "../../api/uncertainty";
import type { FactoryConceptDraft } from "../../api/types";

/** Phase 18 — what the uncertainty screens are allowed to say. */

vi.mock("../../api/uncertainty", async () => {
  const actual = await vi.importActual<typeof import("../../api/uncertainty")>("../../api/uncertainty");
  return {
    ...actual,
    estimateCycleTime: vi.fn(),
    applyEstimate: vi.fn(),
    acceptStationAssumptions: vi.fn(),
    runSensitivity: vi.fn(),
    deriveThreshold: vi.fn(),
  };
});

const estimateMock = vi.mocked(estimateCycleTime);
const applyMock = vi.mocked(applyEstimate);
const acceptMock = vi.mocked(acceptStationAssumptions);
const sweepMock = vi.mocked(runSensitivity);
const thresholdMock = vi.mocked(deriveThreshold);

const draft = { name: "Concept", stages: [] } as unknown as FactoryConceptDraft;

const proposal = {
  low: 35,
  working_value: 45,
  high: 55,
  unit: "s",
  confidence: "MEDIUM" as const,
  method: "LANGUAGE_MODEL" as const,
  basis: "6 fastening operations + handling allowance",
  model_name: "granite-test",
};

const localProposal = {
  ...proposal,
  method: "LOCAL_HEURISTIC" as const,
  model_name: null,
  basis: "Local engineering heuristic: 6-12 s handling + 6 x 4-9 s per screw.",
};

/** Phase 18B — the whole station in one answer. */
function stationProposal(
  overrides: Partial<import("../../api/uncertainty").StationAssumptionProposal> = {},
) {
  return {
    stage_id: "m-screwdriving",
    stage_name: "Screwdriving",
    cycle_time: proposal,
    capacity: { ...localProposal, low: 1, working_value: 1, high: 1, unit: "units", basis: "One unit at a time." },
    operators: { ...localProposal, low: 1, working_value: 1, high: 1, unit: "operators", basis: "One person for its duration." },
    fell_back: false,
    provider_note: null,
    ...overrides,
  };
}

/** One place that knows the response shape. */
function estimateResult(
  overrides: Partial<import("../../api/uncertainty").EstimateResult> = {},
): import("../../api/uncertainty").EstimateResult {
  return {
    estimate: null,
    proposal: null,
    needs_information: null,
    contradiction: null,
    fell_back: false,
    provider_note: null,
    takt_seconds: {} as never,
    ...overrides,
  };
}

beforeEach(() => {
  estimateMock.mockReset();
  applyMock.mockReset();
  acceptMock.mockReset();
  acceptMock.mockResolvedValue({ draft, validation: {}, applied: [] } as never);
  sweepMock.mockReset();
  thresholdMock.mockReset();
  applyMock.mockResolvedValue({ draft, validation: {} } as never);
});

function renderAssistant(onApplied = vi.fn()) {
  render(
    <EstimateAssistant
      draft={draft}
      stageId="m-screwdriving"
      stageName="Screwdriving"
      taktSeconds={30.3}
      onApplied={onApplied}
    />,
  );
  return { user: userEvent.setup(), onApplied };
}

/** Phase 18B shows one route at a time, so the assistant tab must be
 * selected before its fields exist. */
async function openAssistant(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId("estimate-mode-assist"));
}

describe("both paths are offered", () => {
  it("opens on direct entry, so a known value needs no detour", () => {
    renderAssistant();
    // §2: an experienced engineer must always be able to enter known values
    // directly. Phase 18B makes this the DEFAULT tab rather than a second
    // form competing for attention.
    expect(screen.getByTestId("estimate-manual-working")).toBeInTheDocument();
    expect(screen.queryByTestId("estimate-assist-form")).toBeNull();
  });

  it("shows only one route at a time", async () => {
    const { user } = renderAssistant();

    await user.click(screen.getByTestId("estimate-mode-assist"));
    expect(screen.getByTestId("estimate-assist-form")).toBeInTheDocument();
    expect(screen.queryByTestId("estimate-manual")).toBeNull();

    await user.click(screen.getByTestId("estimate-mode-known"));
    expect(screen.getByTestId("estimate-manual")).toBeInTheDocument();
    expect(screen.queryByTestId("estimate-assist-form")).toBeNull();
  });

  it("labels the repeat count so it cannot be read backwards", async () => {
    const { user } = renderAssistant();
    await openAssistant(user);

    const form = screen.getByTestId("estimate-assist-form");
    expect(form).toHaveTextContent(/Repeated operations per unit/i);
    expect(form).toHaveTextContent(/How many times this operation happens on one product/i);
  });

  it("applies a manually entered range without calling the assistant", async () => {
    const { user, onApplied } = renderAssistant();

    await user.type(screen.getByTestId("estimate-manual-low"), "30");
    await user.type(screen.getByTestId("estimate-manual-working"), "38");
    await user.type(screen.getByTestId("estimate-manual-high"), "50");
    await user.type(screen.getByTestId("estimate-manual-basis"), "measured on a comparable line");
    await user.click(screen.getByTestId("estimate-manual-apply"));

    expect(estimateMock).not.toHaveBeenCalled();
    expect(applyMock).toHaveBeenCalledTimes(1);
    const [, , range] = applyMock.mock.calls[0];
    expect(range.working_value).toBe(38);
    expect(range.method).toBe("ENGINEER");
    expect(onApplied).toHaveBeenCalled();
  });

  it("will not apply a manual range without a stated basis", async () => {
    const { user } = renderAssistant();

    await user.type(screen.getByTestId("estimate-manual-low"), "30");
    await user.type(screen.getByTestId("estimate-manual-working"), "38");
    await user.type(screen.getByTestId("estimate-manual-high"), "50");

    // An estimate with no basis is indistinguishable from a guess.
    expect(screen.getByTestId("estimate-manual-apply")).toBeDisabled();
  });

  it("gives the line's takt as context for judging a range", () => {
    renderAssistant();
    expect(screen.getByTestId("estimate-assistant")).toHaveTextContent(/30\.3 s\/unit/);
    // And says what takt is not, so it is not read as a station target.
    expect(screen.getByTestId("estimate-assistant")).toHaveTextContent(/not a value any one station can sit at/i);
  });
});

describe("one card for the whole station", () => {
  it("shows every parameter the assistant proposed", async () => {
    estimateMock.mockResolvedValue(estimateResult({ estimate: proposal, proposal: stationProposal() }));
    const { user } = renderAssistant();
    await openAssistant(user);

    await user.type(screen.getByTestId("estimate-description"), "six screws into an enclosure");
    await user.click(screen.getByTestId("estimate-ask"));

    // The engineer described the operation once, so one card answers for
    // every simulation parameter rather than three separate panels.
    await screen.findByTestId("assumption-card");
    expect(screen.getByTestId("assumption-value-cycle_time")).toHaveTextContent("45");
    expect(screen.getByTestId("assumption-value-capacity")).toHaveTextContent("1");
    expect(screen.getByTestId("assumption-value-operators")).toHaveTextContent("1");
  });

  it("keeps each parameter's own basis behind its own info control", async () => {
    estimateMock.mockResolvedValue(estimateResult({ estimate: proposal, proposal: stationProposal() }));
    const { user } = renderAssistant();
    await openAssistant(user);

    await user.type(screen.getByTestId("estimate-description"), "six screws");
    await user.click(screen.getByTestId("estimate-ask"));
    await screen.findByTestId("assumption-card");

    // A cycle time from reference bands and an operator count read off the
    // word "manual" rest on different evidence, so they get different panels.
    await user.click(screen.getByTestId("assumption-info-cycle_time"));
    expect(screen.getByTestId("assumption-detail-cycle_time")).toHaveTextContent(/fastening operations/);

    await user.click(screen.getByTestId("assumption-info-operators"));
    expect(screen.getByTestId("assumption-detail-operators")).toHaveTextContent(/One person for its duration/);
  });

  it("names the estimator rather than saying AI", async () => {
    estimateMock.mockResolvedValue(estimateResult({ estimate: proposal, proposal: stationProposal() }));
    const { user } = renderAssistant();
    await openAssistant(user);

    await user.type(screen.getByTestId("estimate-description"), "six screws");
    await user.click(screen.getByTestId("estimate-ask"));
    await user.click(await screen.findByTestId("assumption-info-cycle_time"));

    expect(screen.getByTestId("assumption-detail-cycle_time")).toHaveTextContent("granite-test");
  });

  it("renders an unproposed parameter as a word, never as a blank or a default", async () => {
    estimateMock.mockResolvedValue(
      estimateResult({
        estimate: proposal,
        proposal: stationProposal({ capacity: null, operators: null }),
      }),
    );
    const { user } = renderAssistant();
    await openAssistant(user);

    await user.type(screen.getByTestId("estimate-description"), "batch oven");
    await user.click(screen.getByTestId("estimate-ask"));

    // `concept_to_factory` will default an absent capacity to 1, but that is
    // a conversion convention — showing it here would make it look like a
    // finding.
    expect(await screen.findByTestId("assumption-unknown-capacity")).toHaveTextContent(/Not established/);
    expect(screen.getByTestId("assumption-unknown-operators")).toBeInTheDocument();
  });

  it("states the caveat in the open, not in a tooltip", async () => {
    estimateMock.mockResolvedValue(estimateResult({ estimate: proposal, proposal: stationProposal() }));
    const { user } = renderAssistant();
    await openAssistant(user);

    await user.type(screen.getByTestId("estimate-description"), "six screws");
    await user.click(screen.getByTestId("estimate-ask"));

    const card = await screen.findByTestId("assumption-card");
    expect(card).toHaveTextContent(/Suitable for concept simulation/i);
    expect(card).toHaveTextContent(/Not detailed engineering specifications/i);
  });

  it("applies nothing until the engineer accepts", async () => {
    estimateMock.mockResolvedValue(estimateResult({ estimate: proposal, proposal: stationProposal() }));
    const { user } = renderAssistant();
    await openAssistant(user);

    await user.type(screen.getByTestId("estimate-description"), "six screws");
    await user.click(screen.getByTestId("estimate-ask"));
    await screen.findByTestId("assumption-card");

    expect(acceptMock).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("assumption-accept-all"));
    expect(acceptMock).toHaveBeenCalledTimes(1);
  });

  it("accepts every parameter at once, so nothing is copied by hand", async () => {
    estimateMock.mockResolvedValue(estimateResult({ estimate: proposal, proposal: stationProposal() }));
    const { user } = renderAssistant();
    await openAssistant(user);

    await user.type(screen.getByTestId("estimate-description"), "six screws");
    await user.click(screen.getByTestId("estimate-ask"));
    await user.click(await screen.findByTestId("assumption-accept-all"));

    const [, , fields] = acceptMock.mock.calls[0];
    expect(fields).toEqual(["cycle_time", "capacity", "operators"]);
  });

  it("lets the engineer accept only some parameters", async () => {
    estimateMock.mockResolvedValue(estimateResult({ estimate: proposal, proposal: stationProposal() }));
    const { user } = renderAssistant();
    await openAssistant(user);

    await user.type(screen.getByTestId("estimate-description"), "six screws");
    await user.click(screen.getByTestId("estimate-ask"));
    await user.click(await screen.findByTestId("assumption-edit"));

    await user.click(screen.getByTestId("assumption-toggle-operators"));
    await user.click(screen.getByTestId("assumption-accept-all"));

    const [, , fields] = acceptMock.mock.calls[0];
    expect(fields).toEqual(["cycle_time", "capacity"]);
  });
});

describe("a genuine gap is still refused", () => {
  it("asks for what is missing instead of inventing a range", async () => {
    estimateMock.mockResolvedValue(
      estimateResult({
        needs_information: {
          reason: "Fabrivium has no engineering reference data for 'welding'.",
          questions: ["Enter the cycle time directly, or a range if you know one."],
        },
      }),
    );
    const { user } = renderAssistant();
    await openAssistant(user);

    await user.type(screen.getByTestId("estimate-description"), "six screws");
    await user.click(screen.getByTestId("estimate-ask"));

    const message = await screen.findByTestId("estimate-needs-information");
    expect(message).toHaveTextContent(/Not enough information/i);
    expect(message).toHaveTextContent(/Enter the cycle time directly/i);
    // The decisive assertion: no proposal appears in place of the gap.
    expect(screen.queryByTestId("assumption-card")).toBeNull();
    // And the direct-entry route is one click away.
    expect(screen.getByTestId("estimate-switch-to-known")).toBeInTheDocument();
  });
});

describe("a provider outage is not a dead end", () => {
  function localStation() {
    return estimateResult({
      estimate: localProposal,
      proposal: stationProposal({ cycle_time: localProposal, fell_back: true }),
      fell_back: true,
    });
  }

  it("shows the card normally when the local route produced it", async () => {
    estimateMock.mockResolvedValue(localStation());
    const { user } = renderAssistant();
    await openAssistant(user);

    await user.type(screen.getByTestId("estimate-description"), "six screws");
    await user.click(screen.getByTestId("estimate-ask"));

    expect(await screen.findByTestId("assumption-card")).toBeInTheDocument();
    expect(screen.getByTestId("assumption-value-cycle_time")).toHaveTextContent("45");
  });

  it("never shows provider internals in the primary UI", async () => {
    estimateMock.mockResolvedValue({
      ...localStation(),
      provider_note: "LLMAuthenticationError: HTTP 403 token_quota_reached",
    });
    const { user } = renderAssistant();
    await openAssistant(user);

    await user.type(screen.getByTestId("estimate-description"), "six screws");
    await user.click(screen.getByTestId("estimate-ask"));
    await screen.findByTestId("assumption-card");

    // Quota is a fact about our account, not about the engineering.
    const assistant = screen.getByTestId("estimate-assistant");
    expect(assistant).not.toHaveTextContent(/403/);
    expect(assistant).not.toHaveTextContent(/token_quota_reached/);
    expect(assistant).not.toHaveTextContent(/HTTP/);
  });

  it("says which route produced the numbers, quietly", async () => {
    estimateMock.mockResolvedValue(localStation());
    const { user } = renderAssistant();
    await openAssistant(user);

    await user.type(screen.getByTestId("estimate-description"), "six screws");
    await user.click(screen.getByTestId("estimate-ask"));

    expect(await screen.findByTestId("assumption-route")).toHaveTextContent(/Estimated locally/i);
  });

  it("does not attribute a local estimate to a model", async () => {
    estimateMock.mockResolvedValue(localStation());
    const { user } = renderAssistant();
    await openAssistant(user);

    await user.type(screen.getByTestId("estimate-description"), "six screws");
    await user.click(screen.getByTestId("estimate-ask"));
    await user.click(await screen.findByTestId("assumption-info-cycle_time"));

    const detail = screen.getByTestId("assumption-detail-cycle_time");
    expect(detail).toHaveTextContent(/Fabrivium local engineering heuristic/);
    expect(detail).not.toHaveTextContent(/granite/i);
  });
});

describe("contradictory inputs", () => {
  it("asks which reading to use instead of picking one", async () => {
    estimateMock.mockResolvedValue(
      estimateResult({
        contradiction: {
          message: "Your description reads as manual, but automation is set to automatic. Which should Fabrivium use?",
          described_as: "MANUAL",
          selected_as: "AUTOMATIC",
        },
      }),
    );
    const { user } = renderAssistant();
    await openAssistant(user);

    await user.type(screen.getByTestId("estimate-description"), "Manual assembly by an operator");
    await user.click(screen.getByTestId("estimate-ask"));

    const clash = await screen.findByTestId("estimate-contradiction");
    expect(clash).toHaveTextContent(/reads as manual/i);
    // Both readings are offered; Fabrivium does not decide.
    expect(screen.getByTestId("estimate-use-described")).toHaveTextContent(/manual/i);
    expect(screen.getByTestId("estimate-keep-selected")).toHaveTextContent(/automatic/i);
    expect(screen.queryByTestId("assumption-card")).toBeNull();
  });

  it("re-estimates with the resolution the engineer chose", async () => {
    estimateMock.mockResolvedValueOnce(
      estimateResult({
        contradiction: { message: "…", described_as: "MANUAL", selected_as: "AUTOMATIC" },
      }),
    );
    const { user } = renderAssistant();
    await openAssistant(user);

    await user.type(screen.getByTestId("estimate-description"), "Manual assembly");
    await user.click(screen.getByTestId("estimate-ask"));
    await screen.findByTestId("estimate-contradiction");

    estimateMock.mockResolvedValueOnce(
      estimateResult({
        estimate: localProposal,
        proposal: stationProposal({ cycle_time: localProposal, fell_back: true }),
        fell_back: true,
      }),
    );
    await user.click(screen.getByTestId("estimate-use-described"));

    expect(await screen.findByTestId("assumption-card")).toBeInTheDocument();
    const lastCall = estimateMock.mock.calls[estimateMock.mock.calls.length - 1];
    expect(lastCall[2].automation_level).toBe("MANUAL");
  });
});

describe("sensitivity", () => {
  const sweep = {
    stage_id: "m-screwdriving",
    stage_name: "Screwdriving",
    parameter: "cycle_time",
    unit: "s",
    points: [
      { value: 35, unit: "s", completed_units: 1643, target_units: 1900, meets_target: false, bottleneck_machine_id: "m-assembly" },
      { value: 45, unit: "s", completed_units: 1278, target_units: 1900, meets_target: false, bottleneck_machine_id: "m-screwdriving" },
    ],
    simulations_run: 2,
    monotonic: true,
    summary: "The target is missed across the whole estimated range.",
  };

  function renderPanel() {
    render(<SensitivityPanel draft={draft} stageId="m-screwdriving" stageName="Screwdriving" />);
    return userEvent.setup();
  }

  it("reports real simulation runs, not samples", async () => {
    sweepMock.mockResolvedValue(sweep);
    const user = renderPanel();

    await user.click(screen.getByTestId("sensitivity-run"));

    expect(await screen.findByTestId("sensitivity-summary")).toHaveTextContent("Range sweep · 2 simulations");
    const panel = screen.getByTestId("sensitivity-panel");
    expect(panel).toHaveTextContent(/real runs, not samples/i);
    // Nothing here samples a distribution, so the phrase must not appear.
    expect(panel).not.toHaveTextContent(/monte carlo/i);
    expect(panel).not.toHaveTextContent(/probability/i);
  });

  it("shows each point's verdict and limiting station", async () => {
    sweepMock.mockResolvedValue(sweep);
    const user = renderPanel();

    await user.click(screen.getByTestId("sensitivity-run"));

    const row = await screen.findByTestId("sweep-point-35");
    expect(row).toHaveTextContent("1,643");
    expect(row).toHaveTextContent("FAIL");
    // §2 — the table names the limiting station instead of printing its
    // internal key. "m-assembly" is a database identifier and must not
    // reach the screen.
    expect(row).toHaveTextContent("Assembly");
    expect(row).not.toHaveTextContent("m-assembly");
  });

  it("warns when the response is not monotonic instead of implying a threshold", async () => {
    sweepMock.mockResolvedValue({ ...sweep, monotonic: false });
    const user = renderPanel();

    await user.click(screen.getByTestId("sensitivity-run"));

    expect(await screen.findByTestId("sensitivity-non-monotonic")).toHaveTextContent(
      /no single threshold would describe it/i,
    );
  });
});

describe("derived requirement", () => {
  function renderPanel() {
    render(<SensitivityPanel draft={draft} stageId="m-screwdriving" stageName="Screwdriving" />);
    return userEvent.setup();
  }

  it("states the requirement as a number an engineer can ask a vendor for", async () => {
    thresholdMock.mockResolvedValue({
      stage_id: "m-screwdriving",
      stage_name: "Screwdriving",
      parameter: "cycle_time",
      unit: "s",
      threshold: 41.1,
      target_units: 1400,
      simulations_run: 15,
      monotonic: true,
      statement: "To achieve 1,400 units/day with this configuration, Screwdriving must operate at 41.1 s/unit or faster.",
      requirement_value: { value: 41.1, source: "CALCULATED", detail: "Derived from 15 simulations" },
    });
    const user = renderPanel();

    await user.click(screen.getByTestId("threshold-run"));

    expect(await screen.findByTestId("threshold-statement")).toHaveTextContent("41.1 s/unit or faster");
    expect(screen.getByTestId("threshold-result")).toHaveTextContent("15 simulations");
  });

  it("shows the reason, not a number, when no threshold exists", async () => {
    thresholdMock.mockResolvedValue({
      stage_id: "m-screwdriving",
      stage_name: "Screwdriving",
      parameter: "cycle_time",
      unit: "s",
      threshold: null,
      target_units: 1900,
      simulations_run: 2,
      monotonic: true,
      statement:
        "Even at 10 s the concept reaches only 1,643 of 1,900 units/day, so Screwdriving is not what is holding the target back. The limiting station is 'm-assembly'.",
      requirement_value: { value: null, source: "UNKNOWN", detail: null },
    });
    const user = renderPanel();

    await user.click(screen.getByTestId("threshold-run"));

    const result = await screen.findByTestId("threshold-result");
    // "No single answer exists" is itself an engineering finding, and it
    // must not be rendered as a requirement.
    expect(result).toHaveTextContent(/not what is holding the target back/i);
    expect(result).toHaveTextContent(/Finding/);
    expect(result).not.toHaveTextContent(/Engineering requirement/);
  });
});
