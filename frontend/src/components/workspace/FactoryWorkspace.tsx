import { useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import type { ConstraintViolation, Factory, FactoryLayout, LayoutZone, MachinePlacement } from "../../api/types";
import { compactStationName } from "../../utils/formatting";
import {
  machineFootprint,
  machineSafetyEnvelope,
  pointsToSvgPolygon,
  previewOverlap,
  zoneRectangle,
} from "../../utils/geometry";
import { assetFillId, assetLabel, assetVisualKind } from "./machineVisual";

/**
 * Stable component contract for the factory workspace (Phase 6A section 8,
 * extended Phase 6B into a real interactive 2D planner). Deliberately
 * PROPS-ONLY for its DATA (factory/layout/selection/violations come in as
 * props, never read from context directly) — so Phase 6C can swap the
 * internal renderer (SVG -> real 2D/3D) without the surrounding UI needing
 * to change. It DOES own transient local UI state for the active drag
 * gesture only (pointer offset/preview position) — that state is never
 * persisted anywhere; the committed result is reported via `onMoveMachine`
 * on drop, and the PARENT (CenterWorkspace) owns the actual draft layout.
 *
 * Coordinate mapping (Phase 6B section 1 — never silently redefined):
 *   MachinePlacement.x/y = machine footprint CENTER (SVG group transform
 *   below flips only the display Y axis so "up" reads as increasing Y —
 *   a display choice, not a semantic change; screen<->factory conversion
 *   goes through the SVG's own CTM so the flip is never manually
 *   re-derived/duplicated).
 *   LayoutZone.x/y = zone rectangle LOWER-LEFT corner.
 */
export interface FactoryWorkspaceProps {
  factory: Factory | null;
  layout: FactoryLayout | null;
  selectedMachineId: string | null;
  highlightedMachineIds: string[];
  /** True when the currently-displayed state is an evaluated-but-REJECTED
   * candidate (Phase 6A.1 section 3) — must be labeled explicitly, never
   * presented as accepted factory history. */
  isRejectedCandidate: boolean;
  bottleneckMachineId: string | null;
  onSelectMachine: (machineId: string) => void;
  /** True only in EDIT_LAYOUT mode on a stage that owns an editable draft
   * (Phase 6B section 7) — VIEW mode and rejected-candidate/read-only
   * stages must never allow drag. */
  editable?: boolean;
  /** Backend-verified violations for the CURRENT layout (draft or
   * verified) — rendered directly; never invented client-side (section 6). */
  violations?: ConstraintViolation[];
  /** Called with FACTORY-space coordinates once a drag ends — the parent
   * decides what to do with it (update the draft, call /layout/validate).
   * This component never mutates a layout itself. */
  onMoveMachine?: (machineId: string, x: number, y: number) => void;
  /** Phase 10 — audience. */
  presentation?: "EXECUTIVE" | "ENGINEERING";
}

// px per metre — fixed, deliberately not prematurely tunable (Phase 6B
// section 13). Exported so the Phase 8C playback overlay can render at the
// exact same scale without redefining/duplicating it.
export const SCALE = 16;

/* Station label plate geometry. */
const STATION_LABEL_MAX_PX = 92;
const STATION_LABEL_CHAR_PX = 4.5;
const STATION_LABEL_MAX_CHARS = 20;

interface Point {
  x: number;
  y: number;
}

function violationSets(violations: ConstraintViolation[]) {
  const errorMachines = new Set<string>();
  const warningMachines = new Set<string>();
  const errorZones = new Set<string>();
  const warningZones = new Set<string>();
  for (const v of violations) {
    const machineSet = v.severity === "ERROR" ? errorMachines : warningMachines;
    const zoneSet = v.severity === "ERROR" ? errorZones : warningZones;
    v.machine_ids.forEach((id) => machineSet.add(id));
    v.zone_ids.forEach((id) => zoneSet.add(id));
  }
  return { errorMachines, warningMachines, errorZones, warningZones };
}

function zoneStyle(zoneType: LayoutZone["zone_type"]): { fill: string; stroke: string } {
  switch (zoneType) {
    case "AISLE":
      return { fill: "rgba(79, 179, 255, 0.10)", stroke: "rgba(79, 179, 255, 0.55)" };
    case "SAFETY":
      return { fill: "rgba(224, 168, 58, 0.10)", stroke: "rgba(224, 168, 58, 0.55)" };
    case "INPUT":
    case "OUTPUT":
      return { fill: "rgba(53, 195, 122, 0.10)", stroke: "rgba(53, 195, 122, 0.55)" };
    case "RESERVED":
    default:
      return { fill: "rgba(147, 160, 176, 0.10)", stroke: "rgba(147, 160, 176, 0.55)" };
  }
}

export function FactoryWorkspace({
  factory,
  layout,
  selectedMachineId,
  highlightedMachineIds,
  isRejectedCandidate,
  bottleneckMachineId,
  onSelectMachine,
  editable = false,
  violations = [],
  onMoveMachine,
  presentation = "ENGINEERING",
}: FactoryWorkspaceProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const groupRef = useRef<SVGGElement>(null);
  const dragOffsetRef = useRef<Point>({ x: 0, y: 0 });
  const [dragPreview, setDragPreview] = useState<{ machineId: string; x: number; y: number } | null>(null);

  if (!factory) {
    return (
      <div className="factory-workspace" data-testid="factory-workspace">
        <p className="fm-empty">No factory loaded.</p>
      </div>
    );
  }

  if (!layout) {
    return <FlowDiagramFallback factory={factory} selectedMachineId={selectedMachineId} highlightedMachineIds={highlightedMachineIds} bottleneckMachineId={bottleneckMachineId} isRejectedCandidate={isRejectedCandidate} onSelectMachine={onSelectMachine} />;
  }

  const { errorMachines, warningMachines, errorZones, warningZones } = violationSets(violations);
  const machineById = new Map(factory.machines.map((m) => [m.id, m]));

  // Phase 12 §10: route order + the segments that draw it
  //
  // `stageIndexById` numbers the stations the way the product actually
  // travels through them; `routeSegments` are the straight links between
  // consecutive placed stations. Both are derived from
  // `factory.products[0].route` (through the same helper the no-layout
  // fallback diagram uses) — never from where a station happens to sit on
  // the floor, so an L-shaped or reversed line still reads in the right
  // order. A station with no placement contributes no segment rather than
  // being connected to a guessed position.
  const placementById = new Map((layout?.placements ?? []).map((pl) => [pl.machine_id, pl]));
  const routeIds = orderedRouteMachineIds(factory).filter((id) => placementById.has(id));
  const stageIndexById = new Map(routeIds.map((id, i) => [id, i + 1]));
  const routeSegments: { fromId: string; toId: string; x1: number; y1: number; x2: number; y2: number }[] = [];
  for (let i = 0; i < routeIds.length - 1; i += 1) {
    const from = placementById.get(routeIds[i]);
    const to = placementById.get(routeIds[i + 1]);
    if (!from || !to) continue;
    routeSegments.push({
      fromId: routeIds[i],
      toId: routeIds[i + 1],
      x1: from.x * SCALE,
      y1: from.y * SCALE,
      x2: to.x * SCALE,
      y2: to.y * SCALE,
    });
  }

  function toFactoryPoint(clientX: number, clientY: number): Point {
    const group = groupRef.current;
    const svg = svgRef.current;
    if (!group || !svg) return { x: 0, y: 0 };
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const ctm = group.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    // The group's own transform (scale(1,-1) translate(...), see the <g>
    // below) carries no SCALE factor — only child coordinates are
    // pre-multiplied by SCALE (e.g. footprint points at p.x * SCALE). So
    // the inverse-CTM point here comes back in SCALE'd px units, NOT
    // factory metres; every real-mouse drag was ~SCALE(16)x too sensitive
    // before this divide was added (found via real-browser drag testing,
    // Phase 6C.1 2D regression — a machine dragged a few px instantly
    // landed hundreds of "metres" out of bounds).
    const local = pt.matrixTransform(ctm.inverse());
    return { x: local.x / SCALE, y: local.y / SCALE };
  }

  function handlePointerDown(e: ReactPointerEvent<SVGGElement>, placement: MachinePlacement) {
    if (!editable || !onMoveMachine) return;
    e.stopPropagation();
    onSelectMachine(placement.machine_id);
    const factoryPoint = toFactoryPoint(e.clientX, e.clientY);
    dragOffsetRef.current = { x: factoryPoint.x - placement.x, y: factoryPoint.y - placement.y };
    setDragPreview({ machineId: placement.machine_id, x: placement.x, y: placement.y });
    const target = e.target as Element;
    // Not every environment implements pointer capture (e.g. jsdom in
    // tests) — guard defensively rather than assume it's always present.
    // The call itself can also throw (NotFoundError) if the browser has no
    // works via direct listeners on this element without capture.
    if (typeof target.setPointerCapture === "function") {
      try {
        target.setPointerCapture(e.pointerId);
      } catch {
        // No active pointer to capture — drag still proceeds normally.
      }
    }
  }

  function handlePointerMove(e: ReactPointerEvent<SVGGElement>) {
    if (!dragPreview) return;
    const factoryPoint = toFactoryPoint(e.clientX, e.clientY);
    setDragPreview({
      machineId: dragPreview.machineId,
      x: factoryPoint.x - dragOffsetRef.current.x,
      y: factoryPoint.y - dragOffsetRef.current.y,
    });
  }

  function handlePointerUp() {
    if (!dragPreview || !onMoveMachine) return;
    onMoveMachine(dragPreview.machineId, dragPreview.x, dragPreview.y);
    setDragPreview(null);
  }

  return (
    <div className="factory-workspace" data-testid="factory-workspace">
      {isRejectedCandidate && (
        <p className="factory-workspace__notice" data-testid="workspace-rejected-candidate-notice">
          Rejected candidate — this geometry was evaluated but never accepted into the factory's history.
        </p>
      )}

      {/* Phase 12 §10 — the plan was drawn at a fixed
          `factory.width * SCALE` px and left to overflow. In the Executive
          twin panel that meant an 800px drawing sitting in a 1100px box:
          stations rendered small in the left two thirds with dead space
          beside them, and in the narrower Engineering pane the same fixed
          size produced a horizontal scrollbar inside the canvas.

          A viewBox with the identical extent makes the drawing SCALE to
          its container while keeping every internal coordinate exactly as
          it was. `preserveAspectRatio` is left at its default
          (xMidYMid meet) so the floor plan is never distorted — a
          stretched factory would misrepresent real geometry.

          Drag is unaffected: `screenToFactory` converts through the SVG's
          own `getScreenCTM().inverse()`, which already accounts for
          viewBox scaling, so the mapping stays correct at any rendered
          size rather than being re-derived from a hardcoded px factor. */}
      <svg
        ref={svgRef}
        role="img"
        aria-label="Factory floor plan"
        viewBox={`0 0 ${factory.width * SCALE + 4} ${factory.length * SCALE + 4}`}
        data-testid="factory-workspace-svg"
      >
        <defs>
          <pattern id="fm-generic-hatch" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
            <rect width="6" height="6" fill="var(--fm-panel)" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--fm-limiting)" strokeWidth="2" />
          </pattern>
          <pattern id="fm-proxy-hatch" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
            <rect width="6" height="6" fill="var(--fm-panel)" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--fm-warn)" strokeWidth="2" />
          </pattern>
          <pattern id="fm-missing-hatch" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
            <rect width="6" height="6" fill="var(--fm-panel)" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--fm-text-dim)" strokeWidth="1.5" strokeDasharray="1.5,1.5" />
          </pattern>
          <marker
            id="fm-route-arrow"
            viewBox="0 0 8 8"
            refX="7"
            refY="4"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L8,4 L0,8 z" fill="var(--fm-flow)" fillOpacity="0.75" />
          </marker>
        </defs>

        {/* Flip Y for display only — see module docstring. */}
        <g ref={groupRef} data-testid="factory-workspace-group" transform={`scale(1,-1) translate(2, ${-(factory.length * SCALE) - 2})`}>
          {/* Factory boundary */}
          <rect
            x={0} y={0} width={factory.width * SCALE} height={factory.length * SCALE}
            fill="none" stroke="var(--fm-border)" strokeWidth={2}
            data-testid="factory-boundary"
          />

          {/* Zones */}
          {[...layout?.aisle_zones ?? [], ...layout?.reserved_zones ?? []].map((zone) => {
            const style = zoneStyle(zone.zone_type);
            const isErrorZone = errorZones.has(zone.id);
            const isWarnZone = warningZones.has(zone.id);
            const corners = zoneRectangle(zone).map((p) => ({ x: p.x * SCALE, y: p.y * SCALE }));
            return (
              <g key={zone.id} data-testid={`workspace-zone-${zone.id}`}>
                <polygon
                  points={pointsToSvgPolygon(corners)}
                  fill={style.fill}
                  stroke={isErrorZone ? "var(--fm-bad)" : isWarnZone ? "var(--fm-warn)" : style.stroke}
                  strokeWidth={isErrorZone || isWarnZone ? 2.5 : 1.5}
                  strokeDasharray={zone.zone_type === "AISLE" ? undefined : "4,3"}
                />
                <text
                  x={corners[0].x + 4} y={-(corners[0].y + 6)}
                  fontSize={9} fill="var(--fm-text-dim)" transform="scale(1,-1)"
                >
                  {presentation === "ENGINEERING" ? `${zone.zone_type}: ${zone.name}` : zone.name}
                </text>
              </g>
            );
          })}

          {/* Phase 12 §10 — the production ROUTE, drawn. */}
          {routeSegments.length > 0 && (
            <g data-testid="workspace-route-flow" pointerEvents="none">
              {routeSegments.map((segment) => (
                <line
                  key={`${segment.fromId}-${segment.toId}`}
                  x1={segment.x1} y1={segment.y1}
                  x2={segment.x2} y2={segment.y2}
                  stroke="var(--fm-flow)"
                  strokeWidth={1.5}
                  strokeOpacity={0.55}
                  strokeDasharray="5,4"
                  markerEnd="url(#fm-route-arrow)"
                />
              ))}
            </g>
          )}

          {/* Machines */}
          {(layout?.placements ?? []).map((placement) => {
            const machine = machineById.get(placement.machine_id);
            if (!machine) return null;
            const isDragging = dragPreview?.machineId === placement.machine_id;
            const effectivePlacement = isDragging ? { ...placement, x: dragPreview!.x, y: dragPreview!.y } : placement;

            const footprint = machineFootprint(machine, effectivePlacement).map((p) => ({ x: p.x * SCALE, y: p.y * SCALE }));
            const envelope = machineSafetyEnvelope(machine, effectivePlacement).map((p) => ({ x: p.x * SCALE, y: p.y * SCALE }));

            const isSelected = placement.machine_id === selectedMachineId;
            const isBottleneck = placement.machine_id === bottleneckMachineId;
            const isHighlighted = highlightedMachineIds.includes(placement.machine_id);
            const isErrorMachine = errorMachines.has(placement.machine_id);
            const isWarnMachine = warningMachines.has(placement.machine_id);

            let dragOverlapHint = false;
            if (isDragging) {
              for (const other of layout?.placements ?? []) {
                if (other.machine_id === placement.machine_id) continue;
                const otherMachine = machineById.get(other.machine_id);
                if (!otherMachine) continue;
                if (previewOverlap(machineFootprint(machine, effectivePlacement), machineFootprint(otherMachine, other))) {
                  dragOverlapHint = true;
                  break;
                }
              }
            }

            const strokeColor = isErrorMachine || dragOverlapHint
              ? "var(--fm-bad)"
              : isWarnMachine
                ? "var(--fm-warn)"
                : isBottleneck
                  ? "var(--fm-bad)"
                  : isHighlighted
                    ? "var(--fm-good)"
                    : "var(--fm-border)";

            const kind = assetVisualKind(machine);
            const label = assetLabel(kind);

            return (
              <g
                key={placement.machine_id}
                data-testid={`workspace-node-${placement.machine_id}`}
                data-selected={isSelected || undefined}
                data-dragging={isDragging || undefined}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelectMachine(placement.machine_id);
                }}
                onPointerDown={(e) => handlePointerDown(e, placement)}
                onPointerMove={handlePointerMove}
                onPointerUp={handlePointerUp}
                style={{ cursor: editable && onMoveMachine ? "grab" : "pointer", opacity: isDragging ? 0.75 : 1 }}
              >
                <polygon
                  points={pointsToSvgPolygon(envelope)}
                  fill="none"
                  stroke="var(--fm-text-dim)"
                  strokeDasharray="3,3"
                  strokeOpacity={0.5}
                  data-testid={`workspace-envelope-${placement.machine_id}`}
                />
                <polygon
                  points={pointsToSvgPolygon(footprint)}
                  fill={assetFillId(kind)}
                  stroke={strokeColor}
                  strokeWidth={isSelected ? 3 : 2}
                />
                {/* Phase 12 §10 — the name used to be printed straight
                    onto the diagonal hatch fill, which made every station
                    label unreadable at real size. It now sits BELOW the
                    footprint on its own plate, and the station carries its
                    route position as a numbered disc, so the sequence is
                    legible without opening the 3D view. */}
                {stageIndexById.has(placement.machine_id) && (
                  <g transform="scale(1,-1)" pointerEvents="none">
                    <circle
                      cx={effectivePlacement.x * SCALE}
                      cy={-(effectivePlacement.y * SCALE)}
                      r={9}
                      fill="var(--fm-bg)"
                      stroke={strokeColor}
                      strokeWidth={1.5}
                    />
                    <text
                      x={effectivePlacement.x * SCALE}
                      y={-(effectivePlacement.y * SCALE)}
                      fontSize={10}
                      fontWeight={600}
                      fill="var(--fm-text)"
                      textAnchor="middle"
                      dominantBaseline="central"
                    >
                      {stageIndexById.get(placement.machine_id)}
                    </text>
                  </g>
                )}
                {/* The station's OWN name — see compactStationName for why
                    it is shortened rather than replaced by the identifier,
                    and why the plate is measured rather than fixed. The full
                    name stays in the <title>, so nothing is lost to a
                    reader or to assistive technology. */}
                <g transform="scale(1,-1)" pointerEvents="none">
                  {(() => {
                    const full = machine.name;
                    const short = compactStationName(full, STATION_LABEL_MAX_CHARS);
                    const plate = Math.min(
                      short.length * STATION_LABEL_CHAR_PX + 10,
                      STATION_LABEL_MAX_PX,
                    );
                    return (
                      <>
                        <rect
                          x={effectivePlacement.x * SCALE - plate / 2}
                          y={-(effectivePlacement.y * SCALE) + machine.length * SCALE * 0.5 + 3}
                          width={plate}
                          height={15}
                          rx={3}
                          fill="var(--fm-bg)"
                          fillOpacity={0.85}
                        />
                        <text
                          x={effectivePlacement.x * SCALE}
                          y={-(effectivePlacement.y * SCALE) + machine.length * SCALE * 0.5 + 10.5}
                          fontSize={9}
                          fill="var(--fm-text)"
                          textAnchor="middle"
                          dominantBaseline="middle"
                          data-testid={`workspace-label-${placement.machine_id}`}
                        >
                          <title>{full}</title>
                          {short}
                        </text>
                      </>
                    );
                  })()}
                </g>
                {label && presentation === "ENGINEERING" && (
                  <text
                    x={effectivePlacement.x * SCALE}
                    y={-(effectivePlacement.y * SCALE) + machine.length * SCALE * 0.5 + 24}
                    transform="scale(1,-1)" fontSize={8} fill="var(--fm-warn)" textAnchor="middle"
                  >
                    {label}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}

function orderedRouteMachineIds(factory: Factory): string[] {
  const route = factory.products[0]?.route;
  if (route && route.length > 0) {
    const seen = new Set<string>();
    const ordered: string[] = [];
    for (const step of route) {
      if (!seen.has(step.machine_id)) {
        seen.add(step.machine_id);
        ordered.push(step.machine_id);
      }
    }
    for (const machine of factory.machines) {
      if (!seen.has(machine.id)) {
        seen.add(machine.id);
        ordered.push(machine.id);
      }
    }
    return ordered;
  }
  return factory.machines.map((m) => m.id);
}

/** Fallback for a session that legitimately has NO layout at all (Phase
 * 6A.1: `layout === null` is never fabricated into geometry) — a
 * schematic left-to-right process-flow diagram built from real Factory
 * structure (route order), not a physical floor plan. */
function FlowDiagramFallback({
  factory,
  selectedMachineId,
  highlightedMachineIds,
  bottleneckMachineId,
  isRejectedCandidate,
  onSelectMachine,
}: {
  factory: Factory;
  selectedMachineId: string | null;
  highlightedMachineIds: string[];
  bottleneckMachineId: string | null;
  isRejectedCandidate: boolean;
  onSelectMachine: (machineId: string) => void;
}) {
  const orderedMachineIds = orderedRouteMachineIds(factory);
  return (
    <div className="factory-workspace" data-testid="factory-workspace">
      {isRejectedCandidate && (
        <p className="factory-workspace__notice" data-testid="workspace-rejected-candidate-notice">
          Rejected candidate — this geometry was evaluated but never accepted into the factory's history.
        </p>
      )}
      <p className="factory-workspace__notice" data-testid="workspace-no-layout-notice">
        No floor layout is available for this state — showing process order only. Enter Edit Layout to place
        machines on the floor.
      </p>
      <div className="factory-workspace__flow" data-testid="factory-workspace-flow">
        {orderedMachineIds.map((machineId, index) => {
          const machine = factory.machines.find((m) => m.id === machineId);
          if (!machine) return null;
          const isBottleneck = machineId === bottleneckMachineId;
          const isHighlighted = highlightedMachineIds.includes(machineId);
          const isSelected = machineId === selectedMachineId;
          return (
            <span key={machineId} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {index > 0 && (
                <span className="factory-workspace__connector" aria-hidden="true">
                  →
                </span>
              )}
              <button
                type="button"
                className={[
                  "factory-workspace__node",
                  isBottleneck ? "factory-workspace__node--bottleneck" : "",
                  isHighlighted ? "factory-workspace__node--highlighted" : "",
                  isSelected ? "factory-workspace__node--selected" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                onClick={() => onSelectMachine(machineId)}
                data-testid={`workspace-node-${machineId}`}
              >
                <div className="factory-workspace__node-name" title={machine.name}>
                  {machine.name}
                </div>
                <div className="factory-workspace__node-meta">
                  {machine.process_type} · {machine.cycle_time}s
                  {isBottleneck && " · BOTTLENECK"}
                </div>
              </button>
            </span>
          );
        })}
      </div>
    </div>
  );
}
