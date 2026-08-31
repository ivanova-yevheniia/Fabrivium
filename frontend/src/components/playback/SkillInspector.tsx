import { useEffect, useState, useSyncExternalStore } from "react";
import { Activity, Boxes, Cpu, FileWarning, Wrench } from "lucide-react";
import { apiGet } from "../../api/client";
import { getSkillExecutions, subscribeToSkillTrace } from "../../api/skillTrace";

/** Architecture → Skills. */

type SkillCategory =
  | "UNDERSTANDING"
  | "PLANNING"
  | "ESTIMATION"
  | "VALIDATION"
  | "SIMULATION"
  | "OPTIMIZATION"
  | "DISCOVERY"
  | "INTEGRATION";

interface SkillSummary {
  id: string;
  version: string;
  qualified_id: string;
  name: string;
  description: string;
  category: SkillCategory;
  capabilities: string[];
  prerequisites: string[];
  input_types: string[];
  output_types: string[];
  supported_inputs: string[];
  deterministic: boolean;
  uses_llm: boolean;
  uses_external_data: boolean;
  side_effects: string[];
  execution_mode: string;
  namespace: string;
  owner: string;
  enabled: boolean;
}

interface WorkflowSummary {
  id: string;
  name: string;
  description: string;
  skills: string[];
}

interface SkillListResponse {
  skills: SkillSummary[];
  workflows: WorkflowSummary[];
}

const CATEGORY_ORDER: SkillCategory[] = [
  "UNDERSTANDING",
  "PLANNING",
  "ESTIMATION",
  "VALIDATION",
  "SIMULATION",
  "OPTIMIZATION",
  "DISCOVERY",
  "INTEGRATION",
];

const SIDE_EFFECT_LABEL: Record<string, string> = {
  NONE: "no side effects",
  READS_LOCAL_DATA: "reads bundled data",
  WRITES_FILE: "writes a file",
  CONTROLS_EXTERNAL_TOOL: "drives an external tool",
  NETWORK_CALL: "calls a network service",
};

export function SkillInspector() {
  const [data, setData] = useState<SkillListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiGet<SkillListResponse>("/skills")
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch(() => {
        if (!cancelled) setError("The skill registry could not be read.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <p className="pipeline__detail" data-testid="skill-inspector-error">
        {error}
      </p>
    );
  }
  if (!data) return null;

  const byCategory = CATEGORY_ORDER.map((category) => ({
    category,
    skills: data.skills.filter((skill) => skill.category === category),
  })).filter((group) => group.skills.length > 0);

  const deterministic = data.skills.filter((s) => s.deterministic).length;

  return (
    <details className="skills" data-testid="skill-inspector">
      <summary data-testid="skill-inspector-toggle">
        <Boxes size={14} strokeWidth={2} aria-hidden="true" />
        {data.skills.length} engineering skills across {byCategory.length} categories
      </summary>

      <div className="skills__body">
        <p className="pipeline__detail" data-testid="skill-inspector-summary">
          {deterministic} of {data.skills.length} are fully deterministic. New company or
          domain skills register alongside these without changes to the simulation core.
        </p>

        <ExecutionTrace />

        {byCategory.map((group) => (
          <section key={group.category} className="skills__group">
            <h4 className="skills__category">{group.category.toLowerCase()}</h4>
            <ul className="skills__list">
              {group.skills.map((skill) => (
                <li key={skill.id} data-testid={`skill-${skill.id}`}>
                  <button
                    type="button"
                    className="skills__row"
                    aria-expanded={expanded === skill.id}
                    onClick={() => setExpanded(expanded === skill.id ? null : skill.id)}
                    data-testid={`skill-toggle-${skill.id}`}
                  >
                    <span className="skills__name">{skill.name}</span>
                    <span className="skills__version fm-mono">{skill.version}</span>
                    <span
                      className={`skills__kind${skill.deterministic ? "" : " skills__kind--ai"}`}
                      data-testid={`skill-kind-${skill.id}`}
                    >
                      {skill.deterministic ? (
                        <>
                          <Cpu size={11} strokeWidth={2} aria-hidden="true" /> Deterministic
                        </>
                      ) : (
                        <>
                          <Wrench size={11} strokeWidth={2} aria-hidden="true" /> AI-assisted
                        </>
                      )}
                    </span>
                    {/* Only shown when there is one — a side-effect badge on
                        every row would stop meaning anything. */}
                    {!skill.side_effects.includes("NONE") && (
                      <span className="skills__effect" data-testid={`skill-effects-${skill.id}`}>
                        <FileWarning size={11} strokeWidth={2} aria-hidden="true" />
                        {skill.side_effects.map((e) => SIDE_EFFECT_LABEL[e] ?? e).join(", ")}
                      </span>
                    )}
                  </button>

                  {expanded === skill.id && (
                    <div className="skills__detail" data-testid={`skill-detail-${skill.id}`}>
                      <p>{skill.description}</p>
                      <dl>
                        <div>
                          <dt>Consumes</dt>
                          <dd className="fm-mono">{skill.input_types.join(", ") || "—"}</dd>
                        </div>
                        <div>
                          <dt>Produces</dt>
                          <dd className="fm-mono">{skill.output_types.join(", ") || "—"}</dd>
                        </div>
                        {skill.prerequisites.length > 0 && (
                          <div>
                            <dt>Needs first</dt>
                            <dd className="fm-mono">{skill.prerequisites.join(", ")}</dd>
                          </div>
                        )}
                        {skill.supported_inputs.length > 0 && (
                          <div>
                            <dt>Input formats</dt>
                            <dd className="fm-mono">{skill.supported_inputs.join(", ")}</dd>
                          </div>
                        )}
                        <div>
                          <dt>Identifier</dt>
                          <dd className="fm-mono">{skill.qualified_id}</dd>
                        </div>
                      </dl>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ))}

        <section className="skills__group">
          <h4 className="skills__category">workflows</h4>
          <ul className="skills__list" data-testid="skill-workflows">
            {data.workflows.map((workflow) => (
              <li key={workflow.id}>
                <span className="skills__name">{workflow.name}</span>
                <span className="skills__flow fm-mono">{workflow.skills.join(" → ")}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </details>
  );
}


/** What actually ran, most recent first. */
function ExecutionTrace() {
  const executions = useSyncExternalStore(subscribeToSkillTrace, getSkillExecutions);

  if (executions.length === 0) {
    return (
      <p className="pipeline__detail" data-testid="skill-trace-empty">
        No skill has run yet in this session. This list fills in as the concept is
        built and verified.
      </p>
    );
  }

  const recent = [...executions].reverse().slice(0, 8);

  return (
    <section className="skills__group" data-testid="skill-trace">
      <h4 className="skills__category">
        <Activity size={11} strokeWidth={2} aria-hidden="true" /> ran in this session
      </h4>
      <ul className="skills__trace">
        {recent.map((entry, index) => (
          <li key={`${entry.path}-${entry.skillId}-${index}`} data-testid="skill-trace-entry">
            <span className="skills__name">{entry.skillId}</span>
            <span className="skills__version fm-mono">{entry.version}</span>
            <span
              className={`skills__status skills__status--${entry.status.toLowerCase()}`}
              data-testid={`skill-trace-status-${entry.skillId}`}
            >
              {entry.status}
            </span>
            <span className="skills__path fm-mono">{entry.path}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
