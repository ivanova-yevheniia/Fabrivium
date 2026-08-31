/**
 * Phase 9B — the single source of truth for the two new semantic colors
 * this phase introduces (material flow, neutral limiting-stage), used by
 * BOTH the 2D SVG overlay and the 3D scene. SVG can read CSS custom
 * properties directly, but three.js materials cannot (`MeshStandardMaterial
 * color` needs a literal value), so these are exported as literal hex
 * strings and mirrored as CSS custom properties in index.css — change a
 * color in exactly one place (here, then keep index.css's copy in sync) and
 * both renderers follow.
 *
 * Everything else (blocked=bad, processing=accent, good/warn) reuses the
 * existing --fm-* palette — this file only adds what was genuinely
 * missing, it does not replace the base tokens.
 */

export const FLOW_COLOR = "#3ba7c9"; // route lines + direction arrows — distinct from accent/warn/bad
export const FLOW_COLOR_DIM = "rgba(59, 167, 201, 0.35)";
export const LIMITING_STAGE_COLOR = "#7d8bb5"; // neutral slate-blue — never the same as an alarm color
export const STARVED_COLOR = "#6b7785"; // muted grey — "waiting for input", not a fault
export const IDLE_COLOR = "#3a4552";

export const BLOCKED_COLOR = "#e0563f"; // Fm-bad
export const PROCESSING_COLOR = "#4fb3ff"; // Fm-accent
export const BUFFERED_UNIT_COLOR = "#4fb3ff";
export const IN_TRANSIT_UNIT_COLOR = "#e6ebf1";
