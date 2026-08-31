import type { Factory } from "../../api/types";
import type { TraceIndex } from "../../utils/traceIndex";
import {
  BLOCKED_COLOR,
  LIMITING_STAGE_COLOR,
  PROCESSING_COLOR,
  STARVED_COLOR,
} from "../../utils/visualTokens";

/** WHAT THE COLOURS IN THE ANIMATION MEAN. */
export function SceneLegend({
  factory,
  traceIndex,
  limitingStageShown,
}: {
  factory: Factory;
  traceIndex: TraceIndex | null;
  /** True when a limiting-stage halo is actually drawn in this scene. */
  limitingStageShown: boolean;
}) {
  if (!traceIndex) return null;

  // A wired buffer is what makes STARVED derivable at all.
  const hasWiredBuffer = factory.buffers.some(
    (buffer) => buffer.upstream_machine_id && buffer.downstream_machine_id,
  );

  const items: Array<{ key: string; label: string; color: string; ring?: boolean }> = [
    { key: "processing", label: "Processing", color: PROCESSING_COLOR, ring: true },
    { key: "blocked", label: "Blocked", color: BLOCKED_COLOR, ring: true },
  ];
  if (hasWiredBuffer) {
    items.push({ key: "waiting", label: "Waiting for input", color: STARVED_COLOR });
  }
  if (limitingStageShown) {
    items.push({ key: "limiting", label: "Limiting stage", color: LIMITING_STAGE_COLOR });
  }

  return (
    <div className="scene-legend" data-testid="scene-legend">
      {items.map((item) => (
        <span className="scene-legend__item" key={item.key} data-testid={`scene-legend-${item.key}`}>
          <span
            className={`scene-legend__swatch${item.ring ? " scene-legend__swatch--ring" : ""}`}
            style={item.ring ? { borderColor: item.color } : { background: item.color }}
            aria-hidden="true"
          />
          {item.label}
        </span>
      ))}
    </div>
  );
}
