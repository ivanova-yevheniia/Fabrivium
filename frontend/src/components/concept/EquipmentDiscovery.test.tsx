import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { EquipmentDiscovery } from "./EquipmentDiscovery";
import {
  discoverEquipment,
  selectEquipment,
  type EquipmentDiscoveryResult,
  type EquipmentSelectResult,
  type PublishedSpec,
} from "../../api/equipment";
import type { FactoryConceptDraft } from "../../api/types";

/** Phase 16 — what the equipment screen is allowed to say. */

vi.mock("../../api/equipment", async () => {
  const actual = await vi.importActual<typeof import("../../api/equipment")>("../../api/equipment");
  return { ...actual, discoverEquipment: vi.fn(), selectEquipment: vi.fn() };
});

const discoverMock = vi.mocked(discoverEquipment);
const selectMock = vi.mocked(selectEquipment);

const draft = {
  name: "Concept",
  stages: [
    { id: "m-screwdriving", name: "Screwdriving" },
    { id: "m-assembly", name: "Assembly" },
  ],
} as unknown as FactoryConceptDraft;

function sourced(value: number | null, source = "EXAMPLE_DATA") {
  return { value, source, detail: "Electronics Assembly Demo Dataset" };
}

function spec(value: number | null, unit: string | null = null): PublishedSpec {
  return {
    value,
    unit,
    text: null,
    source_id: value == null ? null : "s1",
    // Mirrors the backend validator: an empty value is UNKNOWN whatever
    // else a record says about it.
    evidence: value == null ? "UNKNOWN" : "KNOWN_SPECIFICATION",
    basis: null,
  };
}

function result(overrides: Partial<EquipmentDiscoveryResult> = {}): EquipmentDiscoveryResult {
  return {
    requirement: {
      station_id: "m-screwdriving",
      station_name: "Screwdriving",
      process_category: "screwdriving",
      required_capability: "SCREW_FASTENING" as const,
      capability_statement:
        "Drive and control threaded fasteners into the product at this station's rate.",
      max_cycle_time_seconds: sourced(52),
      operations_per_unit: sourced(null, "UNKNOWN"),
      max_payload_kg: sourced(null, "UNKNOWN"),
      part_dimensions_text: null,
      part_dimensions_provenance: null,
      required_capacity: sourced(1),
      operator_requirement: sourced(2),
      max_width_m: sourced(2.5),
      max_length_m: sourced(2),
      max_height_m: sourced(null, "UNKNOWN"),
      budget_limit: sourced(85000),
      required_interfaces: [],
      optional_preferences: [],
      strategy_context: "Plan E",
      provenance: "Derived from the 'Screwdriving' stage of this concept.",
    },
    assessments: [
      {
        candidate: {
          candidate_id: "kolver-kds-nt120ca",
          manufacturer: "Kolver S.r.l.",
          model: "KDS-NT120CA",
          category: "Transducerised fixture-mount screwdriver",
          provides: ["SCREW_FASTENING" as const],
          catalog_id: "factorymind-researched",
          catalog_kind: "RESEARCHED_MANUFACTURER" as const,
          product_scope: "Screwdriver spindle — integrated into a station",
          description: "",
          cycle_time_seconds: spec(null),
          capacity: spec(null),
          operators_required: spec(null),
          width_mm: spec(27, "mm"),
          length_mm: spec(221, "mm"),
          height_mm: spec(null),
          weight_kg: spec(0.3, "kg"),
          torque_min_nm: spec(0.2, "Nm"),
          torque_max_nm: spec(1.2, "Nm"),
          speed_max_rpm: spec(430, "rpm"),
          interfaces: ["Modbus TCP", "Open Protocol"],
          price: spec(null),
          price_status: "QUOTE_REQUIRED",
          cad_available: null,
          cad_format: null,
          cad_url: null,
          documentation_url: "https://kolver.com/upl/EN_Catalog_CA.pdf",
          sources: [
            {
              source_id: "s1",
              url: "https://kolver.com/upl/EN_Catalog_CA.pdf",
              source_type: "MANUFACTURER_DATASHEET",
              title: "Kolver — Screwdrivers for Automation catalogue",
              retrieved_at: "2026-08-21",
            },
          ],
          caveats: ["The published 221 x 27 mm is the tool body, not a floor footprint."],
        },
        compatibility: {
          candidate_id: "kolver-kds-nt120ca",
          station_id: "m-screwdriving",
          checks: [
            {
              field: "cycle_time",
              label: "Cycle time",
              status: "UNKNOWN",
              requirement_text: "≤ 52 s",
              candidate_text: "Not published",
              reason: "No cycle time is published — it depends on the joint and screw count.",
            },
            {
              field: "footprint_length",
              label: "Footprint length",
              status: "PASS",
              requirement_text: "≤ 2 m",
              candidate_text: "221 mm",
              reason: "",
            },
          ],
        },
        claim: "CANDIDATE" as const,
        claim_text:
          "Candidate equipment — 1 requirement(s) matched, 1 could not be checked against published data.",
        pass_count: 1,
        fail_count: 0,
        unknown_count: 1,
        specs_published: 3,
        specs_considered: 8,
        evidence: {
          known_specification: 3,
          source_derived: 0,
          estimated: 0,
          unknown: 4,
          quote_required: 1,
        },
        catalog_id: "factorymind-researched",
        catalog_kind: "RESEARCHED_MANUFACTURER" as const,
      },
    ],
    capability: "SCREW_FASTENING" as const,
    capability_statement:
      "Drive and control threaded fasteners into the product at this station's rate.",
    catalogs: [
      {
        catalog_id: "factorymind-researched",
        kind: "RESEARCHED_MANUFACTURER" as const,
        display_name: "Fabrivium researched manufacturer data",
        trust_statement: "Every value was read out of the manufacturer document cited beside it.",
        available: true,
        unavailable_reason: "",
        candidate_count: 1,
        verified_on: "2026-08-21",
      },
      {
        catalog_id: "live-manufacturer-web",
        kind: "EXTERNAL_SOURCE" as const,
        display_name: "Live manufacturer web search",
        trust_statement: "Not connected in this build.",
        available: false,
        unavailable_reason: "Live manufacturer search is not connected in this build.",
        candidate_count: 0,
        verified_on: null,
      },
    ],
    freshness: "CACHED",
    verified_on: "2026-08-21",
    note: null,
    ...overrides,
  };
}

function selectResult(overrides: Partial<EquipmentSelectResult> = {}): EquipmentSelectResult {
  return {
    selection: {
      station_id: "m-screwdriving",
      candidate_id: "kolver-kds-nt120ca",
      manufacturer: "Kolver S.r.l.",
      model: "KDS-NT120CA",
      source_url: "https://kolver.com/upl/EN_Catalog_CA.pdf",
      selected_from: "CACHED",
      adopted_parameters: [],
    },
    proposed_changes: [],
    affects_simulation: false,
    ...overrides,
  };
}

/** The station is controlled by the parent in the app (ConceptVerified owns
 * the one station every Handoff panel reads), so a standalone render needs a
 * holder for it. This is the smallest possible stand-in for that owner. */
function Harness({ start, ...rest }: { start: string } & Record<string, unknown>) {
  const [stationId, setStationId] = useState(start);
  return (
    <EquipmentDiscovery
      draft={draft}
      stationId={stationId}
      onStationChange={setStationId}
      strategyContext="Plan E"
      {...rest}
    />
  );
}

async function find() {
  const user = userEvent.setup();
  render(<Harness start="m-screwdriving" />);
  await user.click(screen.getByTestId("concept-find-equipment"));
  return user;
}

beforeEach(() => {
  discoverMock.mockReset();
  selectMock.mockReset();
  discoverMock.mockResolvedValue(result());
  selectMock.mockResolvedValue(selectResult());
});

describe("station choice", () => {
  it("starts on the station it was given but lets the engineer change it", async () => {
    const user = userEvent.setup();
    render(<Harness start="m-assembly" />);

    const picker = screen.getByTestId("equipment-station-select") as HTMLSelectElement;
    // The optimiser's bottleneck is a useful default, not a constraint: an
    // engineer sources equipment for the station they are working on.
    expect(picker.value).toBe("m-assembly");

    await user.selectOptions(picker, "m-screwdriving");
    await user.click(screen.getByTestId("concept-find-equipment"));

    expect(discoverMock).toHaveBeenCalledWith(draft, "m-screwdriving", "Plan E");
  });
});

describe("requirements", () => {
  it("shows the requirement derived from the concept, not a typed-in one", async () => {
    await find();

    expect(discoverMock).toHaveBeenCalledWith(draft, "m-screwdriving", "Plan E");
    expect(await screen.findByTestId("equipment-required-cycle")).toHaveTextContent("≤ 52 s");
  });

  it("keeps the provenance of the bounds visible", async () => {
    await find();
    expect(await screen.findByTestId("equipment-requirement-provenance")).toHaveTextContent(/Screwdriving/);
    expect(within(screen.getByTestId("equipment-requirement")).getAllByTestId("source-example_data").length).toBeGreaterThan(0);
  });

  it("renders a bound the concept never established as a word, not a zero", async () => {
    discoverMock.mockResolvedValue(
      result({
        requirement: { ...result().requirement, budget_limit: sourced(null, "UNKNOWN") },
      }),
    );
    await find();

    const panel = await screen.findByTestId("equipment-requirement");
    expect(panel).toHaveTextContent(/Not established/);
    expect(panel).not.toHaveTextContent("€0");
  });
});

describe("candidate honesty", () => {
  it("labels manufacturer data as bundled, with the date it was read", async () => {
    await find();
    const badge = await screen.findByTestId("equipment-freshness");
    expect(badge).toHaveTextContent(/Bundled manufacturer data/);
    expect(badge).toHaveTextContent("2026-08-21");
    expect(badge).not.toHaveTextContent(/^Live/);
  });

  it("says Live only when the backend says live", async () => {
    discoverMock.mockResolvedValue(result({ freshness: "LIVE" }));
    await find();
    // The LIVE branch reads "Bundled catalogue": there is no live feed, and
    // a freshness badge claiming one would be a capability claim.
    expect(await screen.findByTestId("equipment-freshness")).toHaveTextContent("Bundled catalogue");
  });

  it("reports three counts rather than one score", async () => {
    await find();
    const counts = await screen.findByTestId("equipment-counts-kolver-kds-nt120ca");
    // The product's own words. "PASS" reads as approval of the machine;
    // "matched" says only that one stated bound was compared.
    expect(counts).toHaveTextContent("1 matched");
    expect(counts).toHaveTextContent("0 contradicted");
    expect(counts).toHaveTextContent("1 not verified");
    expect(counts).not.toHaveTextContent("%");
  });

  it("never renders a missing price as a number", async () => {
    await find();
    const price = await screen.findByTestId("equipment-price-kolver-kds-nt120ca");
    expect(price).toHaveTextContent("Quote required");
    expect(price).not.toHaveTextContent("€0");
    expect(price).not.toHaveTextContent("0");
  });

  it("shows an unpublished spec as not published rather than blank", async () => {
    await find();
    const card = await screen.findByTestId("equipment-card-kolver-kds-nt120ca");
    expect(card).toHaveTextContent(/Cycle time/);
    expect(card).toHaveTextContent(/Not published/);
  });

  it("exposes the source document and its retrieval date", async () => {
    await find();
    const link = await screen.findByTestId("equipment-source-kolver-kds-nt120ca");
    expect(link).toHaveAttribute("href", "https://kolver.com/upl/EN_Catalog_CA.pdf");
    expect(screen.getByTestId("equipment-card-kolver-kds-nt120ca")).toHaveTextContent("retrieved 2026-08-21");
  });

  it("carries the caveat that a spindle is not a whole station", async () => {
    await find();
    expect(await screen.findByTestId("equipment-caveats-kolver-kds-nt120ca")).toHaveTextContent(
      /not a floor footprint/i,
    );
  });

  it("explains why each verdict was reached", async () => {
    const user = await find();
    await user.click(await screen.findByText("Matched and unverified requirements"));
    const card = screen.getByTestId("equipment-card-kolver-kds-nt120ca");
    expect(card).toHaveTextContent(/depends on the joint and screw count/);
  });
});

describe("comparison", () => {
  it("compares candidates against the requirement side by side", async () => {
    const user = await find();
    await user.click(await screen.findByTestId("equipment-compare-toggle"));

    const table = screen.getByTestId("equipment-compare");
    expect(table).toHaveTextContent("Kolver S.r.l.");
    expect(table).toHaveTextContent("Cycle time");
    expect(table).toHaveTextContent("≤ 52 s");
  });
});

describe("selection", () => {
  it("records a choice without changing the concept's engineering values", async () => {
    const user = await find();
    await user.click(await screen.findByTestId("equipment-select-kolver-kds-nt120ca"));

    const selected = await screen.findByTestId("equipment-selected");
    expect(selected).toHaveTextContent("KDS-NT120CA");
    expect(selected).toHaveTextContent(/cycle time, capacity and operator count are unchanged/i);
    // No confirmation is needed when nothing published differs.
    expect(screen.queryByTestId("equipment-parameter-review")).toBeNull();
  });

  it("asks before replacing a planning value, naming both numbers", async () => {
    selectMock.mockResolvedValue(
      selectResult({
        affects_simulation: true,
        proposed_changes: [
          {
            field: "cycle_time",
            label: "Cycle time",
            current_value: 52,
            current_source: "EXAMPLE_DATA",
            proposed_value: 45,
            proposed_unit: "s",
            proposed_source_url: "https://kolver.com/upl/EN_Catalog_CA.pdf",
            affects_simulation: true,
          },
        ],
      }),
    );
    const user = await find();
    await user.click(await screen.findByTestId("equipment-select-kolver-kds-nt120ca"));

    const review = await screen.findByTestId("equipment-parameter-review");
    // Both numbers must be in the question; consent to a hidden magnitude
    // is not consent.
    expect(review).toHaveTextContent("52 s");
    expect(review).toHaveTextContent("45 s");
    expect(review).toHaveTextContent(/would need re-verifying/i);
    expect(review).toHaveTextContent(/Nothing has been changed/i);
  });

  it("keeps the concept's values when the engineer declines", async () => {
    selectMock.mockResolvedValue(
      selectResult({
        affects_simulation: true,
        proposed_changes: [
          {
            field: "cycle_time",
            label: "Cycle time",
            current_value: 52,
            current_source: "EXAMPLE_DATA",
            proposed_value: 45,
            proposed_unit: "s",
            proposed_source_url: null,
            affects_simulation: true,
          },
        ],
      }),
    );
    const user = await find();
    await user.click(await screen.findByTestId("equipment-select-kolver-kds-nt120ca"));
    await user.click(await screen.findByTestId("equipment-review-dismiss"));

    expect(screen.queryByTestId("equipment-parameter-review")).toBeNull();
    expect(screen.getByTestId("equipment-selected")).toBeInTheDocument();
  });
});

describe("failure", () => {
  it("reports a failed lookup instead of an empty shortlist", async () => {
    discoverMock.mockRejectedValue(new Error("Could not reach the Fabrivium backend. Is it running?"));
    await find();

    expect(await screen.findByTestId("equipment-error")).toHaveTextContent(/Could not reach/);
    expect(screen.queryByTestId("equipment-requirement")).toBeNull();
  });

  it("says plainly when a station has no researched dataset", async () => {
    discoverMock.mockResolvedValue(
      result({ assessments: [], note: "No researched equipment dataset exists for 'assembly'." }),
    );
    await find();

    expect(await screen.findByTestId("equipment-note")).toHaveTextContent(/No researched equipment dataset/);
    expect(screen.queryByTestId("equipment-compare-toggle")).toBeNull();
    // Nothing was retrieved, so there is no cache to date-stamp; claiming
    // "verified on an unrecorded date" would be noise dressed as provenance.
    expect(screen.queryByTestId("equipment-freshness")).toBeNull();
  });
});

/**
 * Breadth phase — what the screen must say once there is more than one
 * category and more than one kind of source.
 */
describe("capability", () => {
  it("leads with what the station must be able to do", async () => {
    await find();
    const capability = await screen.findByTestId("equipment-capability");
    expect(capability).toHaveTextContent("Required capability");
    expect(capability).toHaveTextContent("screw fastening");
    expect(capability).toHaveTextContent(/Drive and control threaded fasteners/);
  });

  it("shows no capability line for a station nothing was researched for", async () => {
    discoverMock.mockResolvedValue(
      result({
        assessments: [],
        capability: null,
        capability_statement: "",
        requirement: { ...result().requirement, required_capability: null, capability_statement: "" },
        note: "Fabrivium has no researched equipment capability for a 'assembly' station.",
      }),
    );
    await find();
    expect(await screen.findByTestId("equipment-note")).toBeInTheDocument();
    expect(screen.queryByTestId("equipment-capability")).toBeNull();
  });
});

describe("claims", () => {
  it("never calls a candidate compatible", async () => {
    await find();
    const claim = await screen.findByTestId("equipment-claim-kolver-kds-nt120ca");
    expect(claim).toHaveTextContent(/Candidate equipment/);
    // The screen has no path to a stronger word, and this is what stops one
    // being added by accident.
    expect(document.body.textContent).not.toMatch(/\bis compatible\b/i);
    expect(document.body.textContent).not.toMatch(/\bvalidated\b/i);
    expect(document.body.textContent).not.toMatch(/\bguaranteed\b/i);
  });

  it("separates the requirements that were matched from the ones that were not", async () => {
    const user = await find();
    await user.click(await screen.findByText("Matched and unverified requirements"));
    const card = screen.getByTestId("equipment-card-kolver-kds-nt120ca");
    expect(card).toHaveTextContent("Matched (1)");
    expect(card).toHaveTextContent("Not verified (1)");
    // The unverified row still carries the reason it could not be checked.
    expect(card).toHaveTextContent(/depends on the joint and screw count/);
  });
});

describe("sources", () => {
  it("names which catalogue each candidate came from", async () => {
    await find();
    expect(await screen.findByTestId("equipment-origin-kolver-kds-nt120ca")).toHaveTextContent(
      "Manufacturer data",
    );
  });

  it("distinguishes a value we derived from one the manufacturer published", async () => {
    await find();
    const origin = await screen.findByTestId("equipment-origin-kolver-kds-nt120ca");
    expect(origin).toHaveTextContent("3 from source documents");
    expect(origin).toHaveTextContent("1 quote required");
    expect(origin).toHaveTextContent("4 not published");
  });

  it("says when a source could not be consulted rather than hiding it", async () => {
    await find();
    const missing = await screen.findByTestId("equipment-catalog-unavailable-live-manufacturer-web");
    expect(missing).toHaveTextContent(/could not be consulted/);
    expect(missing).toHaveTextContent(/not connected in this build/);
  });

  it("counts what each answering catalogue contributed", async () => {
    await find();
    expect(await screen.findByTestId("equipment-catalogs")).toHaveTextContent(
      "Fabrivium researched manufacturer data (1)",
    );
  });
});

describe("layout", () => {
  it("the interfaces list gets the full spec-grid width", async () => {
    // Found by looking at the rendered panel: in a 120px auto-fit column a
    // six-protocol interface list wraps to a dozen lines and stretches the
    // whole row, with every other cell in it empty beside it. The class is
    // what the CSS grid-column rule hangs off, so it is worth pinning.
    await find();
    const card = await screen.findByTestId("equipment-card-kolver-kds-nt120ca");
    const interfaces = card.querySelector(".equipment-card__interfaces");
    expect(interfaces).not.toBeNull();
    expect(interfaces).toHaveTextContent("Modbus TCP");
  });
});
