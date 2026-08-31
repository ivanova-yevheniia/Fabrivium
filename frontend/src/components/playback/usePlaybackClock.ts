import { useEffect, useRef } from "react";
import { useAppContext } from "../../state/AppContext";

/** How many real seconds the default (1x) speed compresses a full
 * simulated horizon into (Phase 8C section 17: "roughly 20-40 seconds").
 * Speed 5x/20x are multiples of this, never real (1:1) wall-clock time —
 * a 16-hour shift is never literally watched for 16 hours. */
const DEFAULT_PLAYBACK_SECONDS = 30;

/** Throttles playback ticks to ~30/s — smooth enough for the eye, cheap
 * enough not to fight the WebGL frame budget with a state dispatch every
 * animation frame. */
const MIN_DISPATCH_INTERVAL_MS = 33;

/** Drives `playback.simTime` forward while `playback.playing` is true, via
 * requestAnimationFrame. Speed/pause/reset/seek only ever change WHICH
 * simTime is shown — never anything simulated (section 15: "playback speed
 * affects only visualization"). Scrubbing/seeking always goes through the
 * same `stateAt(simTime)` lookup (see traceIndex.ts), so jumping backward
 * is exact, not an accumulated approximation. */
export function usePlaybackClock(): void {
  const { state, seekPlayback } = useAppContext();
  const { playback } = state;

  const simTimeRef = useRef(playback.simTime);
  const rafIdRef = useRef<number | null>(null);
  const lastWallRef = useRef<number | null>(null);
  const lastDispatchRef = useRef<number | null>(null);

  // While NOT playing, the ref just mirrors external changes (seek, reset,
  // marker click, Before/After stage switch).
  useEffect(() => {
    if (!playback.playing) simTimeRef.current = playback.simTime;
  }, [playback.simTime, playback.playing]);

  useEffect(() => {
    if (!playback.playing || !playback.trace) {
      lastWallRef.current = null;
      lastDispatchRef.current = null;
      return;
    }
    const horizon = playback.trace.horizon_seconds;
    const simSecondsPerRealSecond = (horizon / DEFAULT_PLAYBACK_SECONDS) * playback.speed;

    function frame(nowMs: number) {
      if (lastWallRef.current == null) lastWallRef.current = nowMs;
      const deltaReal = (nowMs - lastWallRef.current) / 1000;
      lastWallRef.current = nowMs;
      simTimeRef.current = Math.min(horizon, simTimeRef.current + deltaReal * simSecondsPerRealSecond);

      if (lastDispatchRef.current == null || nowMs - lastDispatchRef.current >= MIN_DISPATCH_INTERVAL_MS) {
        lastDispatchRef.current = nowMs;
        seekPlayback(simTimeRef.current);
      }
      if (simTimeRef.current < horizon) {
        rafIdRef.current = requestAnimationFrame(frame);
      } else {
        seekPlayback(horizon); // guarantee the final dispatch always lands exactly on the horizon
      }
    }
    rafIdRef.current = requestAnimationFrame(frame);
    return () => {
      if (rafIdRef.current != null) cancelAnimationFrame(rafIdRef.current);
      lastWallRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playback.playing, playback.trace, playback.speed]);
}
