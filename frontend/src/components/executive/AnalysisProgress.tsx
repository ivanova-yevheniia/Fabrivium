/** The analysis wait state. */

const STAGES = [
  {
    key: "understand",
    title: "Understand the requirement",
    detail: "Your target and constraints are read into a structured requirement.",
  },
  {
    key: "generate",
    title: "Build engineering alternatives",
    detail: "Different families of intervention — equipment, shifts, workforce, buffers.",
  },
  {
    key: "simulate",
    title: "Simulate each alternative",
    detail: "A deterministic discrete-event engine runs every candidate against the factory model.",
    truth: true,
  },
  {
    key: "verify",
    title: "Verify and compare",
    detail: "Only configurations a simulation actually reached are kept, with their costs stated honestly.",
  },
] as const;

export function AnalysisProgress() {
  return (
    <div className="analysis-progress" data-testid="analysis-progress" role="status" aria-live="polite">
      <header className="analysis-progress__header">
        <h1 className="analysis-progress__title">Building and verifying engineering strategies</h1>
        <p className="analysis-progress__detail">
          Fabrivium is testing alternative production configurations against the factory simulation. This
          usually takes under a minute.
        </p>
      </header>

      {/* aria-busy, not a progressbar: there is no measurable progress to
          expose, and announcing one would be as untrue to a screen reader
          as a fake percentage is to everyone else. */}
      <ol className="analysis-pipeline" aria-label="What this pass consists of" aria-busy="true">
        {STAGES.map((stage) => (
          <li
            className={`analysis-pipeline__stage${"truth" in stage && stage.truth ? " analysis-pipeline__stage--truth" : ""}`}
            key={stage.key}
            data-testid={`analysis-stage-${stage.key}`}
          >
            <div className="analysis-pipeline__marker" aria-hidden="true">
              <span className="analysis-pipeline__dot" />
            </div>
            <div className="analysis-pipeline__body">
              <p className="analysis-pipeline__stage-title">
                {stage.title}
                {/* Stated in WORDS, not by colouring the stage marker. */}
                {"truth" in stage && stage.truth && (
                  <span className="analysis-pipeline__truth-tag">source of engineering truth</span>
                )}
              </p>
              <p className="analysis-pipeline__stage-detail">{stage.detail}</p>
            </div>
          </li>
        ))}
        {/* One indeterminate indicator for the request as a whole. */}
        <span className="analysis-pipeline__rail" aria-hidden="true">
          <span className="analysis-pipeline__scan" />
        </span>
      </ol>
    </div>
  );
}
