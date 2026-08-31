import { useCallback, useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** THE OVERLAY LAYER CONTRACT. */

/** How many overlays are currently holding the page scroll. */
let openCount = 0;
let restoreOverflow = "";
let restorePaddingRight = "";

/** The widest a real scrollbar gets. */
const MAX_SCROLLBAR_PX = 40;

function lockPageScroll() {
  if (openCount === 0) {
    const { body } = document;
    restoreOverflow = body.style.overflow;
    restorePaddingRight = body.style.paddingRight;
    // The scrollbar disappears with the scroll, and the page behind the
    // backdrop shifts by its width if that is not paid back. Measured, not
    // assumed: a browser with overlay scrollbars reports 0 and gets no
    // padding at all.
    //
    // Bounded, because the measurement is not always a scrollbar. jsdom
    // reports `clientWidth` as 0, which makes the difference the entire
    // window width — and the panel was rendered against a body indented by
    // 1024px. No real scrollbar is wider than a few tens of pixels, so
    // anything larger is a broken reading and is ignored rather than
    // applied.
    const gutter = window.innerWidth - document.documentElement.clientWidth;
    body.style.overflow = "hidden";
    if (gutter > 0 && gutter <= MAX_SCROLLBAR_PX) body.style.paddingRight = `${gutter}px`;
  }
  openCount += 1;
}

function releasePageScroll() {
  openCount = Math.max(0, openCount - 1);
  if (openCount === 0) {
    document.body.style.overflow = restoreOverflow;
    document.body.style.paddingRight = restorePaddingRight;
  }
}

export function Overlay({
  onClose,
  label,
  children,
  className,
  testId,
}: {
  onClose: () => void;
  /** Names the dialog for assistive technology. */
  label: string;
  children: ReactNode;
  /** Extra class on the dialog panel, for size variants. */
  className?: string;
  testId?: string;
}) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  // Captured on mount so focus can go back where it came from. An engineer
  // who opened the dialog from a button should get that button back.
  const openerRef = useRef<Element | null>(null);

  const close = useCallback(() => onClose(), [onClose]);

  useEffect(() => {
    openerRef.current = document.activeElement;
    lockPageScroll();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        close();
      }
    }
    document.addEventListener("keydown", onKeyDown, true);

    // After paint, so the panel exists. Focusing the panel itself rather
    // than guessing at a first control: the dialog is scrollable, and the
    // panel is what the arrow keys should move.
    const frame = requestAnimationFrame(() => panelRef.current?.focus());

    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      cancelAnimationFrame(frame);
      releasePageScroll();
      const opener = openerRef.current;
      if (opener instanceof HTMLElement && document.contains(opener)) opener.focus();
    };
  }, [close]);

  // document.body is always present in the browser and in jsdom; the guard
  // is for a server render, where a portal has nowhere to go.
  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      className="fm-overlay"
      data-testid={testId ? `${testId}-backdrop` : "fm-overlay"}
      role="presentation"
      onMouseDown={(event) => {
        // mousedown, not click: a click that STARTED inside the dialog and
        // ended on the backdrop (a drag across a text selection) must not
        if (event.target === event.currentTarget) close();
      }}
    >
      <div
        ref={panelRef}
        className={`fm-overlay__panel${className ? ` ${className}` : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        tabIndex={-1}
        data-testid={testId}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}
