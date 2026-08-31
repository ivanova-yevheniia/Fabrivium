import type { CoverageReport } from "../api/product";

/** WHAT COVERAGE IS ENTITLED TO CLAIM. */
export function coverageSummaryText(coverage: CoverageReport): string {
  const addressed = coverage.items.filter((item) => item.status === "ADDRESSED").length;
  const unresolved = coverage.items.filter((item) => item.status === "UNRESOLVED").length;
  const total = addressed + unresolved;

  if (total === 0) {
    // "The source states no manufacturing requirements" asserts something
    // about the document. What is true is that extraction produced none.
    return "No manufacturing requirements were extracted from the source.";
  }
  if (unresolved === 0) {
    return `All ${total} extracted manufacturing requirement${total === 1 ? "" : "s"} are addressed.`;
  }
  // Still short of complete: the backend's own sentence is precise about
  // which are unresolved and how many the source stated explicitly.
  return coverage.summary;
}
