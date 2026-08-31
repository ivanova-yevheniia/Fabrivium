import { Factory, Activity, GitCompare } from "lucide-react";
import { useAppContext } from "../../state/AppContext";
import type { EngineeringTab } from "../../state/types";

/** Phase 12 §8 — which engineering question is being asked. */

const TABS: { id: EngineeringTab; label: string; icon: typeof Factory; hint: string }[] = [
  { id: "FACTORY", label: "Factory", icon: Factory, hint: "Simulated factory, layout and machine detail" },
  { id: "SIMULATION", label: "Simulation", icon: Activity, hint: "Playback, operators, buffers and queues" },
  { id: "PLAN_ANALYSIS", label: "Plan analysis", icon: GitCompare, hint: "Strategies, KPIs, iterations and costs" },
];

export function EngineeringTabs() {
  const { state, setEngineeringTab } = useAppContext();

  return (
    <div className="eng-tabs" role="tablist" aria-label="Engineering context" data-testid="engineering-tabs">
      {TABS.map((tab) => {
        const Icon = tab.icon;
        const active = state.engineeringTab === tab.id;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={active}
            className={`eng-tabs__tab${active ? " eng-tabs__tab--active" : ""}`}
            onClick={() => setEngineeringTab(tab.id)}
            title={tab.hint}
            data-testid={`engineering-tab-${tab.id.toLowerCase()}`}
          >
            <Icon size={15} strokeWidth={2} aria-hidden="true" />
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
