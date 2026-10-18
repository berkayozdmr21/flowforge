import { describe, it, expect, vi, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Schedules, { localInputDate, scheduleStart } from "./Schedules";
import { api } from "./api";
import type { Flow } from "./types";
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  api: vi.fn(),
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
const flow = { id: "flow", name: "Demo", revision: 1 } as Flow;
function show(
  prepare = vi.fn().mockResolvedValue({ ...flow, revision: 2 }),
  canCreate = true,
) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <Schedules
        flow={flow}
        prepare={prepare}
        canCreate={canCreate}
        openRun={vi.fn()}
      />
    </QueryClientProvider>,
  );
  return prepare;
}
describe("schedule local time", () => {
  it("round trips local wall time to an explicit UTC instant", () => {
    const future = new Date(Date.now() + 3600000);
    future.setMilliseconds(0);
    expect(scheduleStart(localInputDate(future))).toBe(future.toISOString());
  });
  it.each(["", "bad", "2020-01-01T00:00"])(
    "rejects invalid or past start %s",
    (value) => {
      expect(() => scheduleStart(value)).toThrow();
    },
  );
});
it("saves the draft revision before scheduling and sends an idempotency key", async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path.endsWith("/schedules") ? [] : {},
  );
  const prepare = show();
  fireEvent.change(screen.getByLabelText("Zamanlama adı"), {
    target: { value: "Night run" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zamanlamayı kaydet" }));
  await waitFor(() => expect(prepare).toHaveBeenCalledOnce());
  await waitFor(() =>
    expect(
      vi
        .mocked(api)
        .mock.calls.some(([, options]) => options?.method === "POST"),
    ).toBe(true),
  );
  const [, options] = vi
    .mocked(api)
    .mock.calls.find(([, options]) => options?.method === "POST")!;
  expect(JSON.parse(options!.body as string)).toMatchObject({
    name: "Night run",
    revision: 2,
    mode: "once",
  });
  expect(
    (options!.headers as Record<string, string>)["Idempotency-Key"],
  ).toBeTruthy();
});
it("does not create schedules for read-only history", async () => {
  vi.mocked(api).mockResolvedValue([]);
  show(undefined, false);
  expect(
    screen.queryByRole("button", { name: "Zamanlamayı kaydet" }),
  ).toBeNull();
});
it("does not submit when draft preparation fails", async () => {
  vi.mocked(api).mockResolvedValue([]);
  show(vi.fn().mockRejectedValue(Error("Apply pending JSON first")));
  fireEvent.click(screen.getByRole("button", { name: "Zamanlamayı kaydet" }));
  await screen.findByText("Apply pending JSON first");
  expect(
    vi.mocked(api).mock.calls.some(([, options]) => options?.method === "POST"),
  ).toBe(false);
});
