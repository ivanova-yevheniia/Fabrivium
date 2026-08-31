import { useAppContext } from "../../state/AppContext";

/** Surfaces network/validation/API errors distinctly (Phase 6A section 2:
 * "Handle: loading, API error, validation error, backend unavailable"). */
export function ErrorBanner() {
  const { state, clearError } = useAppContext();
  if (!state.error) return null;

  const prefix =
    state.error.kind === "network"
      ? "Backend unavailable"
      : state.error.kind === "validation"
        ? "Invalid request"
        : state.error.kind === "api"
          // An API error usually carries the domain's own sentence, and
          // `describeRequestFailure` now returns it unprefixed. "Backend
          // error:" in front of "Still required: Shifts per day..." would
          // reintroduce exactly the framing that fix removed.
          ? ""
          : "Error";

  // `describeRequestFailure` already opens with the same kind label, so
  // rendering both produced "Backend unavailable: Backend unavailable:
  // Could not reach the Fabrivium backend." (Phase 11 failure-path
  // audit). The banner keeps its own bold prefix and drops the duplicate
  // from the message rather than changing the shared helper, which other
  // callers use as a standalone one-liner.
  const detail =
    prefix && state.error.message.startsWith(`${prefix}: `)
      ? state.error.message.slice(prefix.length + 2)
      : state.error.message;

  return (
    <div className="fm-error-banner" role="alert" data-testid="error-banner">
      {prefix && <strong>{prefix}:</strong>} {detail}{" "}
      <button className="fm-btn-secondary" style={{ marginLeft: 8, padding: "2px 8px" }} onClick={clearError}>
        Dismiss
      </button>
    </div>
  );
}
