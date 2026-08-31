import { useContext } from "react";
import { AlertTriangle, CheckCircle2, CircleDashed, RefreshCw } from "lucide-react";
import { AppContext } from "../../state/AppContext";
import { staleEntry, statusOf } from "../../api/projects";
import type { Artifact, ArtifactStatus, StaleReport } from "../../api/projects";

/** P0 §F — what a result's status is, and why. */

/** The current project's staleness report, or null outside a project. */
function useStaleness(): StaleReport | null {
  return useContext(AppContext)?.state.project.staleness ?? null;
}

const LABEL: Record<ArtifactStatus, string> = {
  CURRENT: "Verified",
  STALE: "Needs revalidation",
  UNVERIFIED: "Not verified",
};

const ICON: Record<ArtifactStatus, typeof CheckCircle2> = {
  CURRENT: CheckCircle2,
  STALE: AlertTriangle,
  UNVERIFIED: CircleDashed,
};

/** The badge. Reads the project's staleness report; decides nothing. */
export function EvidenceBadge({ artifact, label }: { artifact: Artifact; label?: string }) {
  const status = statusOf(useStaleness(), artifact);
  const Icon = ICON[status];

  return (
    <span
      className={`evidence-badge evidence-badge--${status.toLowerCase()}`}
      data-testid={`evidence-${artifact}`}
      data-status={status}
    >
      <Icon size={11} strokeWidth={2.4} aria-hidden="true" />
      {label ?? LABEL[status]}
    </span>
  );
}

/** The cause and the cure, beside the thing that went stale. */
export function EvidenceNote({
  artifact,
  onAct,
  actionLabel,
}: {
  artifact: Artifact;
  /** Runs the named action. */
  onAct?: () => void;
  actionLabel?: string;
}) {
  const entry = staleEntry(useStaleness(), artifact);
  if (!entry) return null;

  return (
    <div className="evidence-note" role="status" data-testid={`evidence-note-${artifact}`}>
      <p className="evidence-note__title">Inputs changed since this result was verified.</p>
      {entry.reasons.length > 0 && (
        <ul className="evidence-note__reasons" data-testid={`evidence-reasons-${artifact}`}>
          {entry.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      {onAct ? (
        <button
          type="button"
          className="fm-btn-secondary fm-btn--auto evidence-note__action"
          onClick={onAct}
          data-testid={`evidence-action-${artifact}`}
        >
          <RefreshCw size={13} strokeWidth={2.2} aria-hidden="true" />
          {actionLabel ?? entry.action}
        </button>
      ) : (
        <p className="evidence-note__reasons" data-testid={`evidence-action-text-${artifact}`}>
          {entry.action}.
        </p>
      )}
    </div>
  );
}
