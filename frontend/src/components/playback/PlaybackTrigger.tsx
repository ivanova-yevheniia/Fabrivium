import { useAppContext } from "../../state/AppContext";

/** Small "open playback for the stage currently on screen" entry point. */
export function PlaybackTrigger({ label = "▶ Play simulation" }: { label?: string }) {
  const { state, openPlayback } = useAppContext();
  if (!state.session) return null;
  if (state.playback.active) return null;

  return (
    <button
      type="button"
      className="playback-trigger"
      onClick={() => void openPlayback()}
      data-testid="playback-trigger"
    >
      {label}
    </button>
  );
}
