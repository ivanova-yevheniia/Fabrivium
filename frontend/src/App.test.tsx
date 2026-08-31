import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { conversationTurnResponse, sampleFactory, sampleExplanationAccepted } from "./test/fixtures";

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  // `headers` is not optional decoration: the API client reads the skill
  // trace off every response, so a fake without them is not a Response.
  return { ok, status, headers: new Headers(), json: async () => body } as Response;
}

/** A project document as the store returns one. */
function projectResponse() {
  return {
    project: {
      schema_version: 1,
      project_id: "test-project",
      name: "Example — electronics controller",
      created_at: "2026-01-01T00:00:00+00:00",
      updated_at: "2026-01-01T00:00:00+00:00",
      state: {
        product: {
          name: "",
          description: "",
          from_example: true,
          understanding: null,
          understanding_model_used: false,
        },
        process: { draft: null, coverage: null },
        requirements: { text: "" },
        concept: { draft: null, factory: null, product_id: null, layout: null, verified_from: null },
        results: { arena: null, selected_strategy_id: null, explore_requests: [] },
        layout: { applied: {} },
        equipment: { selections: {} },
        is_example: true,
        stage: "PRODUCT",
        revisions: {},
        evidence: {},
        history: [],
        produced: [],
        withdrawn: [],
      },
    },
    staleness: { stale: [], current: [], unverified: [], summary: "Nothing has been verified yet." },
  };
}

/** Answers the project/reference plumbing and delegates everything else. */
function withProjectRoutes(handler: (url: string) => Response) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url);
    if (path.endsWith("/projects") && init?.method === "POST") return jsonResponse(projectResponse());
    if (path.endsWith("/projects")) return jsonResponse({ projects: [] });
    if (path.includes("/projects/")) return jsonResponse(projectResponse());
    if (path.includes("/product/reference")) {
      return jsonResponse({ name: "reference.txt", text: "A controller in a plastic enclosure." });
    }
    return handler(path);
  });
}

describe("App (integration)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  /** Phase 13 — the app no longer loads a factory on mount. */
  async function openDemoFactory(user: ReturnType<typeof userEvent.setup>) {
    // P0 — the demo line lives inside the EXAMPLE PROJECT now rather than
    // being a third tile on the front door, so the journey opens a project
    // first. That is one extra click and no change in what follows: the
    // factory, the state it produces and every assertion below are the same.
    await user.click(await screen.findByTestId("project-open-example"));
    await user.click(await screen.findByTestId("start-open-demo"));
    await waitFor(() => expect(screen.getByText(sampleFactory.name)).toBeInTheDocument());
  }

  it("P0 — opens on the project workspace rather than a production flow", async () => {
    vi.stubGlobal("fetch", withProjectRoutes(() => jsonResponse(sampleFactory)));
    render(<App />);

    expect(screen.getByTestId("project-landing")).toBeInTheDocument();
    // The three things the landing page offers, and only those.
    expect(screen.getByTestId("project-create")).toBeInTheDocument();
    expect(screen.getByTestId("project-recent")).toBeInTheDocument();
    expect(screen.getByTestId("project-open-example")).toBeInTheDocument();
    expect(screen.queryByTestId("executive-shell")).not.toBeInTheDocument();
  });

  it("Phase 13 — a project opens on the starting choice, not a pre-loaded factory", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", withProjectRoutes(() => jsonResponse(sampleFactory)));
    render(<App />);

    await user.click(await screen.findByTestId("project-open-example"));

    expect(await screen.findByTestId("start-screen")).toBeInTheDocument();
    expect(screen.getByTestId("start-from-product")).toBeInTheDocument();
    expect(screen.getByTestId("start-design-new")).toBeInTheDocument();
    // No factory has been fetched — none is assumed to exist.
    expect(screen.queryByTestId("executive-shell")).not.toBeInTheDocument();
  });

  it("loads the demo factory on request and shows its name in the top bar", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", withProjectRoutes(() => jsonResponse(sampleFactory)));
    render(<App />);
    await openDemoFactory(user);
  });

  it("Phase 9A — lands on Executive View by default, and the toggle switches to Engineering View and back", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", withProjectRoutes(() => jsonResponse(sampleFactory)));
    render(<App />);
    await openDemoFactory(user);

    expect(screen.getByTestId("executive-shell")).toBeInTheDocument();
    expect(screen.getByTestId("goal-input")).toBeInTheDocument();
    expect(screen.queryByTestId("conversation-panel")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("view-level-engineering"));
    expect(screen.getByTestId("app-shell")).toBeInTheDocument();
    expect(screen.queryByTestId("executive-shell")).not.toBeInTheDocument();

    // Phase 12 §8 — Engineering View opens on the Factory context (the twin
    // and the machine inspector). The conversation belongs to Plan analysis,
    // so it is reachable from the tab bar rather than always mounted.
    expect(screen.getByTestId("engineering-tabs")).toBeInTheDocument();
    await user.click(screen.getByTestId("engineering-tab-plan_analysis"));
    expect(screen.getByTestId("conversation-panel")).toBeInTheDocument();

    await user.click(screen.getByTestId("view-level-executive"));
    expect(screen.getByTestId("executive-shell")).toBeInTheDocument();
  });

  it("shows a backend-unavailable error banner when the backend cannot be reached", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      withProjectRoutes(() => {
        throw new TypeError("Failed to fetch");
      }),
    );
    render(<App />);
    // Phase 13: the fetch happens on the explicit "open demo factory" click
    // rather than on mount, so the failure surfaces from that action.
    await user.click(await screen.findByTestId("project-open-example"));
    await user.click(await screen.findByTestId("start-open-demo"));
    await waitFor(() => expect(screen.getByTestId("error-banner")).toHaveTextContent(/backend unavailable/i));
  });

  it("holding a conversation end to end renders the constraints, branch, timeline, KPIs, and explanation", async () => {
    const user = userEvent.setup();
    const fetchMock = withProjectRoutes((url) => {
      if (url.includes("/factory/example")) return jsonResponse(sampleFactory);
      if (url.includes("/conversation/start")) return jsonResponse(conversationTurnResponse());
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    await openDemoFactory(user);

    // Phase 9A: Executive View is the default landing presentation; this
    // test exercises the dense Engineering View conversation panel/timeline
    // directly, exactly as a user would by clicking the toggle.
    //
    // Phase 12 §8: the conversation, the KPI panel, the explanation and the
    // iteration timeline all live in the Plan analysis context now, so the
    // journey adds one click to get there. What is asserted below is
    // unchanged — one conversation turn still has to drive the constraints,
    // the branch, the timeline, the KPIs and the explanation together.
    await user.click(screen.getByTestId("view-level-engineering"));
    await user.click(screen.getByTestId("engineering-tab-plan_analysis"));

    const panel = screen.getByTestId("conversation-panel");
    await user.type(within(panel).getByLabelText(/what do you want to change/i), "We need 700 units/day.");
    await user.click(within(panel).getByRole("button", { name: /^send$/i }));

    // The conversation records the turn...
    await waitFor(() => expect(screen.getByTestId("turn-0")).toBeInTheDocument());
    expect(screen.getByTestId("turn-user-0")).toHaveTextContent("We need 700 units/day.");
    expect(screen.getByTestId("active-constraints")).toHaveTextContent("Target 700/day");
    expect(screen.getByTestId("branch-selector")).toHaveTextContent("Plan A");

    // ...and the branch's verified result drives the whole digital twin.
    expect(screen.getByTestId("timeline-iteration-0")).toBeInTheDocument();
    expect(screen.getByTestId("explanation-panel")).toHaveTextContent(sampleExplanationAccepted.executive_summary);
    expect(screen.getByTestId("kpi-panel")).toHaveTextContent("500");
  });
});
