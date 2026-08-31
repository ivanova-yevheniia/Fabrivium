import { describe, expect, it } from "vitest";
// Vite's ?raw import gives the stylesheet as a string without pulling Node
// types into the browser tsconfig.
import css from "./index.css?raw";

/** Phase 17A — responsive contract. */

/** The declarations belonging to one selector, as written. */
function ruleBody(selector: string): string {
  const at = css.indexOf(`\n${selector} {`);
  expect(at, `selector ${selector} not found`).toBeGreaterThan(-1);
  return css.slice(at, css.indexOf("}", at));
}

describe("content width system", () => {
  it("defines the three content widths as tokens", () => {
    // Before this phase there were 16 unrelated max-width values scattered
    // across components, which is why nothing scaled together.
    for (const token of ["--fm-content-narrow", "--fm-content-default", "--fm-content-wide"]) {
      expect(css).toContain(`${token}:`);
    }
  });

  it("uses a fluid gutter so small screens are not squeezed twice", () => {
    expect(css).toMatch(/--fm-gutter:\s*clamp\(/);
  });
});

describe("fluid typography", () => {
  it("makes the large sizes fluid", () => {
    // These are the sizes read from a distance and the ones that break
    // narrow layouts.
    for (const token of ["--fm-type-h1", "--fm-type-h2", "--fm-type-h3", "--fm-type-display"]) {
      expect(css).toMatch(new RegExp(`${token}:\\s*clamp\\(`));
    }
  });

  it("keeps the dense engineering sizes fixed", () => {
    // Density is the product. A fluid 11px label would drift below
    // legibility on a projector, so these must stay pinned.
    for (const token of ["--fm-type-micro", "--fm-type-tiny", "--fm-type-small", "--fm-type-body"]) {
      expect(css).toMatch(new RegExp(`${token}:\\s*\\d+px`));
    }
  });
});

describe("viewport height", () => {
  it("sizes the app shells with dvh, not vh", () => {
    // 100vh is taller than the visible area once browser chrome is present,
    // which is exactly how content gets pushed under the fold on the
    // laptops this is presented from.
    expect(ruleBody(".app-shell")).toContain("height: 100dvh");
    expect(ruleBody(".executive-shell")).toContain("min-height: 100dvh");
  });

  it("lets the results page grow instead of fitting itself to the window", () => {
    // The results page used to be `height: 100dvh; overflow-y: auto` — a box
    // exactly the size of the window with its own scrollbar inside. On a
    // laptop whose usable viewport is ~609px that reads as the app being
    // squeezed to fit rather than laid out: the page never grew, it only
    // compressed. min-height plus document flow means the same page is
    // simply TALLER on a short screen.
    const shell = ruleBody(".executive-shell");
    expect(shell).toContain("min-height: 100dvh");
    expect(shell).not.toMatch(/\n\s*height: 100dvh/);
    expect(shell).not.toContain("overflow-y: auto");
  });

  it("keeps the digital-twin shell bounded", () => {
    // Not an oversight: the 2D/3D canvas needs a bounded height to have any
    // size to render into. Everything inside uses minmax(0, 1fr) so it
    // distributes the window rather than overflowing it.
    const shell = ruleBody(".app-shell");
    expect(shell).toContain("height: 100dvh");
    expect(shell).toContain("overflow: hidden");
  });

  it("never sizes a scrolling page with 100vw", () => {
    // With a document scrollbar present, 100vw is wider than the content
    // box — the classic cause of an unexplained horizontal scrollbar.
    expect(ruleBody(".executive-shell")).not.toContain("width: 100vw");
    expect(ruleBody(".app-shell")).not.toContain("width: 100vw");
  });

  it("sizes the full-height centred pages with svh", () => {
    expect(ruleBody(".start-screen")).toContain("min-height: 100svh");
    expect(ruleBody(".concept-brief")).toContain("min-height: 100svh");
  });

  it("clamps vertical block padding instead of charging every screen the same", () => {
    expect(css).toMatch(/--fm-block-pad:\s*clamp\(/);
    expect(ruleBody(".start-screen")).toContain("var(--fm-block-pad)");
  });
});

describe("the landing hero composition", () => {
  it("separates viewport ownership from reading measure", () => {
    // The measured root cause: one box tried to be both the full-height
    // container and the 720px content column, so centring it left 285px of
    // dead space above AND below a block using 37% of the height.
    const outer = ruleBody(".start-screen");
    const inner = ruleBody(".start-screen__inner");
    expect(outer).toContain("min-height: 100svh");
    expect(outer).not.toMatch(/max-width:\s*\d+px/);
    expect(inner).toContain("max-width:");
  });

  it("centres optically rather than mathematically", () => {
    // Uneven grid rows: a mathematically centred block reads as slightly
    // low, and the extra weight below keeps the second card clear of the
    // fold on short viewports.
    expect(ruleBody(".start-screen")).toMatch(/grid-template-rows:\s*5fr auto 7fr/);
  });

  it("lets the hero grow on a large display", () => {
    // §3: it must not look tiny in an ocean of empty space at 1920.
    expect(ruleBody(".start-screen__inner")).toMatch(/clamp\([^)]*vw/);
  });
});

describe("prohibited scaling shortcuts", () => {
  it("never fakes responsiveness by scaling the whole application", () => {
    // A transform/zoom on a layout root scales text rendering and hit
    // targets with it, and hard-coded per-resolution coordinates are the
    // defect this phase existed to remove.
    expect(ruleBody(".app-shell")).not.toMatch(/transform:\s*scale\(/);
    expect(ruleBody(".executive-shell")).not.toMatch(/transform:\s*scale\(/);
    expect(ruleBody(".start-screen")).not.toMatch(/transform:\s*scale\(/);
    expect(css).not.toMatch(/\n\s*zoom:\s*[\d.]/);
  });
});

describe("wide content stays confined", () => {
  it("gives the comparison table its own horizontal scroller", () => {
    // §7: if a table genuinely needs horizontal scrolling it must be
    // bounded, never handed to the page.
    expect(ruleBody(".equipment__compare-wrap")).toContain("overflow-x: auto");
  });

  it("lets candidate cards reflow by available space rather than a fixed count", () => {
    expect(ruleBody(".equipment__cards")).toMatch(/repeat\(auto-fit,\s*minmax\(/);
  });
});

describe("the sticky playback bar reserves its space (audit §6)", () => {
  // Measured live at 1920x1080 before this fix: the 73px bar sat over the
  // workspace toolbar, and document.elementFromPoint on the centre of the
  // 2D/3D toggle returned the BAR. The button was not merely obscured, it
  // was unclickable — switching to the 3D twin during playback silently did
  // nothing. jsdom performs no layout, so what is pinned here is the CSS
  // contract that prevents it; the behaviour itself was verified in a real
  // browser.

  it("keeps the bar's height out of the scrollable column", () => {
    expect(ruleBody(".executive-shell:has(> .bottom-panel) .executive-shell__main")).toContain(
      "--fm-playback-bar-height",
    );
  });

  it("reserves space only while a bar is actually present", () => {
    // Padding that is always there would leave dead space on every screen
    // that has no playback bar.
    expect(ruleBody(".executive-shell")).toContain("--fm-playback-bar-height: 0px");
    expect(ruleBody(".executive-shell:has(> .bottom-panel)")).toMatch(
      /--fm-playback-bar-height:\s*\d+px/,
    );
  });
});

describe("the entry screen fills its column (audit §15)", () => {
  it("centres the goal panel instead of stacking it against the top", () => {
    // At 1920x1080 the panel occupied the top 45% and left ~550px of empty
    // floor, which reads as a page that failed to finish loading.
    const body = ruleBody(".goal-input");
    expect(body).toContain("flex: 1");
    expect(body).toContain("justify-content: center");
  });
});

describe("the assumption review keeps its decision on screen (audit §15)", () => {
  // Measured at 1366x768: the list is ~750px inside a ~630px modal, so
  // "Accept these assumptions" sat below the modal's scroll area entirely.
  // The user saw twenty rows of numbers and no visible way to act on them.

  it("pins the footer so the primary action stays visible", () => {
    const body = ruleBody(".assumption-review__foot");
    expect(body).toContain("position: sticky");
    expect(body).toContain("background: var(--fm-panel)");
  });

  it("pins the head so the subject of the review stays visible too", () => {
    expect(ruleBody(".assumption-review__head")).toContain("position: sticky");
  });

  it("keeps the modal itself the scroller", () => {
    // The sticky children only work while the modal is the scroll
    // container; if the page scrolled instead, both would detach.
    expect(ruleBody(".assumption-review")).toContain("overflow-y: auto");
  });
});
