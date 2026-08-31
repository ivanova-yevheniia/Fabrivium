import type { InformationGap, InformationGapType } from "../api/types";
import type { NamedThing } from "./formatting";

/** INTERNAL IDENTIFIERS DO NOT REACH THE SCREEN. */

/** One phrase per gap, in the words an engineer would use for the same missing number. */
export const GAP_PHRASE: Record<InformationGapType, string> = {
  SHIFT_COST: "the cost of an additional shift",
  OPERATOR_COST: "the cost of an additional operator",
  BUFFER_MODIFICATION_COST: "the cost of changing buffer capacity",
  PROCESS_IMPROVEMENT_COST: "the cost of the process improvement",
  MACHINE_CAPACITY_COST: "the cost of increasing station capacity",
};

/** Title-case form, for a heading or the start of a sentence. */
export const GAP_TITLE: Record<InformationGapType, string> = {
  SHIFT_COST: "Cost of an additional shift",
  OPERATOR_COST: "Cost of an additional operator",
  BUFFER_MODIFICATION_COST: "Cost of changing buffer capacity",
  PROCESS_IMPROVEMENT_COST: "Cost of the process improvement",
  MACHINE_CAPACITY_COST: "Cost of increasing station capacity",
};

/** Which heading a gap belongs under, so one shared input is not repeated once per strategy. */
export type GapGroup = "Equipment" | "Operations" | "Process";

export const GAP_GROUP: Record<InformationGapType, GapGroup> = {
  MACHINE_CAPACITY_COST: "Equipment",
  SHIFT_COST: "Operations",
  OPERATOR_COST: "Operations",
  BUFFER_MODIFICATION_COST: "Process",
  PROCESS_IMPROVEMENT_COST: "Process",
};

const TOKENS = Object.keys(GAP_PHRASE) as InformationGapType[];

/** Replace any internal gap identifier in a backend sentence with its human phrase. */
export function humanizeInternalTokens(
  text: string,
  /** The stations, when the caller has them, so a machine or buffer key in
   * a backend sentence can be replaced with the name the rest of the screen
   * uses for it. Omitted, ids are left alone rather than guessed at. */
  known?: readonly NamedThing[] | null,
): string {
  if (!text) return text;
  let out = text;
  for (const token of [...TOKENS].sort((a, b) => b.length - a.length)) {
    out = out.replace(new RegExp(`\\b${token}\\b`, "g"), GAP_PHRASE[token]);
  }

  // Station and buffer keys. "Purchase cost of a parallel machine at
  // m-screwdriving is not recorded" reached an engineer in the golden run,
  // inside an answer whose entire claim is that Fabrivium is precise about
  // what it knows — and a database key is the one thing on that screen
  // nobody can act on.
  //
  // Done here as well as at source, because these sentences are PERSISTED
  // with a project: an arena saved before the backend stopped emitting ids
  // still carries the old prose, and reopening it must not put the key
  // back on screen. Only ids the caller can actually name are replaced; an
  // unknown key is left exactly as it is rather than turned into a
  // plausible-looking guess.
  if (known && known.length > 0) {
    out = out.replace(/\b[mb]-[a-z][a-z0-9-]*/gi, (id) => {
      const match = known.find((thing) => thing.id === id);
      return match ? match.name : id;
    });
  }

  // The backend also lower-cases a token for one sentence ("shift cost =
  // EUR 18,000"), which reads fine and is left alone; only the raw
  // SCREAMING_SNAKE form is an identifier on screen.
  return out;
}

// Grouping — one missing input, named once

export interface GroupedGaps {
  group: GapGroup;
  items: Array<{ type: InformationGapType; title: string; description: string }>;
}

/** The distinct things still missing, grouped by what an engineer would have to go and do. */
export function groupGaps(
  gaps: readonly InformationGap[],
  /** Stations, so a key inside a gap description is named. */
  known?: readonly NamedThing[] | null,
): GroupedGaps[] {
  const seen = new Map<InformationGapType, InformationGap>();
  for (const gap of gaps) {
    if (!seen.has(gap.gap_type)) seen.set(gap.gap_type, gap);
  }

  const order: GapGroup[] = ["Equipment", "Operations", "Process"];
  const grouped: GroupedGaps[] = [];
  for (const group of order) {
    const items = [...seen.values()]
      .filter((gap) => GAP_GROUP[gap.gap_type] === group)
      .map((gap) => ({
        type: gap.gap_type,
        title: GAP_TITLE[gap.gap_type],
        description: humanizeInternalTokens(gap.description, known),
      }));
    if (items.length > 0) grouped.push({ group, items });
  }
  return grouped;
}
