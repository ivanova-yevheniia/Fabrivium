import { Html, useGLTF } from "@react-three/drei";
import { Component, Suspense, useMemo } from "react";
import type { ReactNode } from "react";
import * as THREE from "three";

import type { Machine, MachinePlacement } from "../../api/types";
import {
  machineBoxDimensions,
  placementToThreePosition,
  rotationDegToThreeY,
} from "../../utils/geometry3d";
import type { Box3Dimensions } from "../../utils/geometry3d";
import { resolveMachineAsset } from "../../utils/assetResolution";
import { assetLabel, assetVisualKind, proxyFamilyParts } from "./machineVisual";
import type { ProxyPart } from "./machineVisual";
import { STATION_ACCENTS } from "./FlowScene3D";

/** Catches failed GLTF loading and falls back to the procedural proxy. */
class GltfErrorBoundary extends Component<
  {
    fallback: ReactNode;
    children: ReactNode;
  },
  {
    hasError: boolean;
  }
> {
  state = {
    hasError: false,
  };

  static getDerivedStateFromError() {
    return {
      hasError: true,
    };
  }

  render() {
    return this.state.hasError ? this.props.fallback : this.props.children;
  }
}

function ProxyPartMesh({
  part,
  color,
  opacity,
}: {
  part: ProxyPart;
  color: string;
  opacity: number;
}) {
  return (
    <mesh
      castShadow
      receiveShadow
      position={part.position}
      rotation={part.rotation ?? [0, 0, 0]}
    >
      {part.shape === "box" ? (
        <boxGeometry args={part.args as [number, number, number]} />
      ) : (
        <cylinderGeometry
          args={part.args as [number, number, number, number]}
        />
      )}

      <meshStandardMaterial
        color={color}
        transparent={opacity < 1}
        opacity={opacity}
        roughness={0.6}
        metalness={0.15}
      />
    </mesh>
  );
}

/**
 * Fallback visual used whenever there is no loaded GLB (proxy, missing
 * asset, or a real EXACT_CAD model still mid-Suspense). process_type picks
 * a lightweight industrial silhouette (see machineVisual.proxyFamilyParts)
 * so the placeholder reads as "roughly this kind of machine" instead of a
 * raw debug cube. The asset's kind (exact/proxy/missing) only ever
 * controls color/opacity — never the engineering footprint.
 */
function ProxyBox({
  dims,
  kind,
  processType,
}: {
  dims: Box3Dimensions;
  kind: ReturnType<typeof assetVisualKind>;
  processType: string;
}) {
  const color =
    kind === "proxy"
      ? "#e0a83a"
      : kind === "missing"
        ? "#6b7785"
        : "#8fa6bf"; // exact/generic — a real GLB is loading (or failed) for this slot

  const opacity =
    kind === "exact"
      ? 1
      : kind === "generic"
        ? 0.75
        : kind === "proxy"
          ? 0.62
          : 0.4;

  const parts = proxyFamilyParts(processType, dims);

  return (
    <>
      {parts.map((part, index) => (
        <ProxyPartMesh
          // eslint-disable-next-line react/no-array-index-key
          key={index}
          part={part}
          color={color}
          opacity={opacity}
        />
      ))}
    </>
  );
}

/** Loads an actual GLB / GLTF visual asset. */
function GltfMachine({
  url,
  dims,
  tint,
}: {
  url: string;
  dims: Box3Dimensions;
  /** Phase 10 — station-identity accent, or null to leave the model exactly as authored. */
  tint?: string | null;
}) {
  const { scene } = useGLTF(url);

  /** ONE memo builds the whole renderable object: clone, then tint. */
  const model = useMemo(() => {
    const cloned = scene.clone(true);
    if (!tint) return cloned;

    const color = new THREE.Color(tint);
    cloned.traverse((child) => {
      const mesh = child as THREE.Mesh;
      if (!mesh.isMesh || !mesh.material) return;
      const tintOne = (material: THREE.Material): THREE.Material => {
        const copy = material.clone() as THREE.MeshStandardMaterial;
        // Multiply rather than replace, so whatever shading the atlas does
        // contribute is preserved and only pushed toward the accent.
        if (copy.color) copy.color.multiply(color);
        return copy;
      };
      mesh.material = Array.isArray(mesh.material)
        ? mesh.material.map(tintOne)
        : tintOne(mesh.material);
    });
    return cloned;
  }, [scene, tint]);

  /** Fit-to-footprint, measured in the model's OWN space. */
  const { scale, offset } = useMemo(() => {
    // Measured on a throwaway clone: `model` may already be mounted, and a
    // mounted object measures in world space (see above).
    const measured = model.clone(true);
    const box = new THREE.Box3().setFromObject(measured);

    const size = new THREE.Vector3();
    box.getSize(size);

    const center = new THREE.Vector3();
    box.getCenter(center);

    const factor = Math.min(
      size.x > 0 ? dims.width / size.x : 1,
      size.y > 0 ? dims.height / size.y : 1,
      size.z > 0 ? dims.length / size.z : 1,
    );

    return {
      scale: Number.isFinite(factor) && factor > 0 ? factor : 1,
      offset: center,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, dims.width, dims.height, dims.length]);

  return (
    <primitive
      // Keyed on the object itself: a new clone is always a new mount, so a
      // stale object can never be left parented somewhere it does not belong.
      key={model.uuid}
      object={model}
      scale={scale}
      position={[
        -offset.x * scale,
        -offset.y * scale,
        -offset.z * scale,
      ]}
    />
  );
}

export interface Machine3DProps {
  machine: Machine;
  placement: MachinePlacement;

  selected: boolean;
  highlighted: boolean;
  isBottleneck: boolean;

  isErrorViolation: boolean;
  isWarningViolation: boolean;

  /** Phase 8C — live playback state, only set while a trace is loaded and playing/scrubbing. */
  playbackBlocked?: boolean;
  playbackProcessing?: boolean;
  /** Live queue depth for this machine at the current playback instant —
   * 0/undefined renders no badge at all (bounded, section 31: no floating
   * UI unless there is something to say). */
  playbackQueueLength?: number;

  /** Phase 10 — whether to draw the machine's own name + asset-kind badge above it. */
  showAssetBadge?: boolean;

  onSelect: (machineId: string) => void;

  /** Phase 12.1 — layout editing in 3D. */
  onDragStart?: (machineId: string) => void;
}

/** Renders one physical Fabrivium machine. */
export function Machine3D({
  machine,
  placement,
  selected,
  highlighted,
  isBottleneck,
  isErrorViolation,
  isWarningViolation,
  playbackBlocked = false,
  playbackProcessing = false,
  playbackQueueLength = 0,
  showAssetBadge = true,
  onSelect,
  onDragStart,
}: Machine3DProps) {
  const dims = machineBoxDimensions(machine);

  // Everything the label could contain. When all of it is absent the label
  // itself is absent too — see the note at the <Html> below.
  const hasLabelContent = showAssetBadge || playbackBlocked || playbackQueueLength > 0;

  const pos = placementToThreePosition(
    placement,
    dims.height,
  );

  const rotY = rotationDegToThreeY(
    placement.rotation_deg,
  );

  const kind = assetVisualKind(machine);

  // Both EXACT and GENERIC are real, loadable models (see assetResolution.ts
  // — the LIBRARY/manifest fix); PROXY/MISSING always fall back to the
  // procedural silhouette below.
  const resolution = resolveMachineAsset(machine);
  const gltfUrl =
    kind === "exact" || kind === "generic"
      ? resolution.assetUri
      : null;

  const label = assetLabel(kind);

  // Explicit precedence (Phase 8C section 13), documented rather than left
  // to accidental ordering: constraint ERROR > live BLOCKED > WARNING >
  // historical BOTTLENECK > live PROCESSING > action HIGHLIGHT > SELECTED.
  // Live playback facts (blocked/processing) sit above the static
  // bottleneck highlight because "what is happening right now" is a more
  // urgent signal during a playback session than "which stage is
  // congested overall".
  const outlineColor = isErrorViolation
    ? "#e0563f"
    : playbackBlocked
      ? "#e0563f"
      : isWarningViolation
        ? "#e0a83a"
        : isBottleneck
          ? "#e0563f"
          : playbackProcessing
            ? "#4fb3ff"
            : highlighted
              ? "#35c37a"
              : selected
                ? "#4fb3ff"
                : null;

  return (
    <group
      position={[pos.x, pos.y, pos.z]}
      rotation={[0, rotY, 0]}
      name={`machine3d-${machine.id}`}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(machine.id);
      }}
      onPointerDown={
        onDragStart
          ? (event) => {
              event.stopPropagation();
              // Select first, so the inspector and the rotation controls
              // follow the machine being moved — the same order the 2D
              // canvas uses.
              onSelect(machine.id);
              // Only that a drag began — the scene calibrates the grab
              // offset against the floor plane, because this event's point
              // lies on the machine's surface, not on the floor.
              onDragStart(machine.id);
            }
          : undefined
      }
    >
      {gltfUrl ? (
        <GltfErrorBoundary
          fallback={
            <ProxyBox
              dims={dims}
              kind={kind}
              processType={machine.process_type}
            />
          }
        >
          <Suspense
            fallback={
              <ProxyBox
                dims={dims}
                kind={kind}
                processType={machine.process_type}
              />
            }
          >
            <GltfMachine
              url={gltfUrl}
              dims={dims}
              tint={STATION_ACCENTS[resolution.requestedCategory]}
            />
          </Suspense>
        </GltfErrorBoundary>
      ) : (
        <ProxyBox
          dims={dims}
          kind={kind}
          processType={machine.process_type}
        />
      )}

      {/*
        Phase 10 — machine STATUS is now a halo on the floor, not a wireframe
        cage around the machine.

        The cage (a 1.06x wireframe box) was legible as "this one is
        highlighted" but it read as a debug bounding box, and with several
        states live at once the scene looked like a wireframe test harness
        rather than a factory. A ring at the machine's base carries exactly
        the same one fact, in the same colour, with the same precedence — and
        it stops occluding the model it is drawing attention to, which
        matters most for the bottleneck, the object viewers look at hardest.

        The mesh keeps its `machine3d-outline-` name so anything selecting on
        it (tests, future camera work) is unaffected.
      */}
      {outlineColor && (
        <group name={`machine3d-outline-${machine.id}`} position={[0, -dims.height / 2 + 0.02, 0]}>
          <mesh rotation={[-Math.PI / 2, 0, 0]}>
            <ringGeometry args={[Math.max(dims.width, dims.length) * 0.62, Math.max(dims.width, dims.length) * 0.78, 40]} />
            <meshBasicMaterial color={outlineColor} transparent opacity={0.95} />
          </mesh>
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.004, 0]}>
            <circleGeometry args={[Math.max(dims.width, dims.length) * 0.78, 40]} />
            <meshBasicMaterial color={outlineColor} transparent opacity={0.14} />
          </mesh>
        </group>
      )}

      {/* Audit §5 — nothing is rendered when there is nothing to say. */}
      {hasLabelContent && (
      <Html
        center
        distanceFactor={12}
        position={[
          0,
          dims.height / 2 + 0.4,
          0,
        ]}
      >
        <div
          className="machine3d-label"
          data-testid={`machine3d-label-${machine.id}`}
        >
          {/* §2 — the machine's own name, which we are holding, rather than
              a string reverse-engineered from its id. */}
          {showAssetBadge && machine.name}

          {showAssetBadge && label && (
            <span
              className="fm-badge fm-badge--unknown"
              style={{
                marginLeft: 4,
              }}
            >
              {label}
            </span>
          )}

          {playbackBlocked && (
            <span className="fm-badge fm-badge--bad" style={{ marginLeft: 4 }} data-testid={`machine3d-blocked-${machine.id}`}>
              BLOCKED
            </span>
          )}
          {playbackQueueLength > 0 && (
            <span className="fm-badge fm-badge--unknown" style={{ marginLeft: 4 }} data-testid={`machine3d-queue-${machine.id}`}>
              {playbackQueueLength} waiting
            </span>
          )}
        </div>
      </Html>
      )}
    </group>
  );
}