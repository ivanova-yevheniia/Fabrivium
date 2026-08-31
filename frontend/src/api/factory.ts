import { apiGet } from "./client";
import type { Factory } from "./types";

/** GET /factory/example — the bundled examples/electronics_line.json Factory. */
export function getExampleFactory(): Promise<Factory> {
  return apiGet<Factory>("/factory/example");
}
