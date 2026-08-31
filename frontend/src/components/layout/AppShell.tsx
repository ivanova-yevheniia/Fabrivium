import { ConversationPanel } from "../conversation/ConversationPanel";
import { ExplanationPanel } from "../explanation/ExplanationPanel";
import { KpiPanel } from "../kpi/KpiPanel";
import { PlaybackControls } from "../playback/PlaybackControls";
import { PlanningTimeline } from "../timeline/PlanningTimeline";
import { CenterWorkspace } from "./CenterWorkspace";
import { EngineeringTabs } from "./EngineeringTabs";
import { ErrorBanner } from "./ErrorBanner";
import { IterationSwitchConfirm } from "./IterationSwitchConfirm";
import { SelectedMachinePanel } from "./SelectedMachinePanel";
import { TopBar } from "./TopBar";
import { UnplacedEquipmentPanel } from "./UnplacedEquipmentPanel";
import { ViolationsPanel } from "./ViolationsPanel";
import { useAppContext } from "../../state/AppContext";

/** Engineering View — the evidence level. */
export function AppShell() {
  const { state } = useAppContext();
  const tab = state.engineeringTab;

  return (
    <div className={`app-shell app-shell--${tab.toLowerCase()}`} data-testid="app-shell">
      <TopBar />
      <div className="app-shell__context">
        <EngineeringTabs />
      </div>

      {tab === "FACTORY" && (
        <>
          <CenterWorkspace />
          <aside className="right-panel" data-testid="engineering-factory-panel">
            <SelectedMachinePanel />
            <ViolationsPanel />
            <UnplacedEquipmentPanel />
          </aside>
        </>
      )}

      {tab === "SIMULATION" && (
        <>
          <CenterWorkspace />
          <aside className="right-panel" data-testid="engineering-simulation-panel">
            <KpiPanel />
          </aside>
        </>
      )}

      {tab === "PLAN_ANALYSIS" && (
        <>
          <ConversationPanel />
          <CenterWorkspace />
          <aside className="right-panel" data-testid="engineering-plan-panel">
            <KpiPanel />
            <ExplanationPanel />
          </aside>
        </>
      )}

      {/* The transport bar is mounted OUTSIDE the tab switch on purpose:
          playback can be opened from Executive View, and a user who then
          moves to Engineering must not lose the controls for the animation
          still running in front of them. It renders nothing at all unless
          a trace is actually open. The timeline stays inside Plan analysis
          — it selects which plan iteration to inspect, which is that tab's
          job. */}
      <div className="bottom-stack">
        <PlaybackControls />
        {tab === "PLAN_ANALYSIS" && <PlanningTimeline />}
      </div>

      <ErrorBanner />
      <IterationSwitchConfirm />
    </div>
  );
}
