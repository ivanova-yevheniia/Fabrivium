import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithContext } from "../../test/testUtils";
import { IterationSwitchConfirm } from "./IterationSwitchConfirm";

describe("IterationSwitchConfirm", () => {
  it("renders nothing when there is no pending switch", () => {
    renderWithContext(<IterationSwitchConfirm />, { pendingIterationSelection: null });
    expect(screen.queryByTestId("discard-draft-confirm")).not.toBeInTheDocument();
  });

  it("warns explicitly when a stage switch is pending, rather than silently discarding", () => {
    renderWithContext(<IterationSwitchConfirm />, { pendingIterationSelection: "final" });
    expect(screen.getByTestId("discard-draft-confirm")).toHaveTextContent(/discard/i);
  });

  it("Discard & Switch calls confirmIterationSwitch", () => {
    const { contextValue } = renderWithContext(<IterationSwitchConfirm />, { pendingIterationSelection: 0 });
    fireEvent.click(screen.getByTestId("confirm-discard-button"));
    expect(contextValue.confirmIterationSwitch).toHaveBeenCalled();
  });

  it("Cancel calls cancelIterationSwitch", () => {
    const { contextValue } = renderWithContext(<IterationSwitchConfirm />, { pendingIterationSelection: 0 });
    fireEvent.click(screen.getByTestId("cancel-discard-button"));
    expect(contextValue.cancelIterationSwitch).toHaveBeenCalled();
  });
});
