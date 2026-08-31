import { afterEach, describe, expect, it, vi } from "vitest";
import { apiGet, apiPost, ApiError, ApiValidationError, BackendUnavailableError, describeRequestFailure } from "./client";
import { getSkillExecutions, resetSkillTrace } from "./skillTrace";

function mockFetchOnce(response: Partial<Response> & { json?: () => Promise<unknown> }) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      // A real Response always has headers, and the client reads the skill
      // trace off them. A fake without headers is not a Response.
      headers: new Headers(),
      json: async () => ({}),
      ...response,
    } as Response),
  );
}

describe("api/client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns parsed JSON on a 200 response", async () => {
    mockFetchOnce({ ok: true, status: 200, json: async () => ({ hello: "world" }) });
    const result = await apiGet<{ hello: string }>("/health");
    expect(result).toEqual({ hello: "world" });
  });

  it("throws ApiValidationError on a 422 response", async () => {
    mockFetchOnce({ ok: false, status: 422, json: async () => ({ detail: [{ msg: "bad field" }] }) });
    await expect(apiPost("/planning/run", {})).rejects.toBeInstanceOf(ApiValidationError);
  });

  it("throws ApiError (not ApiValidationError) on a 400 response", async () => {
    mockFetchOnce({ ok: false, status: 400, json: async () => ({ detail: "Unknown product_id." }) });
    const promise = apiPost("/planning/run", {});
    await expect(promise).rejects.toBeInstanceOf(ApiError);
    await expect(promise).rejects.not.toBeInstanceOf(ApiValidationError);
  });

  it("throws BackendUnavailableError when fetch itself rejects (network down)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await expect(apiGet("/factory/example")).rejects.toBeInstanceOf(BackendUnavailableError);
  });

  it("carries the response status/detail on ApiError", async () => {
    mockFetchOnce({ ok: false, status: 500, json: async () => ({ detail: "boom" }) });
    try {
      await apiGet("/health");
      throw new Error("expected apiGet to throw");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).status).toBe(500);
      expect((error as ApiError).detail).toBe("boom");
    }
  });

  describe("describeRequestFailure", () => {
    it("describes a BackendUnavailableError distinctly from other errors", () => {
      expect(describeRequestFailure(new BackendUnavailableError())).toMatch(/backend unavailable/i);
    });

    it("describes an ApiValidationError distinctly", () => {
      expect(describeRequestFailure(new ApiValidationError("bad shape"))).toMatch(/invalid request/i);
    });

    it("shows the domain's own message when the backend supplied one", () => {
      // The engineering message is the useful half. "Backend error (400):" in
      // front of "Still required: Shifts per day..." turns a designed refusal
      // into an apparent crash.
      expect(describeRequestFailure(new ApiError(400, "Still required: Shifts per day."))).toBe(
        "Still required: Shifts per day.",
      );
    });

    it("falls back to the status code when there is no domain message", () => {
      expect(describeRequestFailure(new ApiError(500, undefined))).toMatch(/500/);
      expect(describeRequestFailure(new ApiError(500, { unexpected: true }))).toMatch(/500/);
    });
  });
});

describe("api/client — skill trace", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    resetSkillTrace();
  });

  it("records the skills a response reports", async () => {
    resetSkillTrace();
    mockFetchOnce({
      headers: new Headers({ "X-FactoryMind-Skills": "factory_simulation@1.0.0:SUCCESS" }),
      json: async () => ({}),
    });
    await apiGet("/simulation/run");

    expect(getSkillExecutions()).toHaveLength(1);
    expect(getSkillExecutions()[0].skillId).toBe("factory_simulation");
    expect(getSkillExecutions()[0].path).toBe("/simulation/run");
  });

  it("records nothing for an endpoint that reports no skills", async () => {
    resetSkillTrace();
    mockFetchOnce({ json: async () => ({}) });
    await apiGet("/health");

    expect(getSkillExecutions()).toHaveLength(0);
  });

  it("records the skill that refused, on a failed request", async () => {
    resetSkillTrace();
    mockFetchOnce({
      ok: false,
      status: 400,
      headers: new Headers({
        "X-FactoryMind-Skills": "factory_concept_builder@1.0.0:BLOCKED",
      }),
      json: async () => ({ detail: "Still required: Shifts per day." }),
    });
    await expect(apiGet("/concept/build")).rejects.toBeInstanceOf(ApiError);

    expect(getSkillExecutions()[0].status).toBe("BLOCKED");
  });
});
