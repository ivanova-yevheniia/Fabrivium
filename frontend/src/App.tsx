import { AppShell } from "./components/layout/AppShell";
import { ExecutiveShell } from "./components/executive/ExecutiveShell";
import { ConceptBuilder } from "./components/concept/ConceptBuilder";
import { StartScreen } from "./components/concept/StartScreen";
import { ProductFirstFlow } from "./components/product/ProductFirstFlow";
import { ProjectLanding } from "./components/project/ProjectLanding";
import { ProjectBar } from "./components/project/ProjectBar";
import { AppProvider, useAppContext } from "./state/AppContext";

/**
 * Phase 9A — a presentation-level switch only (mirrors ViewMode/EditMode):
 * both shells read the exact same AppContext, so switching levels never
 * changes what session/plan/strategy is "real" — only how it is shown.
 *
 * P0 adds the project workspace above both of them; Phase 13's step is now
 * the first thing that happens INSIDE a project rather than the first thing
 * that happens in the application.
 *
 * Phase 13 adds one step BEFORE that switch. The app no longer assumes a
 * modelled factory exists: it asks how the session starts, and can build a
 * factory concept from a customer brief first. Once a factory exists —
 * whether it came from the demo file or from the builder — everything below
 * is exactly the pre-Phase-13 application, reading the same
 * `factory`/`layout`/`productId` state.
 */
function ViewLevelRouter() {
  const { state } = useAppContext();

  // P0 adds one step BEFORE all of that. The application no longer opens
  // into a production flow: it opens into a workspace of projects, and every
  // flow below runs inside one. That is what makes the work reopenable —
  // there is now something for it to belong to.
  if (state.startMode === "PROJECTS") return <ProjectLanding />;

  if (state.startMode === "CHOOSING") return <StartScreen />;

  // The two editing routes carry the project bar: which project is open, and
  // whether the last edit is saved. The workspace below has the same
  // controls in its own top bar, and the landing page has no project open.
  if (state.startMode === "PRODUCT_FIRST") {
    return (
      <>
        <ProjectBar />
        <ProductFirstFlow />
      </>
    );
  }
  if (state.startMode === "CONCEPT_BUILDER") {
    return (
      <>
        <ProjectBar />
        <ConceptBuilder />
      </>
    );
  }

  return state.viewLevel === "EXECUTIVE" ? <ExecutiveShell /> : <AppShell />;
}

export function App() {
  return (
    <AppProvider>
      <ViewLevelRouter />
    </AppProvider>
  );
}
