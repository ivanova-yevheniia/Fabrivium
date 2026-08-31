import { describe, expect, it } from "vitest";
import { EQUIPMENT_STATE_LABEL, EQUIPMENT_STATE_NOTE } from "./equipmentState";
import type { EquipmentState } from "./equipmentState";

/** §18 — the strongest word this screen is allowed to use. */

const ALL: EquipmentState[] = [
  "DISCOVERED",
  "UNDER_CONSIDERATION",
  "REQUIREMENTS_MATCHED",
  "UNVERIFIED",
  "CONTRADICTED",
  "COMMERCIAL_DATA_REQUIRED",
  "STALE",
];

describe("equipment state vocabulary", () => {
  it("uses the canonical short label for each state", () => {
    expect(EQUIPMENT_STATE_LABEL.DISCOVERED).toBe("Candidate");
    expect(EQUIPMENT_STATE_LABEL.UNDER_CONSIDERATION).toBe("Under consideration");
    expect(EQUIPMENT_STATE_LABEL.REQUIREMENTS_MATCHED).toBe("Requirement matched");
    expect(EQUIPMENT_STATE_LABEL.UNVERIFIED).toBe("Not verified");
    expect(EQUIPMENT_STATE_LABEL.CONTRADICTED).toBe("Constraint mismatch");
    expect(EQUIPMENT_STATE_LABEL.COMMERCIAL_DATA_REQUIRED).toBe("Commercial data required");
    expect(EQUIPMENT_STATE_LABEL.STALE).toBe("Stale");
  });

  it("never uses a word that reads as approval", () => {
    // A machine whose cycle time nobody publishes has not been verified
    // against anything, and no badge on this screen may suggest otherwise.
    //
    // The check is for a POSITIVE claim. "Not verified" contains the word
    // and is the opposite of the claim — it is precisely the label this
    // rule exists to protect — so a preceding negation is required to pass.
    const positiveApproval = /(?<!\bnot\s)\b(verified|approved|compatible|suitable|recommended|best)\b/i;
    for (const state of ALL) {
      expect(EQUIPMENT_STATE_LABEL[state]).not.toMatch(positiveApproval);
    }
    // And the negated form really is present, rather than the rule passing
    // because nothing on this screen mentions verification at all.
    expect(EQUIPMENT_STATE_LABEL.UNVERIFIED).toMatch(/not verified/i);
  });

  it("carries the qualification the short badge can no longer hold", () => {
    // "Requirement matched" alone reads as "approved for this station". What
    // it means is that every bound a manufacturer happened to publish
    // compared favourably — three of eight, for real screwdriving equipment.
    expect(EQUIPMENT_STATE_NOTE.REQUIREMENTS_MATCHED).toBe(
      "Matches the required capability. Application-specific parameters still need supplier or engineering confirmation.",
    );
  });

  it("describes an unpublished value as an absence, not a failure", () => {
    expect(EQUIPMENT_STATE_NOTE.UNVERIFIED).toMatch(/absence, not a failure/i);
  });

  it("has a note for every state, so a badge is never left to stand alone", () => {
    for (const state of ALL) {
      expect(EQUIPMENT_STATE_NOTE[state]).toBeTruthy();
      expect(EQUIPMENT_STATE_NOTE[state].length).toBeGreaterThan(40);
    }
  });
});
