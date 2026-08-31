/** Typed fetch wrapper for the Fabrivium backend. */

import { SKILL_TRACE_HEADER, recordSkillTrace } from "./skillTrace";

export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL && import.meta.env.VITE_API_BASE_URL.replace(/\/$/, "")) ||
  "http://localhost:8000";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? `Backend request failed (HTTP ${status}).`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export class ApiValidationError extends ApiError {
  constructor(detail: unknown) {
    super(422, detail, "The request was rejected as structurally invalid (422).");
    this.name = "ApiValidationError";
  }
}

export class BackendUnavailableError extends Error {
  readonly originalError?: unknown;

  constructor(originalError?: unknown) {
    super("Could not reach the Fabrivium backend. Is it running?");
    this.name = "BackendUnavailableError";
    this.originalError = originalError;
  }
}

export type RequestFailure = ApiError | ApiValidationError | BackendUnavailableError;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch (cause) {
    throw new BackendUnavailableError(cause);
  }

  // Recorded for both outcomes: a BLOCKED skill behind a 400 is exactly the
  // execution an engineer most wants to see.
  recordSkillTrace(response.headers.get(SKILL_TRACE_HEADER), path);

  if (!response.ok) {
    let detail: unknown = undefined;
    try {
      const body = await response.json();
      detail = body?.detail ?? body;
    } catch {
      // Non-JSON error body — leave detail undefined rather than throwing.
    }
    if (response.status === 422) {
      throw new ApiValidationError(detail);
    }
    throw new ApiError(response.status, detail);
  }

  return (await response.json()) as T;
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path, { method: "GET" });
}

export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(body) });
}

export function apiPut<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "PUT", body: JSON.stringify(body) });
}

export function apiDelete<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" });
}

/** Human-readable message for any RequestFailure — used wherever the UI
 * needs one line of error text (never a raw stack trace). */
export function describeRequestFailure(error: unknown): string {
  if (error instanceof BackendUnavailableError) {
    return `Backend unavailable: ${error.message}`;
  }
  if (error instanceof ApiValidationError) {
    return `Invalid request: ${summarizeDetail(error.detail)}`;
  }
  if (error instanceof ApiError) {
    // A string `detail` is the domain's own message — "This concept is not
    // ready to simulate. Still required: Shifts per day, ..." — written to be
    // read by an engineer. Prefixing it with "Backend error (400):" reframes a
    // designed refusal as a crash, and the concept-build gate is one of the
    // best moments in the product: it is the system declining to invent six
    // numbers. Show the sentence it wrote.
    //
    // The prefix survives for failures with no domain message, where the
    // status code IS the only information available.
    if (typeof error.detail === "string" && error.detail.trim()) {
      return error.detail;
    }
    return `Backend error (${error.status}): ${summarizeDetail(error.detail)}`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "An unknown error occurred.";
}

function summarizeDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (detail == null) return "no further details provided.";
  try {
    return JSON.stringify(detail);
  } catch {
    return "no further details provided.";
  }
}
