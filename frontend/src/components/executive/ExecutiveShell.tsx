import { useAppContext } from "../../state/AppContext";
import { TopBar } from "../layout/TopBar";
import { ErrorBanner } from "../layout/ErrorBanner";
import { IterationSwitchConfirm } from "../layout/IterationSwitchConfirm";
import { PlaybackControls } from "../playback/PlaybackControls";
import { AnalysisProgress } from "./AnalysisProgress";
import { ExecutiveResults } from "./ExecutiveResults";
import { GoalInput } from "./GoalInput";
import { ConceptReady } from "../concept/ConceptReady";

/** Phase 9A — the default (competition/demo) presentation level. */
export function ExecutiveShell() {
  const { state } = useAppContext();

  // Loading always takes priority, even over a PREVIOUS result (Phase 9A
  // section 16): a conversational refinement re-running must never leave
  // stale strategy/KPI content on screen while a new verified answer is
  // in flight.
  const loading = state.exploring || state.planLoading || state.conversationSending;
  const hasResult = Boolean(state.arena) || Boolean(state.session);

  // Phase 14 (audit finding A1) — a factory that came from the concept
  // builder continues its own story instead of restarting at "What does your
  // factory need?". The user already stated the target; asking again under
  // the product's splash heading read as though the builder had been a
  // detour. `GoalInput` is still the right first question for the OTHER
  // entry — optimizing a factory that already exists — so both remain.
  const cameFromBuilder = state.concept.draft !== null;
  const entry = cameFromBuilder ? <ConceptReady /> : <GoalInput />;

  return (
    <div className="executive-shell" data-testid="executive-shell">
      <TopBar />
      <main className="executive-shell__main">
        {loading ? <AnalysisProgress /> : hasResult ? <ExecutiveResults /> : entry}
      </main>
      <PlaybackControls />
      <ErrorBanner />
      <IterationSwitchConfirm />
    </div>
  );
}
