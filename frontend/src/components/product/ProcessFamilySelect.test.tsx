import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { PROCESS_FAMILY_CATALOG } from "../../test/fixtures";

/** The process family is chosen from the server's vocabulary or not at all. */

vi.mock("../../api/processFamilies", () => ({
  fetchProcessFamilies: vi.fn(),
}));

const api = await import("../../api/processFamilies");
const { ProcessFamilySelect, defaultProcessType, resetProcessFamilyCache, useProcessFamilies } =
  await import("./ProcessFamilySelect");

/** A harness, because the state lives in a hook the select is given. */
function Harness({ onType }: { onType?: (t: string) => void } = {}) {
  const state = useProcessFamilies();
  return (
    <>
      <ProcessFamilySelect value="" onChange={onType ?? (() => {})} state={state} testId="pfs" />
      <span data-testid="default">{defaultProcessType(state)}</span>
    </>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  resetProcessFamilyCache();
});

describe("process family select", () => {
  it("offers every family the backend publishes, not the golden run's five", async () => {
    vi.mocked(api.fetchProcessFamilies).mockResolvedValue(PROCESS_FAMILY_CATALOG);
    render(<Harness />);

    const select = await screen.findByTestId("pfs");
    await waitFor(() => expect(select.querySelectorAll("option")).toHaveLength(12));

    const values = Array.from(select.querySelectorAll("option")).map((o) => o.getAttribute("value"));
    // The seven a mechanical, packaging or medical-device project needs and
    // that neither hard-coded list offered.
    expect(values).toEqual(
      expect.arrayContaining([
        "welding", "soldering", "painting", "machining", "cleaning", "curing", "palletizing",
      ]),
    );
    // And exactly one spelling of the family that used to have two.
    expect(values.filter((v) => v === "labelling")).toHaveLength(1);
    expect(values).not.toContain("labeling");
    // `testing` is an alias of inspection, never a family.
    expect(values).not.toContain("testing");
  });

  it("says which families have no reference estimate rather than letting it be found later", async () => {
    vi.mocked(api.fetchProcessFamilies).mockResolvedValue(PROCESS_FAMILY_CATALOG);
    render(<Harness />);

    const select = await screen.findByTestId("pfs");
    await waitFor(() => expect(select.querySelectorAll("option").length).toBeGreaterThan(1));

    const welding = Array.from(select.querySelectorAll("option")).find(
      (o) => o.getAttribute("value") === "welding",
    );
    expect(welding?.textContent).toContain("no reference estimate");

    const screwdriving = Array.from(select.querySelectorAll("option")).find(
      (o) => o.getAttribute("value") === "screwdriving",
    );
    expect(screwdriving?.textContent).not.toContain("no reference estimate");
  });

  it("offers nothing and explains itself when the vocabulary cannot be fetched", async () => {
    vi.mocked(api.fetchProcessFamilies).mockRejectedValue(new Error("backend unreachable"));
    render(<Harness />);

    await screen.findByTestId("pfs-error");
    // No select at all — not an empty one, and above all not a built-in list.
    expect(screen.queryByTestId("pfs")).toBeNull();
    expect(screen.getByTestId("pfs-error").textContent).toContain("cannot be added");
  });

  it("has no default family until the server supplies one", async () => {
    vi.mocked(api.fetchProcessFamilies).mockRejectedValue(new Error("backend unreachable"));
    render(<Harness />);

    await screen.findByTestId("pfs-error");
    // The empty string is what the two callers gate their submit on, so a
    // form cannot post an operation while the vocabulary is unknown.
    expect(screen.getByTestId("default").textContent).toBe("");
  });

  it("issues one request when several selects mount in the same tick", async () => {
    // Caching only the RESOLVED value looks like deduplication and is not:
    // two selects mounting together both see an empty cache and both fetch,
    // because neither request has resolved yet. Found in a browser, not
    // here — the earlier version of this file passed the test below while
    // issuing two real requests on the page.
    let release: (v: typeof PROCESS_FAMILY_CATALOG) => void = () => {};
    vi.mocked(api.fetchProcessFamilies).mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );

    render(
      <>
        <Harness />
        <Harness />
        <Harness />
      </>,
    );

    expect(api.fetchProcessFamilies).toHaveBeenCalledTimes(1);
    release(PROCESS_FAMILY_CATALOG);
    await waitFor(() =>
      expect(screen.getAllByTestId("pfs")[0].querySelectorAll("option")).toHaveLength(12),
    );
    expect(api.fetchProcessFamilies).toHaveBeenCalledTimes(1);
  });

  it("retries after a failure rather than caching the rejection forever", async () => {
    vi.mocked(api.fetchProcessFamilies).mockRejectedValueOnce(new Error("blip"));
    const first = render(<Harness />);
    await screen.findByTestId("pfs-error");
    first.unmount();

    vi.mocked(api.fetchProcessFamilies).mockResolvedValue(PROCESS_FAMILY_CATALOG);
    render(<Harness />);
    const select = await screen.findByTestId("pfs");
    await waitFor(() => expect(select.querySelectorAll("option")).toHaveLength(12));
  });

  it("fetches the catalog once and reuses it", async () => {
    vi.mocked(api.fetchProcessFamilies).mockResolvedValue(PROCESS_FAMILY_CATALOG);
    const first = render(<Harness />);
    await waitFor(() => expect(api.fetchProcessFamilies).toHaveBeenCalledTimes(1));
    first.unmount();

    render(<Harness />);
    await screen.findByTestId("pfs");
    expect(api.fetchProcessFamilies).toHaveBeenCalledTimes(1);
  });
});
