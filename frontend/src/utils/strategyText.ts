/** Phase 11 — make backend-authored strategy prose safe to show a judge. */

export interface StrategyLabelSource {
  strategy_id: string;
  label: string;
}

export function humanizeStrategyText(text: string, options: readonly StrategyLabelSource[]): string {
  if (!text) return text;
  const ordered = [...options].sort((a, b) => b.strategy_id.length - a.strategy_id.length);
  let out = text;
  for (const option of ordered) {
    if (!option.strategy_id) continue;
    out = out.split(option.strategy_id).join(option.label);
  }
  return softenDominanceVerdict(out);
}

/** "Dominated" is a claim about the OPERATIONAL axes only. */
export function softenDominanceVerdict(text: string): string {
  return text.replace(
    /Operationally dominated by:\s*([^.]+)\./gi,
    (_match, names: string) => `Requires more operational changes than ${names.trim()}.`,
  );
}
