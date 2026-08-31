import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Overlay } from "./Overlay";

/** §8 — THE OVERLAY LAYER CONTRACT. */

function Trapped({ onClose = () => {} }: { onClose?: () => void }) {
  // Reproduces the exact ancestor that caused the bug.
  return (
    <div style={{ transform: "translateZ(0)" }} data-testid="transformed-ancestor">
      <Overlay onClose={onClose} label="Test dialog" testId="test-dialog">
        <p>dialog body</p>
        <button type="button">inside</button>
      </Overlay>
    </div>
  );
}

describe("Overlay", () => {
  it("renders OUTSIDE the transformed ancestor that would otherwise trap it", () => {
    render(<Trapped />);

    const dialog = screen.getByTestId("test-dialog");
    const ancestor = screen.getByTestId("transformed-ancestor");

    expect(ancestor.contains(dialog)).toBe(false);
    expect(document.body.contains(dialog)).toBe(true);
    // Directly under <body>: nothing between it and the root can create a
    // stacking context around it.
    expect(screen.getByTestId("test-dialog-backdrop").parentElement).toBe(document.body);
  });

  it("locks the page scroll while open and restores it exactly on close", () => {
    document.body.style.overflow = "auto";
    const { unmount } = render(<Trapped />);
    expect(document.body.style.overflow).toBe("hidden");

    unmount();
    expect(document.body.style.overflow).toBe("auto");
  });

  it("ignores an implausible scrollbar measurement rather than indenting the page", () => {
    // jsdom reports documentElement.clientWidth as 0, which makes the
    // difference the whole window width. The panel was rendered against a
    // body indented by 1024px before this was bounded.
    const { unmount } = render(<Trapped />);
    const pad = document.body.style.paddingRight;
    expect(pad === "" || Number.parseInt(pad, 10) <= 40).toBe(true);
    unmount();
  });

  it("closes on Escape — a modal dismissable only by a small × is a demo trap", async () => {
    const onClose = vi.fn();
    render(<Trapped onClose={onClose} />);
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on the backdrop and not on the panel", async () => {
    const onClose = vi.fn();
    render(<Trapped onClose={onClose} />);

    await userEvent.click(screen.getByText("dialog body"));
    expect(onClose).not.toHaveBeenCalled();

    await userEvent.click(screen.getByTestId("test-dialog-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("announces itself as a modal dialog with a name", () => {
    render(<Trapped />);
    const dialog = screen.getByRole("dialog", { name: "Test dialog" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("nests without an inner close releasing the outer one's scroll lock", () => {
    document.body.style.overflow = "auto";
    const outer = render(<Trapped />);
    const inner = render(
      <Overlay onClose={() => {}} label="Inner" testId="inner-dialog">
        <p>inner</p>
      </Overlay>,
    );

    expect(document.body.style.overflow).toBe("hidden");
    inner.unmount();
    expect(document.body.style.overflow).toBe("hidden");
    outer.unmount();
    expect(document.body.style.overflow).toBe("auto");
  });
});
