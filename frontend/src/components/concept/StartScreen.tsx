import { ArrowLeft, Factory, Package, PencilRuler } from "lucide-react";
import { useAppContext } from "../../state/AppContext";

/** How this project starts. */
export function StartScreen() {
  const { state, setStartMode, openDemoFactory, closeProject } = useAppContext();

  return (
    <div className="start-screen" data-testid="start-screen">
      <div className="start-screen__inner">
        <header className="start-screen__head">
          <h1 className="start-screen__title">{state.project.name || "Fabrivium"}</h1>
          <p className="start-screen__tagline">
            How does this project start? Both routes end at the same verified factory model.
          </p>
        </header>

        <p className="fm-label start-screen__prompt">Choose a starting point</p>

        <div className="start-screen__options">
          {/* Phase 19. */}
          <button
            type="button"
            className="start-option start-option--primary"
            onClick={() => setStartMode("PRODUCT_FIRST")}
            data-testid="start-from-product"
          >
            <span className="start-option__icon" aria-hidden="true">
              <Package size={20} strokeWidth={1.8} />
            </span>
            <span className="start-option__body">
              <span className="start-option__title">Start from a product</span>
              <span className="start-option__detail">
                Describe it or upload its specification. Fabrivium works out what manufacturing
                operations it needs.
              </span>
            </span>
          </button>

          <button
            type="button"
            className="start-option"
            onClick={() => setStartMode("CONCEPT_BUILDER")}
            data-testid="start-design-new"
          >
            <span className="start-option__icon" aria-hidden="true">
              <PencilRuler size={20} strokeWidth={1.8} />
            </span>
            <span className="start-option__body">
              <span className="start-option__title">Design a new factory</span>
              <span className="start-option__detail">
                Turn production requirements into a simulation-ready concept. No CAD needed.
              </span>
            </span>
          </button>

          {/* Only inside an EXAMPLE project, and phrased as what it is. */}
          {state.project.isExample && (
            <button
              type="button"
              className="start-option"
              onClick={() => void openDemoFactory()}
              disabled={state.factoryLoading}
              data-testid="start-open-demo"
            >
              <span className="start-option__icon" aria-hidden="true">
                <Factory size={20} strokeWidth={1.8} />
              </span>
              <span className="start-option__body">
                <span className="start-option__title">
                  {state.factoryLoading ? "Loading…" : "Open the bundled example line"}
                </span>
                <span className="start-option__detail">
                  Electronics Assembly Line — a complete example model, already simulated.
                </span>
              </span>
            </button>
          )}
        </div>

        <div className="estimate__footer">
          <button
            type="button"
            className="fm-btn-tertiary"
            onClick={closeProject}
            data-testid="start-back-to-projects"
          >
            <ArrowLeft size={13} strokeWidth={2} aria-hidden="true" />
            All projects
          </button>
        </div>
      </div>
    </div>
  );
}
