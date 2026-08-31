import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ResolveInputs } from "./ResolveInputs";
import type { ResolutionPlan, ResolvableInput } from "../../api/concept";
import type { EstimatedRange } from "../../api/uncertainty";
import type { FactoryConceptDraft } from "../../api/types";

/** Resolve engineering inputs — the UI contract. */

vi.mock("../../api/concept", async () => {
  const actual = await vi.importActual<typeof import("../../api/concept")>("../../api/concept");
  return {
    ...actual,
    resolutionPlan: vi.fn(),
    resolveInput: vi.fn(),
    applyExampleData: vi.fn(),
    useExampleDataForUnresolved: vi.fn(),
    bufferSensitivity: vi.fn(),
  };
});

const api = await import("../../api/concept");

const draft = { buffers: [{ id: "b1" }] } as unknown as FactoryConceptDraft;

function input(over: Partial<ResolvableInput> & Pick<ResolvableInput, "key" | "label">): ResolvableInput {
  return {
    unit: null,
    value: null,
    source: "UNKNOWN",
    detail: null,
    necessity: "BLOCKS_SIMULATION",
    consequence: "Because the simulator reads it.",
    actions: ["ENGINEER_INPUT", "LEAVE_UNKNOWN"],
    stage_id: null,
    quote_required: false,
    resolved: false,
    estimate: null,
    superseded: null,
    ...over,
  };
}

const PLAN: ResolutionPlan = {
  inputs: [
    input({
      key: "shifts_per_day",
      label: "Shifts per day",
      actions: ["ENGINEER_INPUT", "USE_EXAMPLE_DATA", "LEAVE_UNKNOWN"],
      consequence: "An operating decision. It cannot be inferred from the target.",
    }),
    input({
      key: "production_target",
      label: "Daily production target",
      unit: "units/day",
      value: 1900,
      source: "CUSTOMER",
      detail: "Stated in the customer brief",
      resolved: true,
    }),
    input({
      key: "stage.m-screwdriving.cycle_time",
      label: "Screwdriving — cycle time",
      unit: "s",
      stage_id: "m-screwdriving",
      actions: ["ESTIMATE", "ENGINEER_INPUT", "USE_EXAMPLE_DATA", "LEAVE_UNKNOWN"],
    }),
    input({
      key: "stage.m-screwdriving.purchase_cost",
      label: "Screwdriving — equipment cost",
      unit: "€",
      necessity: "COMMERCIAL_ONLY",
      quote_required: true,
      actions: ["EXTERNAL_DATA", "ENTER_QUOTE", "USE_EXAMPLE_DATA", "LEAVE_UNKNOWN"],
      consequence: "Commercial only. An unknown price stays unknown.",
    }),
  ],
  computed: [
    {
      key: "required_takt",
      label: "Required takt",
      unit: "s/unit",
      value: 30.32,
      formula: "57,600 s ÷ 1,900 units",
      blocked_by: null,
      source: "CALCULATED",
    },
    {
      key: "available_production_time",
      label: "Available production time",
      unit: "s/day",
      value: null,
      formula: "shifts × hours × 3600",
      blocked_by: "the operating schedule",
      source: "CALCULATED",
    },
  ],
  blocking_unresolved: 3,
  ready_to_simulate: false,
};

function renderPanel(overrides: Partial<Parameters<typeof ResolveInputs>[0]> = {}) {
  return render(
    <ResolveInputs
      draft={draft}
      onDraftChange={overrides.onDraftChange ?? (() => {})}
      onEstimateStage={overrides.onEstimateStage ?? (() => {})}
      onClose={overrides.onClose ?? (() => {})}
      isExampleProject={overrides.isExampleProject ?? true}
    />,
  );
}

beforeEach(() => {
  // "called exactly once" then measure the whole file rather than the case.
  vi.clearAllMocks();
  vi.mocked(api.resolutionPlan).mockResolvedValue(PLAN);
  vi.mocked(api.resolveInput).mockResolvedValue({ draft, validation: {} as never });
});

describe("resolve engineering inputs", () => {
  it("offers only the routes that can honestly produce each value", async () => {
    renderPanel();
    const cost = await screen.findByTestId("resolve-row-stage.m-screwdriving.purchase_cost");

    // A price is never estimated: it is published, quoted, or unknown.
    expect(
      within(cost).queryByTestId("resolve-action-ESTIMATE-stage.m-screwdriving.purchase_cost"),
    ).toBeNull();
    expect(
      within(cost).getByTestId("resolve-action-ENTER_QUOTE-stage.m-screwdriving.purchase_cost"),
    ).toBeInTheDocument();

    // Operation physics is estimatable, and offers it first.
    const cycle = screen.getByTestId("resolve-row-stage.m-screwdriving.cycle_time");
    expect(
      within(cycle).getByTestId("resolve-action-ESTIMATE-stage.m-screwdriving.cycle_time"),
    ).toBeInTheDocument();
  });

  it("states an absent value instead of leaving it blank", async () => {
    renderPanel();
    // "Quote required" and "Not established" are answers. A blank cell reads
    // as a rendering failure, and a zero would be a lie.
    expect(await screen.findByTestId("resolve-value-stage.m-screwdriving.purchase_cost")).toHaveTextContent(
      "Quote required",
    );
    expect(screen.getByTestId("resolve-value-shifts_per_day")).toHaveTextContent("Not established");
    expect(screen.getByTestId("resolve-value-stage.m-screwdriving.purchase_cost")).not.toHaveTextContent("€0");
  });

  it("shows where a resolved value came from", async () => {
    renderPanel();
    const target = await screen.findByTestId("resolve-row-production_target");
    expect(within(target).getByText("1,900 units/day")).toBeInTheDocument();
    expect(within(target).getByTestId("source-customer")).toBeInTheDocument();
  });

  it("shows computed values with their arithmetic and never as inputs", async () => {
    renderPanel();
    const takt = await screen.findByTestId("computed-required_takt");
    expect(takt).toHaveTextContent("30.32");
    expect(takt).toHaveTextContent("57,600 s ÷ 1,900 units");
    // Nobody may hand-edit takt into disagreeing with its own definition.
    expect(screen.queryByTestId("resolve-row-required_takt")).toBeNull();
  });

  it("says what a computed value is waiting for", async () => {
    renderPanel();
    const available = await screen.findByTestId("computed-available_production_time");
    expect(available).toHaveTextContent(/needs the operating schedule/i);
  });

  it("records a typed value as ENGINEER, never as CUSTOMER", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByTestId("resolve-action-ENGINEER_INPUT-shifts_per_day"));
    await user.type(screen.getByTestId("resolve-input-shifts_per_day"), "2");
    await user.click(screen.getByTestId("resolve-save-shifts_per_day"));

    await waitFor(() => expect(api.resolveInput).toHaveBeenCalled());
    const [, key, value, source] = vi.mocked(api.resolveInput).mock.calls[0];
    expect(key).toBe("shifts_per_day");
    expect(value).toBe(2);
    // The customer did not say this; the engineer did.
    expect(source).toBe("ENGINEER");
  });

  it("resolves one value without touching the others", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByTestId("resolve-action-ENGINEER_INPUT-shifts_per_day"));
    await user.type(screen.getByTestId("resolve-input-shifts_per_day"), "2");
    await user.click(screen.getByTestId("resolve-save-shifts_per_day"));

    await waitFor(() => expect(api.resolveInput).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.resolveInput).mock.calls[0][1]).toBe("shifts_per_day");
  });

  it("lets a value be put back to unknown", async () => {
    const user = userEvent.setup();
    renderPanel();
    // Only meaningful for a value that HAS one — the control is disabled
    // otherwise, because "clear the blank" is not an action.
    const target = await screen.findByTestId("resolve-action-LEAVE_UNKNOWN-production_target");
    await user.click(target);
    await waitFor(() => expect(api.resolveInput).toHaveBeenCalled());
    expect(vi.mocked(api.resolveInput).mock.calls[0][2]).toBeNull();

    expect(screen.getByTestId("resolve-action-LEAVE_UNKNOWN-shifts_per_day")).toBeDisabled();
  });

  it("hands a stage to the estimator rather than estimating inline", async () => {
    const user = userEvent.setup();
    const onEstimateStage = vi.fn();
    renderPanel({ onEstimateStage });
    await user.click(
      await screen.findByTestId("resolve-action-ESTIMATE-stage.m-screwdriving.cycle_time"),
    );
    expect(onEstimateStage).toHaveBeenCalledWith("m-screwdriving");
  });

  it("explains what depends on a value on request", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByTestId("resolve-why-shifts_per_day"));
    expect(screen.getByTestId("resolve-consequence-shifts_per_day")).toHaveTextContent(
      /cannot be inferred from the target/i,
    );
  });

  it("marks which inputs actually block simulation", async () => {
    renderPanel();
    expect(await screen.findByTestId("resolve-necessity-shifts_per_day")).toHaveTextContent(
      /required to simulate/i,
    );
    // Money never blocks physics.
    expect(screen.getByTestId("resolve-necessity-stage.m-screwdriving.purchase_cost")).toHaveTextContent(
      /commercial only/i,
    );
  });

  it("reports what the demo fallback filled and what it refused to touch", async () => {
    const user = userEvent.setup();
    vi.mocked(api.useExampleDataForUnresolved).mockResolvedValue({
      draft,
      validation: {} as never,
      filled: ["a", "b"],
      added: ["buffer.b1.capacity"],
      protected: ["production_target"],
      unavailable: [],
    });
    renderPanel();
    await user.click(await screen.findByTestId("resolve-bulk-example"));
    // §10 — writing twelve fictional values into a real project is not a
    // one-click action. The confirmation states what they are before it
    // happens; nothing is filled until it is accepted.
    const confirm = await screen.findByTestId("resolve-demo-confirm");
    expect(confirm).toHaveTextContent(/fictional demonstration assumptions/i);
    expect(confirm).toHaveTextContent(/tagged as demo data/i);
    expect(api.useExampleDataForUnresolved).not.toHaveBeenCalled();
    await user.click(screen.getByTestId("resolve-demo-confirm-yes"));

    const note = await screen.findByTestId("resolve-bulk-note");
    expect(note).toHaveTextContent(/filled 2 unresolved values/i);
    // Creating buffers is not the same act as filling a blank.
    expect(note).toHaveTextContent(/wired 1 buffer/i);
    // The engineer must be told their decisions survived.
    expect(note).toHaveTextContent(/left untouched/i);
  });

  it("asks the simulator about buffers instead of adopting a size", async () => {
    const user = userEvent.setup();
    vi.mocked(api.bufferSensitivity).mockResolvedValue({
      points: [
        {
          size: 0,
          completed_units: 1105,
          target_units: 1900,
          meets_target: false,
          limiting_stage_id: "m-screwdriving",
          average_level: null,
          upstream_blocked_seconds: 0,
          blocking_observed: false,
        },
      ],
      simulations_run: 6,
      indifferent: true,
      smallest_size_meeting_target: null,
      summary: "Buffer size does not change this line's output.",
    });
    renderPanel();
    await user.click(await screen.findByTestId("buffer-sweep-run"));

    expect(await screen.findByTestId("buffer-summary")).toHaveTextContent(
      /does not change this line's output/i,
    );
    expect(screen.getByTestId("buffer-points")).toHaveTextContent(/no buffers/i);
  });
});

/** The estimate contract, opened from the row's ⓘ. */
describe("the estimate contract in the ⓘ", () => {
  const ESTIMATE: EstimatedRange = {
    low: 30,
    working_value: 48,
    high: 66,
    unit: "s",
    confidence: "MEDIUM",
    method: "LOCAL_HEURISTIC",
    basis: "6–12 s handling + 6 × 4–9 s per screw.",
    model_name: null,
  };

  const KEY = "stage.m-screwdriving.cycle_time";

  function planWith(over: Partial<ResolvableInput>) {
    return {
      ...PLAN,
      inputs: PLAN.inputs.map((i) => (i.key === KEY ? { ...i, ...over } : i)),
    };
  }

  async function openWhy() {
    // Station groups collapse once every value in them is established, so a
    // row inside a settled station is one click away. A station still
    // holding a gap or an estimate is already open and this is a no-op.
    const station = await screen.findByTestId("resolve-station-toggle-m-screwdriving");
    if (station.getAttribute("aria-expanded") === "false") await userEvent.click(station);
    await screen.findByTestId(`resolve-row-${KEY}`);
    await userEvent.click(screen.getByTestId(`resolve-why-${KEY}`));
  }

  it("answers why this value, how it was obtained and what was assumed", async () => {
    vi.mocked(api.resolutionPlan).mockResolvedValue(
      planWith({ value: 48, source: "ENGINEERING_ESTIMATE", resolved: true, estimate: ESTIMATE }),
    );
    renderPanel();
    await openWhy();

    const panel = screen.getByTestId(`resolve-estimate-${KEY}`);
    // How it was obtained — the MECHANISM, never the word "AI".
    expect(panel).toHaveTextContent(/reference bands/i);
    expect(panel).not.toHaveTextContent(/\bAI\b/);
    // What was assumed.
    expect(panel).toHaveTextContent("6–12 s handling + 6 × 4–9 s per screw.");
    // The uncertainty, and that it is qualitative.
    expect(panel).toHaveTextContent("30–66 s");
    expect(panel).toHaveTextContent("MEDIUM");
    // That it can be changed, and that it is not a specification.
    expect(panel).toHaveTextContent(/Preliminary assumption/i);
    expect(panel).toHaveTextContent(/override/i);
  });

  it("names the model when a language model produced the range", async () => {
    vi.mocked(api.resolutionPlan).mockResolvedValue(
      planWith({
        value: 48,
        source: "ENGINEERING_ESTIMATE",
        resolved: true,
        estimate: { ...ESTIMATE, method: "LANGUAGE_MODEL", model_name: "ibm/granite-3-8b-instruct" },
      }),
    );
    renderPanel();
    await openWhy();

    // A judge asking "which model?" gets the answer, not the word "AI".
    expect(screen.getByTestId(`resolve-estimate-method-${KEY}`)).toHaveTextContent(
      "ibm/granite-3-8b-instruct",
    );
  });

  it("does not print a range for a value that has none", async () => {
    // Capacity and operators come back as low == working == high. "1–1 units"
    // would dress a single reading up as a measured spread.
    vi.mocked(api.resolutionPlan).mockResolvedValue(
      planWith({
        value: 1,
        source: "ENGINEERING_ESTIMATE",
        resolved: true,
        estimate: { ...ESTIMATE, low: 1, working_value: 1, high: 1, unit: "units" },
      }),
    );
    renderPanel();
    await openWhy();

    const panel = screen.getByTestId(`resolve-estimate-${KEY}`);
    expect(panel).not.toHaveTextContent("1–1");
    expect(panel).not.toHaveTextContent(/Plausible range/i);
  });

  it("shows no estimate panel once an override has retired the range", async () => {
    vi.mocked(api.resolutionPlan).mockResolvedValue(
      planWith({
        value: 40,
        source: "ENGINEER",
        detail: "Pilot cell stopwatch",
        resolved: true,
        estimate: null,
        superseded: "ENGINEER value supersedes the engineering estimate of 48 s (30–66 s)",
      }),
    );
    renderPanel();
    await openWhy();

    // The heuristic's reasoning must not survive to justify 40 s.
    expect(screen.queryByTestId(`resolve-estimate-${KEY}`)).toBeNull();
    expect(screen.queryByText(/per screw/)).toBeNull();
    // What was replaced is stated instead — the override is visible, not
    // merely correct.
    expect(screen.getByTestId(`resolve-superseded-${KEY}`)).toHaveTextContent(
      /supersedes the engineering estimate of 48 s/,
    );
  });

  it("shows nothing extra for a value that was never an estimate", async () => {
    renderPanel();
    await screen.findByTestId("resolve-row-production_target");
    await userEvent.click(screen.getByTestId("resolve-why-production_target"));

    expect(screen.queryByTestId("resolve-estimate-production_target")).toBeNull();
    expect(screen.getByTestId("resolve-consequence-production_target")).toHaveTextContent(
      "Stated in the customer brief",
    );
  });
});

/**
 * G12 — a station header must not make four optional gaps look like four
 * reasons the line cannot be simulated.
 *
 * The golden run met "6 not established" on a station where two values stop
 * the simulator and four do not: a price nobody has quoted, a footprint only
 * the layout reads, a buffer with a stated default. Counting them together
 * sends an engineer chasing four things that block nothing — and, the second
 * time they notice, teaches them to ignore the number entirely.
 */
describe("what a station header counts", () => {
  const stage = "m-screwdriving";

  function station(...inputs: ResolvableInput[]): ResolutionPlan {
    return { inputs, computed: [], blocking_unresolved: 0, ready_to_simulate: false };
  }

  const blocker = (key: string, label: string) =>
    input({ key: `stage.${stage}.${key}`, label, stage_id: stage, necessity: "BLOCKS_SIMULATION" });
  const other = (key: string, label: string, necessity: ResolvableInput["necessity"]) =>
    input({ key: `stage.${stage}.${key}`, label, stage_id: stage, necessity });

  it("separates what blocks a simulation from what merely is not filled in", async () => {
    vi.mocked(api.resolutionPlan).mockResolvedValue(
      station(
        blocker("cycle_time", "Screwdriving — cycle time"),
        blocker("operators_required", "Screwdriving — operators"),
        other("purchase_cost", "Screwdriving — equipment cost", "COMMERCIAL_ONLY"),
        other("width", "Screwdriving — width", "AFFECTS_LAYOUT"),
        other("length", "Screwdriving — length", "AFFECTS_LAYOUT"),
        other("capacity", "Screwdriving — capacity", "HAS_DEFAULT"),
      ),
    );
    renderPanel();

    const chip = await screen.findByTestId(`resolve-station-gaps-${stage}`);
    expect(within(chip).getByTestId(`resolve-station-blocking-${stage}`)).toHaveTextContent(
      "2 needed to simulate",
    );
    expect(within(chip).getByTestId(`resolve-station-other-${stage}`)).toHaveTextContent(
      "4 other unresolved",
    );
    // The old wording made all six equivalent.
    expect(chip).not.toHaveTextContent("6 not established");
  });

  it("says plainly when nothing unresolved there blocks a run", async () => {
    vi.mocked(api.resolutionPlan).mockResolvedValue(
      station(
        input({
          key: `stage.${stage}.cycle_time`,
          label: "Screwdriving — cycle time",
          stage_id: stage,
          value: 48,
          source: "ENGINEERING_ESTIMATE",
          resolved: true,
        }),
        other("purchase_cost", "Screwdriving — equipment cost", "COMMERCIAL_ONLY"),
      ),
    );
    renderPanel();

    const chip = await screen.findByTestId(`resolve-station-gaps-${stage}`);
    expect(chip).toHaveTextContent("1 unresolved, none needed to simulate");
    expect(screen.queryByTestId(`resolve-station-blocking-${stage}`)).toBeNull();
  });

  it("counts only what blocks, when everything unresolved does", async () => {
    vi.mocked(api.resolutionPlan).mockResolvedValue(
      station(blocker("cycle_time", "Screwdriving — cycle time")),
    );
    renderPanel();

    const chip = await screen.findByTestId(`resolve-station-gaps-${stage}`);
    expect(chip).toHaveTextContent("1 needed to simulate");
    expect(screen.queryByTestId(`resolve-station-other-${stage}`)).toBeNull();
  });

  it("makes the section heading count the same way", async () => {
    vi.mocked(api.resolutionPlan).mockResolvedValue(
      station(
        blocker("cycle_time", "Screwdriving — cycle time"),
        blocker("operators_required", "Screwdriving — operators"),
        other("purchase_cost", "Screwdriving — equipment cost", "COMMERCIAL_ONLY"),
      ),
    );
    renderPanel();

    expect(await screen.findByTestId("resolve-stations-count")).toHaveTextContent(
      "2 needed to simulate · 1 other unresolved",
    );
  });

  it("still says an estimated station is estimated, not unresolved", async () => {
    // Preserved: an estimate is a resolved value AND an open question. It
    // must not appear in either unresolved count.
    vi.mocked(api.resolutionPlan).mockResolvedValue(
      station(
        input({
          key: `stage.${stage}.cycle_time`,
          label: "Screwdriving — cycle time",
          stage_id: stage,
          value: 48,
          source: "ENGINEERING_ESTIMATE",
          detail: "35–55 s",
          resolved: true,
          estimate: {
            low: 35,
            working_value: 48,
            high: 55,
            unit: "s",
            confidence: "MEDIUM",
            method: "LOCAL_HEURISTIC",
            basis: "6 fastenings",
            model_name: null,
          } as EstimatedRange,
        }),
      ),
    );
    renderPanel();

    await screen.findByTestId(`resolve-station-${stage}`);
    expect(screen.queryByTestId(`resolve-station-gaps-${stage}`)).toBeNull();
    expect(screen.getByTestId(`resolve-row-stage.${stage}.cycle_time`)).toHaveTextContent("48");
  });
});

/** "Use demo value" fills a station from the Electronics Assembly Demo Dataset. */
describe("demo data is offered only where it belongs", () => {
  it("offers it inside the example project", async () => {
    renderPanel({ isExampleProject: true });
    await screen.findByTestId("resolve-inputs");
    expect(screen.queryAllByTestId(/^resolve-action-USE_EXAMPLE_DATA-/).length).toBeGreaterThan(0);
  });

  it("does not offer it in a real project", async () => {
    renderPanel({ isExampleProject: false });
    await screen.findByTestId("resolve-inputs");
    expect(screen.queryAllByTestId(/^resolve-action-USE_EXAMPLE_DATA-/)).toHaveLength(0);
  });

  it("still offers every legitimate way to resolve the value", async () => {
    // The point is not to remove the engineer's options — it is to remove
    // one that is only meaningful for a different product.
    renderPanel({ isExampleProject: false });
    await screen.findByTestId("resolve-inputs");
    expect(screen.queryAllByTestId(/^resolve-action-ENGINEER_INPUT-/).length).toBeGreaterThan(0);
    expect(screen.queryAllByTestId(/^resolve-action-LEAVE_UNKNOWN-/).length).toBeGreaterThan(0);
  });
});
