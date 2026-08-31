import { useState } from "react";
import { BookOpen, FolderOpen, Loader2, Plus, Trash2 } from "lucide-react";
import { useAppContext } from "../../state/AppContext";

/** P0 §A — the workspace Fabrivium opens into. */
export function ProjectLanding() {
  const { state, newProject, openProject, openExampleProject, removeProject } = useAppContext();
  const project = state.project;
  const [name, setName] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);

  const busy = project.opening;

  function create() {
    const trimmed = name.trim();
    if (!trimmed) return;
    setName("");
    void newProject(trimmed);
  }

  return (
    <div className="start-screen" data-testid="project-landing">
      <div className="start-screen__inner">
        {/* The proposition, in the order a reader takes it in: the name,
            what the product does end to end, then how. Deliberately no
            marketing paragraph and no "AI-powered" opener — the claim being
            made here is engineering verification, and AI is a technology
            inside it rather than the thing on offer. */}
        <header className="start-screen__head">
          <h1 className="start-screen__title" data-testid="brand-wordmark">
            Fabrivium
          </h1>
          <p className="start-screen__tagline">
            From product requirements to simulation-verified production.
          </p>
          <p className="start-screen__subtagline">
            Design, simulate, compare and hand off manufacturing concepts in one traceable
            engineering workflow.
          </p>
        </header>

        <section className="project-new" data-testid="project-new">
          <label className="fm-label" htmlFor="project-name-input">
            New project
          </label>
          <div className="project-new__row">
            <input
              id="project-name-input"
              className="fm-input project-new__input"
              type="text"
              value={name}
              placeholder="e.g. Controller line — Plant 2"
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  create();
                }
              }}
              data-testid="project-name-input"
            />
            <button
              type="button"
              className="fm-btn-primary fm-btn--auto"
              onClick={create}
              disabled={busy || !name.trim()}
              data-testid="project-create"
            >
              {busy ? (
                <Loader2 size={14} strokeWidth={2} aria-hidden="true" className="equipment__spin" />
              ) : (
                <Plus size={14} strokeWidth={2.2} aria-hidden="true" />
              )}
              Create project
            </button>
          </div>
        </section>

        <section className="project-recent" data-testid="project-recent">
          <p className="fm-label start-screen__prompt">Recent projects</p>

          {project.listing && project.recent.length === 0 && (
            <p className="fm-empty" data-testid="project-list-loading">
              Looking for your projects…
            </p>
          )}

          {!project.listing && project.recent.length === 0 && (
            /* The empty state names the two things that can be done from
               here rather than showing an empty box with a shrug. */
            <p className="fm-empty" data-testid="project-empty">
              No projects yet. Name one above to begin, or open the example project below to see a
              finished one.
            </p>
          )}

          {project.recent.length > 0 && (
            <ul className="project-list">
              {project.recent.map((summary) => (
                <li key={summary.project_id} className="project-list__row">
                  <button
                    type="button"
                    className="project-list__open"
                    onClick={() => void openProject(summary.project_id)}
                    disabled={busy}
                    data-testid={`project-open-${summary.project_id}`}
                  >
                    <span className="project-list__icon" aria-hidden="true">
                      <FolderOpen size={16} strokeWidth={1.8} />
                    </span>
                    <span className="project-list__body">
                      <span className="project-list__name">
                        {summary.name}
                        {summary.is_example && (
                          <span className="project-list__example" data-testid="project-example-tag">
                            example
                          </span>
                        )}
                      </span>
                      <span className="project-list__meta">
                        {summary.product_name ? `${summary.product_name} · ` : ""}
                        last edited {formatWhen(summary.updated_at)}
                      </span>
                    </span>
                  </button>

                  {confirmingDelete === summary.project_id ? (
                    <span className="project-list__confirm">
                      <button
                        type="button"
                        className="fm-btn-tertiary"
                        onClick={() => {
                          setConfirmingDelete(null);
                          void removeProject(summary.project_id);
                        }}
                        data-testid={`project-delete-confirm-${summary.project_id}`}
                      >
                        Delete permanently
                      </button>
                      <button
                        type="button"
                        className="fm-btn-tertiary"
                        onClick={() => setConfirmingDelete(null)}
                      >
                        Keep
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="project-list__delete"
                      aria-label={`Delete ${summary.name}`}
                      onClick={() => setConfirmingDelete(summary.project_id)}
                      data-testid={`project-delete-${summary.project_id}`}
                    >
                      <Trash2 size={14} strokeWidth={1.8} aria-hidden="true" />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="project-example">
          <button
            type="button"
            className="start-option project-example__button"
            onClick={() => void openExampleProject()}
            disabled={busy}
            data-testid="project-open-example"
          >
            <span className="start-option__icon" aria-hidden="true">
              <BookOpen size={20} strokeWidth={1.8} />
            </span>
            <span className="start-option__body">
              <span className="start-option__title">Explore the example project</span>
              <span className="start-option__detail">
                A compact electronics controller, with the bundled example specification already
                loaded. Everything in it is labelled as example data.
              </span>
            </span>
          </button>
        </section>

        {project.error && (
          <p className="concept-error" data-testid="project-error">
            {project.error}
          </p>
        )}
      </div>
    </div>
  );
}

/** A timestamp an engineer can read at a glance. */
function formatWhen(iso: string): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "recently";

  const seconds = Math.max(0, (Date.now() - then.getTime()) / 1000);
  if (seconds < 90) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} minutes ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} hours ago`;
  if (seconds < 7 * 86400) return `${Math.round(seconds / 86400)} days ago`;
  return then.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
