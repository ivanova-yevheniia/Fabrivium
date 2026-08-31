import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FactoryConceptDraft } from "../../api/types";
import { sampleArena, sampleFactory, sampleStrategySessions, sampleSessionTwoIterations } from "../../test/fixtures";
import { renderWithContext } from "../../test/testUtils";
import { ConceptBuilder } from "./ConceptBuilder";
import { ConceptReady } from "./ConceptReady";
import { ConceptVerified } from "./ConceptVerified";
import { JourneyStrip } from "./JourneyStrip";
import { handoffToPlantSimulation, type PlantSimulationHandoffResult } from "../../api/handoff";

// The Siemens call is the backend's job; the component is responsible for
// what it does with the answer, which is what these tests exercise.
vi.mock("../../api/handoff", () => ({ handoffToPlantSimulation: vi.fn() }));
const handoffMock = vi.mocked(handoffToPlantSimulation);

/** Phase 14 — the competition journey. */

function sourced(value: number | null, source: FactoryConceptDraft["production_target"]["source"]) {
  return { value, source, detail: null };
}

function draft(overrides: Partial<FactoryConceptDraft> = {}): FactoryConceptDraft {
  return {
    name: "New factory concept",
    customer_brief: "We need 1,900 units per day through assembly and packaging.",
    production_target: sourced(1900, "CUSTOMER"),
    product_name: "Product",
    stages: [
      {
        id: "m-assembly",
        name: "Assembly",
        process_type: "assembly",
        cycle_time: sourced(35, "EXAMPLE_DATA"),
        capacity: sourced(1, "EXAMPLE_DATA"),
        operators_required: sourced(2, "EXAMPLE_DATA"),
        width: sourced(3, "EXAMPLE_DATA"),
        length: sourced(2, "EXAMPLE_DATA"),
        purchase_cost: sourced(null, "UNKNOWN"),
      },
    ],
    buffers: [],
    shifts_per_day: sourced(2, "EXAMPLE_DATA"),
    hours_per_shift: sourced(8, "EXAMPLE_DATA"),
    operators_available: sourced(8, "CUSTOMER"),
    floor_width: sourced(30, "CUSTOMER"),
    floor_length: sourced(18, "CUSTOMER"),
    budget: sourced(null, "UNKNOWN"),
    prefer_no_new_machines: true,
    ...overrides,
  };
}

const readyValidation = {
  simulation_ready: true,
  blocking_gaps: [],
  optional_gaps: [],
  errors: [],
};

const blockedValidation = {
  simulation_ready: false,
  blocking_gaps: [
    {
      key: "stage.m-assembly.cycle_time",
      label: "Assembly cycle time",
      severity: "REQUIRED" as const,
      reason: "Processing time per unit is the core physical property of a stage.",
      stage_id: "m-assembly",
    },
  ],
  optional_gaps: [
    {
      key: "budget",
      label: "Capital budget",
      severity: "OPTIONAL" as const,
      reason: "Commercial only.",
      stage_id: null,
    },
  ],
  errors: [],
};

// Journey position

describe("JourneyStrip", () => {
  it("shows nothing before a journey has started", () => {
    renderWithContext(<JourneyStrip />, { startMode: "CHOOSING" });
    expect(screen.queryByTestId("journey")).toBeNull();
  });

  it("shows nothing for the optimize-an-existing-factory entry", () => {
    // That path genuinely has no Brief/Concept steps, and inventing them
    // would describe a journey the user is not on.
    renderWithContext(<JourneyStrip />, { startMode: "FACTORY_LOADED", factory: sampleFactory });
    expect(screen.queryByTestId("journey")).toBeNull();
  });

  it("tracks the concept journey from Brief to Improve", () => {
    const base = { startMode: "CONCEPT_BUILDER" as const };

    const { unmount } = renderWithContext(<JourneyStrip />, base);
    expect(screen.getByTestId("journey-step-brief")).toHaveAttribute("aria-current", "step");
    unmount();

    const withDraft = renderWithContext(<JourneyStrip />, {
      ...base,
      concept: { draft: draft(), validation: readyValidation, generatedLayout: null, building: false, extracting: false, error: null },
    });
    expect(screen.getByTestId("journey-step-concept")).toHaveAttribute("aria-current", "step");
    withDraft.unmount();

    renderWithContext(<JourneyStrip />, {
      startMode: "FACTORY_LOADED",
      factory: sampleFactory,
      arena: sampleArena,
      concept: { draft: draft(), validation: readyValidation, generatedLayout: null, building: false, extracting: false, error: null },
    });
    expect(screen.getByTestId("journey-step-improve")).toHaveAttribute("aria-current", "step");
  });

  it("is a readout, not navigation — the steps are not buttons", () => {
    renderWithContext(<JourneyStrip />, { startMode: "CONCEPT_BUILDER" });
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });
});

// Dictation

describe("brief dictation", () => {
  const originalSpeech = (window as unknown as Record<string, unknown>).SpeechRecognition;

  afterEach(() => {
    (window as unknown as Record<string, unknown>).SpeechRecognition = originalSpeech;
    (window as unknown as Record<string, unknown>).webkitSpeechRecognition = undefined;
  });

  it("states plainly when the browser cannot dictate", () => {
    // jsdom implements no SpeechRecognition, which is the unsupported case.
    renderWithContext(<ConceptBuilder />, {
      startMode: "CONCEPT_BUILDER",
      concept: { draft: null, validation: null, generatedLayout: null, building: false, extracting: false, error: null },
    });

    expect(screen.getByTestId("concept-brief-mic-unsupported")).toHaveTextContent(/unavailable/i);
    expect(screen.queryByTestId("concept-brief-mic")).toBeNull();
    // Typing still works — dictation is never a dependency.
    expect(screen.getByTestId("concept-brief-input")).toBeEnabled();
  });

  describe("with a supported browser", () => {
    /** The last recognition object the hook constructed, so a test can drive
     * its callbacks the way the browser would. */
    let live: {
      onresult: ((event: unknown) => void) | null;
      onerror: ((event: unknown) => void) | null;
      onend: (() => void) | null;
      start: ReturnType<typeof vi.fn>;
      stop: ReturnType<typeof vi.fn>;
      abort: ReturnType<typeof vi.fn>;
    };

    beforeEach(() => {
      class SpeechRecognitionMock {
        lang = "";
        continuous = false;
        interimResults = false;
        onresult: ((event: unknown) => void) | null = null;
        onerror: ((event: unknown) => void) | null = null;
        onend: (() => void) | null = null;
        start = vi.fn();
        stop = vi.fn();
        abort = vi.fn();

        constructor() {
          live = this as never;
        }
      }
      (window as unknown as Record<string, unknown>).SpeechRecognition = SpeechRecognitionMock;
    });

    it("offers a microphone and does not open it until asked", () => {
      renderWithContext(<ConceptBuilder />, {
        startMode: "CONCEPT_BUILDER",
        concept: { draft: null, validation: null, generatedLayout: null, building: false, extracting: false, error: null },
      });

      expect(screen.getByTestId("concept-brief-mic")).toBeInTheDocument();
      // Nothing constructed or started on mount: the microphone is requested
      // by the click, never by arriving on the screen.
      expect(live).toBeUndefined();
    });

    it("starts listening only on an explicit press", async () => {
      const user = userEvent.setup();
      renderWithContext(<ConceptBuilder />, {
        startMode: "CONCEPT_BUILDER",
        concept: { draft: null, validation: null, generatedLayout: null, building: false, extracting: false, error: null },
      });

      await user.click(screen.getByTestId("concept-brief-mic"));
      expect(live.start).toHaveBeenCalledTimes(1);
      expect(screen.getByTestId("concept-brief-mic")).toHaveAttribute("aria-pressed", "true");
    });

    it("never auto-submits: a transcript lands in the editable field only", async () => {
      const user = userEvent.setup();
      const startConceptFromBrief = vi.fn(async () => {});
      renderWithContext(
        <ConceptBuilder />,
        {
          startMode: "CONCEPT_BUILDER",
          concept: { draft: null, validation: null, generatedLayout: null, building: false, extracting: false, error: null },
        },
        { startConceptFromBrief },
      );

      await user.click(screen.getByTestId("concept-brief-mic"));
      act(() => {
        live.onresult?.({
          resultIndex: 0,
          results: { length: 1, 0: { isFinal: true, length: 1, 0: { transcript: "We need 1900 units per day." } } },
        });
      });

      const field = screen.getByTestId("concept-brief-input") as HTMLTextAreaElement;
      expect(field.value).toContain("We need 1900 units per day.");
      // The decisive assertion: speech produced text, not a submission.
      expect(startConceptFromBrief).not.toHaveBeenCalled();
    });

    it("keeps text editable after dictation — typing wins", async () => {
      const user = userEvent.setup();
      renderWithContext(<ConceptBuilder />, {
        startMode: "CONCEPT_BUILDER",
        concept: { draft: null, validation: null, generatedLayout: null, building: false, extracting: false, error: null },
      });

      await user.click(screen.getByTestId("concept-brief-mic"));
      act(() => {
        live.onresult?.({
          resultIndex: 0,
          results: { length: 1, 0: { isFinal: true, length: 1, 0: { transcript: "Assembly and packaging." } } },
        });
      });

      const field = screen.getByTestId("concept-brief-input") as HTMLTextAreaElement;
      await user.type(field, " 900 units per day.");
      expect(field.value).toBe("Assembly and packaging. 900 units per day.");
    });

    it("explains a declined microphone without breaking the brief", () => {
      renderWithContext(<ConceptBuilder />, {
        startMode: "CONCEPT_BUILDER",
        concept: { draft: null, validation: null, generatedLayout: null, building: false, extracting: false, error: null },
      });

      screen.getByTestId("concept-brief-mic").click();
      act(() => {
        live.onerror?.({ error: "not-allowed" });
      });

      expect(screen.getByTestId("concept-brief-speech-message")).toHaveTextContent(/type or paste/i);
      expect(screen.getByTestId("concept-brief-input")).toBeEnabled();
    });
  });
});

// Gaps: summarised, disclosed on demand

describe("information gaps presentation", () => {
  const state = {
    startMode: "CONCEPT_BUILDER" as const,
    concept: {
      draft: draft({ stages: [{ ...draft().stages[0], cycle_time: sourced(null, "UNKNOWN") }] }),
      validation: blockedValidation,
      generatedLayout: null,
      building: false,
      extracting: false,
      error: null,
    },
  };

  it("leads with the decision, not with a list", () => {
    renderWithContext(<ConceptBuilder />, state);

    expect(screen.getByTestId("gap-required")).toHaveTextContent(
      /We can build the first concept, but 1 engineering input still needs confirmation/i,
    );
    // The item list is collapsed until asked for.
    expect(screen.queryByTestId("gap-required-list")).toBeNull();
  });

  it("discloses the individual inputs on request", async () => {
    const user = userEvent.setup();
    renderWithContext(<ConceptBuilder />, state);

    await user.click(screen.getByTestId("gap-required-toggle"));
    expect(screen.getByTestId("gap-required-list")).toHaveTextContent("Assembly cycle time");
  });

  it("keeps optional gaps clearly non-blocking", () => {
    renderWithContext(<ConceptBuilder />, state);
    expect(screen.getByTestId("gap-optional")).toHaveTextContent(/does not block simulation/i);
  });
});

// Concept ready — audit finding A1

describe("ConceptReady", () => {
  const state = {
    startMode: "FACTORY_LOADED" as const,
    factory: sampleFactory,
    concept: {
      draft: draft(),
      validation: readyValidation,
      generatedLayout: null,
      building: false,
      extracting: false,
      error: null,
    },
  };

  it("continues the story instead of asking for the goal again", () => {
    renderWithContext(<ConceptReady />, state);

    expect(screen.getByTestId("concept-ready")).toBeInTheDocument();
    expect(screen.getByTestId("concept-ready-target")).toHaveTextContent("1,900");
    // The regression this screen exists to prevent.
    expect(screen.queryByTestId("goal-input")).toBeNull();
  });

  it("labels the generated layout as concept level, and says placement does not change output", () => {
    renderWithContext(<ConceptReady />, state);

    const reveal = screen.getByTestId("concept-layout-reveal");
    expect(reveal).toHaveTextContent(/Concept layout/i);
    expect(reveal).toHaveTextContent(/not an optimised layout and not CAD/i);
    expect(reveal).toHaveTextContent(/moving a station changes validity, never output/i);
  });

  it("verifies using the target already captured, not a retyped one", async () => {
    const user = userEvent.setup();
    const exploreOptions = vi.fn(async (_request: string) => {});
    renderWithContext(<ConceptReady />, state, { exploreOptions });

    await user.click(screen.getByTestId("concept-verify"));
    expect(exploreOptions).toHaveBeenCalledWith(expect.stringContaining("1900"));
    // The stated preference travels with it, so the verification asks the
    // same question the customer actually asked.
    expect(exploreOptions.mock.calls[0][0]).toContain("Avoid buying new machines");
  });

  it("states what is still open at concept stage", () => {
    renderWithContext(<ConceptReady />, state);
    expect(screen.getByTestId("concept-ready-open-items")).toHaveTextContent(/equipment is not selected/i);
  });
});

// Concept verified / handoff

describe("ConceptVerified", () => {
  const state = {
    startMode: "FACTORY_LOADED" as const,
    factory: sampleFactory,
    arena: sampleArena,
    strategySessions: sampleStrategySessions,
    session: sampleSessionTwoIterations,
    selectedStrategyId: sampleArena.recommended_strategy_id,
    concept: {
      draft: draft(),
      validation: readyValidation,
      generatedLayout: null,
      building: false,
      extracting: false,
      error: null,
    },
  };

  it("states that equipment is not selected", () => {
    renderWithContext(<ConceptVerified />, state);
    expect(screen.getByTestId("concept-verified-equipment")).toHaveTextContent(/no specific machine selected/i);
  });

  it("reports the real number of commercially incomplete options", () => {
    renderWithContext(<ConceptVerified />, state);
    const incomplete = sampleArena.strategies.filter((s) => !s.commercially_complete).length;
    expect(screen.getByTestId("concept-verified-cost")).toHaveTextContent(
      `${incomplete} of ${sampleArena.strategies.length}`,
    );
  });

  it("describes the handoff contents and offers the one verified export", async () => {
    const user = userEvent.setup();
    renderWithContext(<ConceptVerified />, state);

    await user.click(screen.getByTestId("concept-handoff-toggle"));
    const panel = screen.getByTestId("concept-handoff");
    expect(panel).toHaveTextContent(/Process graph/i);
    // Phase 14 refused to offer an export because no receiving tool had been
    // validated. Phase 15B validated one, so the button exists now — and the
    // panel still states what the model does NOT carry rather than letting
    // "handoff" imply the proposed equipment went with it.
    expect(screen.getByTestId("handoff-plant-simulation")).toBeEnabled();
    // §21 — WHAT IS BEING EXPORTED, ABOVE THE BUTTON.
    // The panel sits under a recommended plan, so "Transfer to Siemens Plant
    // Simulation" reads as transferring the plan. It transfers the baseline
    // concept. That was previously stated only after the export had run, and
    // in a note below the button — both after the decision it informs.
    expect(screen.getByTestId("handoff-target-scope")).toHaveTextContent(
      // The exporter's own words, so the two statements about the same file
      // cannot describe it differently.
      /Baseline engineering concept/i,
    );
    expect(screen.getByTestId("handoff-target")).toHaveTextContent(/not Plan B/i);
    // And the equipment boundary is part of the retained list, not only the
    // result panel's exclusions.
    expect(screen.getByTestId("handoff-contents-retained")).toHaveTextContent(
      // Reworded for the competition pass: the boundary is now stated as
      // metadata-vs-instantiation rather than as "selected equipment", which
      // model". What is pinned is the CLAIM, not the old phrasing.
      /supplier equipment geometry/i,
    );
    expect(screen.getByTestId("handoff-contents-retained")).toHaveTextContent(
      /no supplier cad is instantiated/i,
    );
  });

  it("offers equipment discovery for the concept's own bottleneck station", async () => {
    const user = userEvent.setup();
    renderWithContext(<ConceptVerified />, state);

    await user.click(screen.getByTestId("concept-handoff-toggle"));

    // Phase 14 showed this disabled, because a search that returned nothing
    // real would have undone the credibility of everything above it.
    // Phase 16 researched one process category, so the step is live — and
    // it targets the station the verified plan identified rather than a
    // hard-coded id.
    expect(screen.getByTestId("concept-find-equipment")).toBeEnabled();
    expect(screen.getByTestId("equipment-discovery")).toHaveTextContent(
      /asks every bundled catalogue which records declare that capability/i,
    );
  });

  // Phase 15C — the transfer into Plant Simulation.
  //
  // The adapter's own contract is pinned in the backend suite. What matters
  // here is that the SCREEN cannot say something the backend did not: no
  // success before a response, no success on a partial model, and the three
  // outcomes kept distinct because they need different actions from the
  // engineer.
  async function openHandoff() {
    const user = userEvent.setup();
    renderWithContext(<ConceptVerified />, state);
    await user.click(screen.getByTestId("concept-handoff-toggle"));
    return user;
  }

  function handoffResponse(overrides: Partial<PlantSimulationHandoffResult> = {}): PlantSimulationHandoffResult {
    return {
      status: "COMPLETE",
      // A project-scoped path, not Temp: the export directory is where the
      // deliverable lives now, and the default fixture should look like the
      // thing it stands for.
      model_path: "C:/work/factorymind/exports/siemens/concept.spp",
      model_bytes: 3_751_936,
      export_directory: "C:/work/factorymind/exports/siemens",
      saved_model_verified: true,
      saved_stations_verified: 4,
      saved_connections_verified: 5,
      // The four verdicts the panel renders. A fixture that omitted them
      // would let the panel be tested against a shape the backend never
      // sends.
      verification: [
        { tier: "STRUCTURE", status: "VERIFIED", detail: "4/4 stations" },
        { tier: "LAYOUT", status: "VERIFIED", detail: "9/9 objects placed" },
        { tier: "FLOW", status: "VERIFIED", detail: "8/8 connections" },
        { tier: "RUNTIME", status: "VERIFIED", detail: "3 unit(s) reached the drain" },
      ],
      export_scope: "BASELINE_CONCEPT",
      export_scope_label: "Baseline engineering concept",
      export_excludes: ["The shared operator pool."],
      manifest_path: "C:/work/factorymind/exports/siemens/concept.manifest.md",
      product_version: "Plant Simulation 2404",
      language: "de",
      stations_created: 4,
      stations_verified: 4,
      connections_created: 5,
      connections_verified: 5,
      cycle_times_verified: 4,
      // Phase 15D — a handoff is only green when the model is GEOMETRICALLY
      // usable, so the default fixture describes a model that is: every
      // object where it was put, nothing overlapping, the route walked end
      // to end, and a unit actually delivered to the drain.
      layout_mode: "normalised-concept",
      layout_reason: null,
      positions_verified: 6,
      positions_checked: 6,
      layout_min_separation: 90,
      overlaps: [],
      route_complete: true,
      route_walked: ["Source", "Assembly_Station", "Screwdriving_Station", "Drain"],
      disconnected: [],
      traversal_units: 3,
      traversal_verified: true,
      equipment_verified: 0,
      equipment_transferred: 0,
      simulated_units: null,
      simulated_seconds: null,
      station_utilisation: {},
      warnings: [],
      errors: [],
      ...overrides,
    };
  }

  it("sends the factory in session rather than a rebuilt demo payload", async () => {
    handoffMock.mockResolvedValue(handoffResponse());
    const user = await openHandoff();

    await user.click(screen.getByTestId("handoff-plant-simulation"));

    expect(handoffMock).toHaveBeenCalledTimes(1);
    const sent = handoffMock.mock.calls[0][0];
    // Identity, not deep equality: a reconstructed lookalike would pass a
    // value comparison and would still be the wrong factory.
    expect(sent.factory).toBe(sampleFactory);
  });

  it("reports only what read-back verified", async () => {
    handoffMock.mockResolvedValue(handoffResponse());
    const user = await openHandoff();

    await user.click(screen.getByTestId("handoff-plant-simulation"));

    const done = await screen.findByTestId("handoff-complete");
    expect(done).toHaveTextContent(/4 of 4/);
    expect(done).toHaveTextContent(/5 of 5/);
    expect(screen.getByTestId("handoff-model-path")).toHaveTextContent(/\.spp/);
    // The file line carries evidence — a measured size — not the adjective
    // "saved" on its own.
    expect(screen.getByTestId("handoff-model-path")).toHaveTextContent(/3\.8 MB on disk/);
    expect(screen.getByTestId("handoff-roundtrip")).toHaveTextContent(/re-opened and read back/i);
  });

  it("only claims to transfer what the adapter actually writes", async () => {
    // §14. The adapter writes station names, cycle times, capacities,
    // positions, the flow chain AND the buffers between stations — and
    // nothing else reaches Plant Simulation. Operator demand, the shared
    // workforce pool, shifts and provenance stay in the concept, and the
    // screen has to say which is which.
    //
    // Buffers changed sides when the cross-simulator work made them real:
    // they are created as MaterialFlow buffers, wired between their two
    // stations and read back out of the reopened model. Listing them as
    // retained-only understated the handoff on the point that matters most —
    // a generated line WITHOUT them is a zero-buffer blocking line, measured
    // at 1,413 units/day against the same line's 2,462.
    await openHandoff();

    const transferred = screen.getByTestId("handoff-contents-transferred");
    expect(transferred).toHaveTextContent(/cycle time and capacity/i);
    expect(transferred).toHaveTextContent(/flow connections/i);
    expect(transferred).toHaveTextContent(/buffers/i);
    expect(transferred).not.toHaveTextContent(/operator demand/i);
    expect(transferred).not.toHaveTextContent(/shifts/i);

    const retained = screen.getByTestId("handoff-contents-retained");
    expect(retained).toHaveTextContent(/operator demand/i);
    // The workforce boundary is the one the competition claim rests on, so
    // the screen has to carry it, not just a report.
    expect(retained).toHaveTextContent(/workforce pool/i);
    expect(retained).toHaveTextContent(/shifts/i);
    expect(retained).not.toHaveTextContent(/buffers/i);
  });

  it("says outright when no file was written", async () => {
    // A build can verify in-session and still leave nothing on disk. A
    // success panel that simply omits the file line would read as though
    // one exists, so the absence is stated.
    handoffMock.mockResolvedValue(
      handoffResponse({
        model_path: null,
        model_bytes: null,
        export_directory: null,
        saved_model_verified: null,
        saved_stations_verified: null,
        saved_connections_verified: null,
      }),
    );
    const user = await openHandoff();

    await user.click(screen.getByTestId("handoff-plant-simulation"));

    await screen.findByTestId("handoff-complete");
    expect(screen.queryByTestId("handoff-model-path")).toBeNull();
    expect(screen.getByTestId("handoff-no-file")).toHaveTextContent(/no file was written/i);
    // An unattempted round trip must never be dressed up as a passed one.
    expect(screen.queryByTestId("handoff-roundtrip")).toBeNull();
  });

  it("never shows success while the transfer is still running", async () => {
    let release: (value: PlantSimulationHandoffResult) => void = () => {};
    handoffMock.mockReturnValue(new Promise<PlantSimulationHandoffResult>((resolve) => (release = resolve)));
    const user = await openHandoff();

    await user.click(screen.getByTestId("handoff-plant-simulation"));

    expect(screen.getByTestId("handoff-busy")).toBeInTheDocument();
    expect(screen.getByTestId("handoff-plant-simulation")).toBeDisabled();
    expect(screen.queryByTestId("handoff-complete")).toBeNull();

    await act(async () => {
      release(handoffResponse());
    });
    expect(await screen.findByTestId("handoff-complete")).toBeInTheDocument();
  });

  it("calls a partial model INCOMPLETE and names which half failed", async () => {
    handoffMock.mockResolvedValue(
      handoffResponse({
        status: "INCOMPLETE",
        connections_verified: 0,
        errors: ["Ungültiger Bezeichner: Assembly Station"],
      }),
    );
    const user = await openHandoff();

    await user.click(screen.getByTestId("handoff-plant-simulation"));

    const failed = await screen.findByTestId("handoff-incomplete");
    expect(failed).toHaveTextContent(/Handoff not yet complete/i);
    expect(failed).toHaveTextContent(/0 of 5/);
    // The product's own message survives to the screen; a generic
    // "transfer failed" would leave the engineer with nothing to act on.
    expect(screen.getByTestId("handoff-error")).toHaveTextContent(/Ungültiger Bezeichner/);
    expect(screen.queryByTestId("handoff-complete")).toBeNull();
  });

  // Phase 15D — the success state must be about a USABLE model.
  //
  // The old green panel said "contents read back and matched" for a model
  // whose six stations sat on one point: Fabrivium was sending floor
  // coordinates in metres into a frame that measures objects in 41-unit
  // icons and silently clamps anything under 20. Counts of things cannot
  // see that. Where those things are can.

  it("shows geometry, route and traversal evidence in the success state", async () => {
    handoffMock.mockResolvedValue(handoffResponse());
    const user = await openHandoff();

    await user.click(screen.getByTestId("handoff-plant-simulation"));
    await screen.findByTestId("handoff-complete");

    expect(screen.getByTestId("handoff-spacing")).toHaveTextContent(/No two objects overlap/i);
    expect(screen.getByTestId("handoff-spacing")).toHaveTextContent(/90 frame units/);
    expect(screen.getByTestId("handoff-route")).toHaveTextContent(/Source → Assembly_Station/);
    expect(screen.getByTestId("handoff-traversal")).toHaveTextContent(/3 unit\(s\) reached the drain/i);
    // The claim is about a line that runs, not about contents that match.
    expect(screen.getByTestId("handoff-complete")).toHaveTextContent(
      /laid out, connected end to end, and traversed/i,
    );
  });

  it("never shows the success state for a model whose stations overlap", async () => {
    // The exact defect: every count green, every object on one point.
    handoffMock.mockResolvedValue(
      handoffResponse({
        status: "INCOMPLETE",
        positions_verified: 2,
        positions_checked: 13,
        layout_min_separation: 0,
        overlaps: ["Source and Assembly_Station are 0 units apart, inside the 41-unit icon"],
        traversal_units: 0,
        traversal_verified: false,
        errors: [
          "8 pair(s) of objects overlap in the Plant Simulation frame, so the model would open as a pile rather than as a line.",
        ],
      }),
    );
    const user = await openHandoff();

    await user.click(screen.getByTestId("handoff-plant-simulation"));

    const failed = await screen.findByTestId("handoff-incomplete");
    expect(failed).toHaveTextContent(/2 of 13/);
    expect(screen.getByTestId("handoff-spacing")).toHaveTextContent(/overlap/i);
    expect(screen.getByTestId("handoff-error")).toHaveTextContent(/open as a pile/i);
    expect(screen.queryByTestId("handoff-complete")).toBeNull();
  });

  it("says so when the concept arrangement could not be transferred as drawn", async () => {
    handoffMock.mockResolvedValue(
      handoffResponse({
        layout_mode: "generated-line",
        layout_reason: "two stations share the same conceptual coordinate",
        warnings: [
          "The concept arrangement could not be transferred as drawn, so Plant Simulation received a generated engineering line instead — two stations share the same conceptual coordinate.",
        ],
      }),
    );
    const user = await openHandoff();

    await user.click(screen.getByTestId("handoff-plant-simulation"));
    await screen.findByTestId("handoff-complete");

    expect(screen.getByTestId("handoff-layout-mode")).toHaveTextContent(
      /generated engineering line, not the concept layout as drawn/i,
    );
    expect(screen.getByTestId("handoff-warning")).toHaveTextContent(/could not be transferred as drawn/i);
  });

  it("reports carried equipment as metadata that changed no verified value", async () => {
    handoffMock.mockResolvedValue(
      handoffResponse({ equipment_transferred: 1, equipment_verified: 1 }),
    );
    const user = await openHandoff();

    await user.click(screen.getByTestId("handoff-plant-simulation"));
    await screen.findByTestId("handoff-complete");

    const line = screen.getByTestId("handoff-equipment");
    expect(line).toHaveTextContent(/1 of 1 station/i);
    expect(line).toHaveTextContent(/no manufacturer figure was written into them/i);
  });

  it("distinguishes Plant Simulation being absent from a failed handoff", async () => {
    handoffMock.mockResolvedValue(
      handoffResponse({ status: "UNAVAILABLE", model_path: null, stations_created: 0, stations_verified: 0 }),
    );
    const user = await openHandoff();

    await user.click(screen.getByTestId("handoff-plant-simulation"));

    const unavailable = await screen.findByTestId("handoff-unavailable");
    expect(unavailable).toHaveTextContent(/not reachable/i);
    expect(unavailable).toHaveTextContent(/concept itself is unaffected/i);
    expect(screen.queryByTestId("handoff-incomplete")).toBeNull();
  });

  it("reports a failed request separately from a failed handoff", async () => {
    handoffMock.mockRejectedValue(new Error("Could not reach the Fabrivium backend. Is it running?"));
    const user = await openHandoff();

    await user.click(screen.getByTestId("handoff-plant-simulation"));

    expect(await screen.findByTestId("handoff-request-error")).toHaveTextContent(/Could not reach/i);
    expect(screen.queryByTestId("handoff-complete")).toBeNull();
  });

  it("renders nothing without a concept — an optimized existing factory has no concept stage", () => {
    renderWithContext(<ConceptVerified />, {
      ...state,
      concept: { draft: null, validation: null, generatedLayout: null, building: false, extracting: false, error: null },
    });
    expect(screen.queryByTestId("concept-verified")).toBeNull();
  });
});
