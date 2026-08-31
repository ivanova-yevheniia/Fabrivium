import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import * as THREE from "three";
import type { Factory, FactoryLayout, Machine } from "../../api/types";
import { sampleFactory } from "../../test/fixtures";
import { FactoryWorkspace } from "./FactoryWorkspace";
import { AssetProvenanceLegend } from "./AssetProvenanceLegend";
import { CONGESTION_COLORS, STATION_ACCENTS } from "./FlowScene3D";
import { categoryForProcessType } from "../../utils/assetResolution";
import type { MachineCategory } from "../../utils/assetResolution";

/** Phase 10 — Executive View drops engineering chrome, WITHOUT dropping any disclosure. */

vi.mock("@react-three/drei", () => ({
  Html: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  useGLTF: () => ({ scene: new THREE.Group() }),
  OrbitControls: () => null,
  PerspectiveCamera: () => null,
  Grid: () => null,
}));

/** A machine whose process_type matches the generic asset pack, so it
 * resolves to GENERIC and would carry a per-machine badge. */
function genericMachine(id: string, processType: string): Machine {
  return {
    id, name: id, process_type: processType, cycle_time: 10, setup_time: 0,
    capacity: 1, operators_required: 2, purchase_cost: 0,
    position_x: 5, position_y: 5, width: 2, length: 2,
    parallel_of_machine_id: null, asset: null,
    lifecycle_status: "EXISTING", physical_envelope: null,
  } as Machine;
}

const factory = {
  ...sampleFactory,
  machines: [genericMachine("m-assembly", "assembly"), genericMachine("m-packaging", "packaging")],
} as Factory;

const layout = {
  factory_width: 50,
  factory_length: 20,
  placements: [
    { machine_id: "m-assembly", x: 5, y: 5, rotation_deg: 0 },
    { machine_id: "m-packaging", x: 15, y: 5, rotation_deg: 0 },
  ],
  aisle_zones: [{ id: "z-1", name: "Main Aisle", zone_type: "AISLE", x: 0, y: 10, width: 40, length: 2, rotation_deg: 0 }],
  reserved_zones: [],
} as unknown as FactoryLayout;

function renderWorkspace(presentation: "EXECUTIVE" | "ENGINEERING") {
  return render(
    <FactoryWorkspace
      factory={factory}
      layout={layout}
      selectedMachineId={null}
      highlightedMachineIds={[]}
      isRejectedCandidate={false}
      bottleneckMachineId={null}
      onSelectMachine={() => {}}
      presentation={presentation}
    />,
  );
}

describe("Phase 10 — Engineering View keeps every engineering label", () => {
  it("tags each GENERIC machine individually", () => {
    const { container } = renderWorkspace("ENGINEERING");
    expect(container.textContent).toContain("GENERIC");
  });

  it("prefixes a zone with its type", () => {
    const { container } = renderWorkspace("ENGINEERING");
    expect(container.textContent).toContain("AISLE: Main Aisle");
  });
});

describe("Phase 10 — Executive View drops the chrome", () => {
  it("does not stamp GENERIC on every machine", () => {
    const { container } = renderWorkspace("EXECUTIVE");
    expect(container.textContent).not.toContain("GENERIC");
  });

  it("still names the zone — only the type prefix goes", () => {
    const { container } = renderWorkspace("EXECUTIVE");
    expect(container.textContent).toContain("Main Aisle");
    expect(container.textContent).not.toContain("AISLE: Main Aisle");
  });

  it("still draws every machine — this is a label change, not a filter", () => {
    renderWorkspace("EXECUTIVE");
    expect(screen.getByTestId("workspace-node-m-assembly")).toBeInTheDocument();
    expect(screen.getByTestId("workspace-node-m-packaging")).toBeInTheDocument();
  });

  it("defaults to ENGINEERING when no presentation is given", () => {
    const { container } = render(
      <FactoryWorkspace
        factory={factory} layout={layout} selectedMachineId={null}
        highlightedMachineIds={[]} isRejectedCandidate={false}
        bottleneckMachineId={null} onSelectMachine={() => {}}
      />,
    );
    expect(container.textContent).toContain("GENERIC");
  });
});

describe("Phase 10 — the scene-level provenance legend carries the disclosure", () => {
  it("says these models are stand-ins, and that no equipment has been chosen", () => {
    render(<AssetProvenanceLegend factory={factory} />);
    const legend = screen.getByTestId("asset-provenance-legend");

    // What the shapes are...
    expect(legend).toHaveTextContent(/generic station models/i);
    // ...and the thing silence would be read as having answered.
    expect(legend).toHaveTextContent(/exact supplier equipment has not been selected/i);
  });

  it("names the mix when the scene is not all one kind of model", () => {
    // One machine with its own CAD alongside a generic one: the plaque must
    // not flatten that into "generic station models", which would be false
    // of the machine that has real geometry.
    const mixed = {
      ...factory,
      machines: [
        ...factory.machines,
        { ...genericMachine("m-laser", "laser welding"), asset: null },
      ],
    } as Factory;
    render(<AssetProvenanceLegend factory={mixed} />);

    const mix = screen.getByTestId("asset-provenance-mix");
    expect(mix).toHaveTextContent(/2 of 3/);
    expect(mix).toHaveTextContent(/1 of 3/);
  });

  it("credits the asset pack and its licence — GENERIC / Kenney Factory Kit / CC0", () => {
    render(<AssetProvenanceLegend factory={factory} />);
    const credit = screen.getByTestId("asset-provenance-credit");
    expect(credit).toHaveTextContent(/Kenney Factory Kit/i);
    expect(credit).toHaveTextContent("CC0");
  });

  it("credits a shared pack ONCE, however many machines use it", () => {
    render(<AssetProvenanceLegend factory={factory} />);
    expect(screen.getAllByTestId("asset-provenance-credit")).toHaveLength(1);
  });

  it("reports machines with no model as placeholders rather than silently omitting them", () => {
    const withUnknown = {
      ...factory,
      machines: [...factory.machines, genericMachine("m-laser", "laser welding")],
    } as Factory;
    render(<AssetProvenanceLegend factory={withUnknown} />);

    // Counted, not asserted: a machine the resolver found no model for is
    // named as a footprint placeholder rather than quietly folded in with
    // the ones that do have geometry.
    expect(screen.getByTestId("asset-provenance-mix")).toHaveTextContent(
      /1 of 3 footprint placeholders/i,
    );
  });

  it("renders nothing without a factory, rather than an empty box", () => {
    const { container } = render(<AssetProvenanceLegend factory={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("Phase 10 — station accents actually differentiate", () => {
  it("gives every station category its own colour", () => {
    // The four flagship categories must be mutually distinguishable, or the
    // tinting that makes Assembly readable as different from Packaging is
    // silently pointless. A duplicated or missing accent is invisible in a
    // screenshot review and obvious here.
    const flagship: MachineCategory[] = [
      "ASSEMBLY_STATION", "SCREWDRIVING_STATION", "INSPECTION_STATION", "PACKAGING_STATION",
    ];
    const colors = flagship.map((c) => STATION_ACCENTS[c]);

    expect(new Set(colors).size).toBe(flagship.length);
    for (const color of colors) expect(color).toMatch(/^#[0-9a-f]{6}$/i);
  });

  it("covers every category the resolver can return, including the catch-all", () => {
    // categoryForProcessType falls back to GENERIC_PROCESSING_MACHINE, so an
    // unrecognised machine must still get a colour rather than `undefined`,
    // which three.js would reject at render time.
    expect(STATION_ACCENTS[categoryForProcessType("laser welding")]).toBeTruthy();
    expect(STATION_ACCENTS.GENERIC_PROCESSING_MACHINE).toMatch(/^#[0-9a-f]{6}$/i);
  });

  it("keeps congestion colours distinct from each other", () => {
    // Queue and buffer severity must be readable at a glance and must not
    // collide with one another.
    const bands = [CONGESTION_COLORS.clear, CONGESTION_COLORS.building, CONGESTION_COLORS.congested];
    expect(new Set(bands).size).toBe(3);
  });
});
