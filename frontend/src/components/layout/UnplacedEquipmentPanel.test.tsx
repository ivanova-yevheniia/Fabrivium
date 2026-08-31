import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { sampleFactory } from "../../test/fixtures";
import { renderWithContext } from "../../test/testUtils";
import { UnplacedEquipmentPanel } from "./UnplacedEquipmentPanel";

const proxyFactory = {
  ...sampleFactory,
  machines: [
    ...sampleFactory.machines,
    {
      id: "m-c", name: "Candidate Station", process_type: "labeling", cycle_time: 10, setup_time: 0, capacity: 1,
      operators_required: 0, purchase_cost: 10_000, position_x: 0, position_y: 0, width: 1, length: 1,
      lifecycle_status: "PURCHASE_CANDIDATE" as const,
      asset: { asset_type: "PROXY" as const, status: "AVAILABLE" as const, asset_uri: null, source_uri: null, manufacturer: null, model_number: null, license_name: null, attribution: null, file_format: null, notes: null },
      physical_envelope: null,
    },
  ],
};

const draftWithOnlyAPlaced = {
  factory_width: 20, factory_length: 10,
  placements: [{ machine_id: "m-a", x: 5, y: 5, z: 0, rotation_deg: 0 }],
  reserved_zones: [], aisle_zones: [],
};

describe("UnplacedEquipmentPanel", () => {
  it("renders nothing outside EDIT_LAYOUT mode", () => {
    renderWithContext(<UnplacedEquipmentPanel />, { editMode: "VIEW", factory: proxyFactory });
    expect(screen.queryByTestId("unplaced-equipment-panel")).not.toBeInTheDocument();
  });

  it("lists every machine without a placement", () => {
    renderWithContext(<UnplacedEquipmentPanel />, { editMode: "EDIT_LAYOUT", factory: proxyFactory, draftLayout: draftWithOnlyAPlaced });
    expect(screen.getByTestId("unplaced-m-b")).toBeInTheDocument();
    expect(screen.getByTestId("unplaced-m-c")).toBeInTheDocument();
    expect(screen.queryByTestId("unplaced-m-a")).not.toBeInTheDocument();
  });

  it("shows a PROXY badge for a purchase-candidate proxy machine", () => {
    renderWithContext(<UnplacedEquipmentPanel />, { editMode: "EDIT_LAYOUT", factory: proxyFactory, draftLayout: draftWithOnlyAPlaced });
    expect(screen.getByTestId("unplaced-m-c")).toHaveTextContent("PROXY");
  });

  it("clicking Place on floor calls placeMachine with a default position", () => {
    const { contextValue } = renderWithContext(<UnplacedEquipmentPanel />, { editMode: "EDIT_LAYOUT", factory: proxyFactory, draftLayout: draftWithOnlyAPlaced });
    fireEvent.click(screen.getByTestId("place-m-c"));
    expect(contextValue.placeMachine).toHaveBeenCalledWith("m-c", proxyFactory.width / 2, proxyFactory.length / 2);
  });

  it("renders nothing once every machine is placed", () => {
    const fullDraft = { ...draftWithOnlyAPlaced, placements: [...draftWithOnlyAPlaced.placements, { machine_id: "m-b", x: 8, y: 5, z: 0, rotation_deg: 0 }, { machine_id: "m-c", x: 10, y: 5, z: 0, rotation_deg: 0 }] };
    renderWithContext(<UnplacedEquipmentPanel />, { editMode: "EDIT_LAYOUT", factory: proxyFactory, draftLayout: fullDraft });
    expect(screen.queryByTestId("unplaced-equipment-panel")).not.toBeInTheDocument();
  });
});
