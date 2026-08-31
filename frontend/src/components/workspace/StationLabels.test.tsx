import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FactoryWorkspace } from "./FactoryWorkspace";
import { SceneLegend } from "./SceneLegend";
import { sampleFactory } from "../../test/fixtures";
import type { Factory, FactoryLayout } from "../../api/types";
import type { TraceIndex } from "../../utils/traceIndex";

/** §14/§17 — what the floor plan and the animation are allowed to say. */

const layout: FactoryLayout = {
  factory_width: 20,
  factory_length: 10,
  placements: [
    { machine_id: "m-a", x: 3, y: 5, z: 0, rotation_deg: 0 },
    { machine_id: "m-b", x: 9, y: 5, z: 0, rotation_deg: 0 },
  ],
  zones: [],
} as unknown as FactoryLayout;

/** The real shape of a product-first line: process types repeat, so the
 * identifiers are m-assembly, m-assembly-2, … while the engineer's own
 * names are all different. */
const namedFactory: Factory = {
  ...sampleFactory,
  machines: [
    { ...sampleFactory.machines[0], id: "m-assembly", name: "PCB placement" },
    { ...sampleFactory.machines[1], id: "m-assembly-2", name: "Cable connection ×2" },
  ],
};

const namedLayout: FactoryLayout = {
  ...layout,
  placements: [
    { machine_id: "m-assembly", x: 3, y: 5, z: 0, rotation_deg: 0 },
    { machine_id: "m-assembly-2", x: 9, y: 5, z: 0, rotation_deg: 0 },
  ],
} as unknown as FactoryLayout;

function renderPlan(factory: Factory, l: FactoryLayout) {
  return render(
    <FactoryWorkspace
      factory={factory}
      layout={l}
      selectedMachineId={null}
      highlightedMachineIds={[]}
      isRejectedCandidate={false}
      bottleneckMachineId={null}
      onSelectMachine={vi.fn()}
    />,
  );
}

describe("§14 — the floor plan names the stations the engineer named", () => {
  it("shows the station's own name, not the identifier's prettified form", () => {
    renderPlan(namedFactory, namedLayout);

    // The defect: these read "Assembly" and "Assembly 2" — a database key
    // and a suffix, neither of which is a station anyone can find on a floor.
    expect(screen.getByTestId("workspace-label-m-assembly")).toHaveTextContent("PCB placement");
    expect(screen.getByTestId("workspace-label-m-assembly-2")).toHaveTextContent(
      "Cable connection ×2",
    );
  });

  it("keeps the FULL name reachable even where the plate has to shorten it", () => {
    const long: Factory = {
      ...namedFactory,
      machines: [
        { ...namedFactory.machines[0], name: "Automated PCB placement and pre-test cell" },
        namedFactory.machines[1],
      ],
    };
    renderPlan(long, namedLayout);

    const label = screen.getByTestId("workspace-label-m-assembly");
    // Shortened on screen...
    expect(label.textContent).toMatch(/…/);
    // ...and never lost: the <title> is what a hover and a screen reader get.
    expect(label.querySelector("title")?.textContent).toBe(
      "Automated PCB placement and pre-test cell",
    );
  });
});

describe("§17 — the animation legend", () => {
  const traceIndex = {} as TraceIndex;

  it("renders nothing when no animation is running", () => {
    // A legend for an animation that is not playing is decoration.
    const { container } = render(
      <SceneLegend factory={sampleFactory} traceIndex={null} limitingStageShown={false} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("pairs every colour with its word, so nothing is carried by colour alone", () => {
    render(<SceneLegend factory={sampleFactory} traceIndex={traceIndex} limitingStageShown />);
    expect(screen.getByTestId("scene-legend-processing")).toHaveTextContent("Processing");
    expect(screen.getByTestId("scene-legend-blocked")).toHaveTextContent("Blocked");
    expect(screen.getByTestId("scene-legend-limiting")).toHaveTextContent("Limiting stage");
  });

  it("omits a state this line cannot actually show", () => {
    // STARVED is only derivable for a machine with a wired inbound buffer.
    // sampleFactory has no buffers, so the scene never draws it.
    render(<SceneLegend factory={sampleFactory} traceIndex={traceIndex} limitingStageShown />);
    expect(screen.queryByTestId("scene-legend-waiting")).toBeNull();

    const wired: Factory = {
      ...sampleFactory,
      buffers: [
        {
          id: "buf-1",
          name: "A → B",
          capacity: 50,
          upstream_machine_id: "m-a",
          downstream_machine_id: "m-b",
          position_x: 6,
          position_y: 5,
        } as never,
      ],
    };
    render(<SceneLegend factory={wired} traceIndex={traceIndex} limitingStageShown />);
    expect(screen.getByTestId("scene-legend-waiting")).toHaveTextContent("Waiting for input");
  });

  it("omits the limiting stage when no halo is drawn for one", () => {
    render(
      <SceneLegend factory={sampleFactory} traceIndex={traceIndex} limitingStageShown={false} />,
    );
    expect(screen.queryByTestId("scene-legend-limiting")).toBeNull();
  });
});
