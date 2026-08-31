import { ArrowLeft } from "lucide-react";
import { useAppContext } from "../../state/AppContext";
import type { SaveStatus } from "../../state/types";

/** P0 §G — which project is open, and whether it is saved. */
export function ProjectBar() {
  const { state, closeProject } = useAppContext();
  const project = state.project;
  if (!project.id) return null;

  return (
    <div className="project-bar project-bar--standalone" data-testid="project-bar">
      <button
        type="button"
        className="fm-btn-tertiary"
        onClick={closeProject}
        title="Save and return to all projects"
        data-testid="project-bar-all-projects"
      >
        <ArrowLeft size={13} strokeWidth={2} aria-hidden="true" />
        Projects
      </button>
      <span className="project-bar__name" data-testid="project-bar-name">
        {project.name}
      </span>
      <SaveIndicator status={project.saveStatus} error={project.saveError} />
    </div>
  );
}

function SaveIndicator({ status, error }: { status: SaveStatus; error: string | null }) {
  if (status === "IDLE") return null;

  const text =
    status === "SAVING"
      ? "Saving…"
      : status === "SAVED"
        ? "Saved"
        : status === "DIRTY"
          ? "Unsaved changes"
          : `Not saved — ${error ?? "the last save failed"}`;

  return (
    <span
      className={`project-bar__save${status === "ERROR" ? " project-bar__save--error" : ""}`}
      role={status === "ERROR" ? "alert" : "status"}
      data-testid="project-save-status"
      data-status={status}
    >
      {text}
    </span>
  );
}
