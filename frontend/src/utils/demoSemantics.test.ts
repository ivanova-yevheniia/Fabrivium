import { describe, expect, it } from "vitest";
import { scenarioWords, transitionLabel } from "./scenario";
import { GAP_TITLE, groupGaps, humanizeInternalTokens } from "./informationGaps";
import { coverageSummaryText } from "./coverageSummary";
import { compactStationName } from "./formatting";
import { initialConceptState } from "../state/types";
import { operatorCostGap, shiftCostGap } from "../test/fixtures";
import type { CoverageReport } from "../api/product";
import type { FactoryConceptDraft, InformationGap } from "../api/types";

/** §1, §6, §7, §11, §14 — the words the product is allowed to use. */

const draft = { name: "concept" } as unknown as FactoryConceptDraft;

describe("§1 — baseline vocabulary follows the journey", () => {
  it("calls the unchanged state a BASELINE CONCEPT when the factory does not exist yet", () => {
    const words = scenarioWords({ concept: { ...initialConceptState, draft } });
    expect(words.greenfield).toBe(true);
    expect(words.baseline).toBe("Baseline concept");
    expect(words.baselineShort).toBe("Baseline");
    expect(transitionLabel(words, "Plan A")).toBe("Baseline → Plan A");
  });

  it("keeps TODAY for a factory that genuinely exists", () => {
    // The bundled example line is a modelled, existing factory. Renaming its
    // baseline to "concept" would be the same error pointing the other way.
    const words = scenarioWords({ concept: initialConceptState });
    expect(words.greenfield).toBe(false);
    expect(words.baseline).toBe("Today, without changes");
    expect(transitionLabel(words, "Plan D")).toBe("Today → Plan D");
  });
});

describe("§6 — internal identifiers do not reach user-facing prose", () => {
  it("translates every gap type the backend can interpolate", () => {
    const sentence =
      "Plan A shows a known CAPEX of EUR 0, but that is not a full price — " +
      "MACHINE_CAPACITY_COST, SHIFT_COST must be supplied before it can be ranked financially.";
    const out = humanizeInternalTokens(sentence);

    expect(out).toContain("the cost of increasing station capacity");
    expect(out).toContain("the cost of an additional shift");
    expect(out).not.toMatch(/SHIFT_COST|MACHINE_CAPACITY_COST/);
  });

  it("leaves an ordinary sentence — and legitimate jargon — untouched", () => {
    // CAPEX is a word a manufacturing manager uses; it is not an identifier.
    const sentence = "Plan A is fully priced at EUR 85,000 known CAPEX.";
    expect(humanizeInternalTokens(sentence)).toBe(sentence);
  });

  it("has a phrase for every member of the enum", () => {
    const types: Array<keyof typeof GAP_TITLE> = [
      "SHIFT_COST",
      "OPERATOR_COST",
      "BUFFER_MODIFICATION_COST",
      "PROCESS_IMPROVEMENT_COST",
      "MACHINE_CAPACITY_COST",
    ];
    for (const type of types) {
      expect(GAP_TITLE[type]).toBeTruthy();
      expect(GAP_TITLE[type]).not.toMatch(/_/);
    }
  });
});

describe("§7 — one missing input is named once", () => {
  it("de-duplicates a gap that blocks several options", () => {
    // Four plans blocked by the same unknown is ONE thing to go and find
    // out; the prose repeated it once per plan.
    const gaps: InformationGap[] = [shiftCostGap, operatorCostGap, shiftCostGap, shiftCostGap];
    const groups = groupGaps(gaps);

    const items = groups.flatMap((g) => g.items);
    expect(items).toHaveLength(2);
    expect(items.map((i) => i.type).sort()).toEqual(["OPERATOR_COST", "SHIFT_COST"]);
  });

  it("groups by what an engineer would have to go and do", () => {
    const groups = groupGaps([shiftCostGap]);
    expect(groups).toHaveLength(1);
    expect(groups[0].group).toBe("Operations");
    expect(groups[0].items[0].title).toBe("Cost of an additional shift");
  });

  it("returns nothing when nothing is missing", () => {
    expect(groupGaps([])).toEqual([]);
  });
});

describe("§11 — coverage claims only what it can prove", () => {
  function report(overrides: Partial<CoverageReport>): CoverageReport {
    return {
      items: [],
      summary: "",
      complete: true,
      approval_blocked: false,
      unresolved_count: 0,
      critical_unresolved_count: 0,
      ...overrides,
    };
  }

  const addressed = (key: string) =>
    ({
      fact_key: key,
      label: key,
      value: null,
      status: "ADDRESSED" as const,
      severity: "CRITICAL" as const,
      addressed_by: ["Packaging"],
      quotes: [],
    });

  it("says EXTRACTED, not 'found in the source'", () => {
    // Fabrivium can prove every extracted requirement is answered. It
    // cannot prove extraction found every requirement the document states.
    const text = coverageSummaryText(
      report({
        items: [addressed("a"), addressed("b")],
        summary: "All 2 manufacturing requirements found in the source are addressed.",
      }),
    );
    expect(text).toBe("All 2 extracted manufacturing requirement" + "s are addressed.");
    expect(text).not.toMatch(/found in the source/);
  });

  it("does not weaken the incomplete sentence, which makes no such claim", () => {
    const backend = "5 of 7 extracted manufacturing requirements are addressed; 2 unresolved.";
    const text = coverageSummaryText(
      report({
        items: [
          addressed("a"),
          { ...addressed("b"), status: "UNRESOLVED" as const, addressed_by: [] },
        ],
        summary: backend,
      }),
    );
    expect(text).toBe(backend);
  });

  it("attributes an empty result to extraction, not to the document", () => {
    expect(coverageSummaryText(report({ items: [], summary: "x" }))).toBe(
      "No manufacturing requirements were extracted from the source.",
    );
  });
});

describe("§14 — a station label is the engineer's name, shortened if it must be", () => {
  it("leaves a name that fits completely alone", () => {
    expect(compactStationName("Cable connection ×2")).toBe("Cable connection ×2");
    expect(compactStationName("PCB placement")).toBe("PCB placement");
  });

  it("keeps the repetition multiplier through a truncation", () => {
    // "Screw fastening" and "Screw fastening ×6" describe different amounts
    // of work, so the ×6 survives while the words give way.
    const short = compactStationName("Automated screw fastening cell ×6", 20);
    expect(short).toMatch(/×6$/);
    expect(short.length).toBeLessThanOrEqual(20);
  });

  it("breaks on a word boundary rather than mid-word", () => {
    expect(compactStationName("Prepare plastic enclosure", 18)).toBe("Prepare plastic…");
  });

  it("is deterministic — the same name always shortens the same way", () => {
    const name = "Final functional inspection and test";
    expect(compactStationName(name, 20)).toBe(compactStationName(name, 20));
  });
});
