import { useAppContext } from "../../state/AppContext";
import { ProductStart } from "./ProductStart";
import type { BuildConceptResult } from "../../api/product";

/** Phase 19 — the product route's one connection to application state. */
export function ProductFirstFlow() {
  const { setStartMode, updateConceptDraft } = useAppContext();

  function handleConceptBuilt(result: BuildConceptResult) {
    // Hands over to the existing Concept Builder, which already knows how
    // to show gaps and how to offer the Station Assumption Assistant for
    // each one. The product context travels with the draft in the response;
    // the stage rows read it from there.
    void updateConceptDraft(result.draft);
    setStartMode("CONCEPT_BUILDER");
  }

  return <ProductStart onConceptBuilt={handleConceptBuilt} onBack={() => setStartMode("CHOOSING")} />;
}
