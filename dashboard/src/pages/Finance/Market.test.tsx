import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import Market from "./Market";
const api = vi.hoisted(() => ({
  status: vi.fn(),
  search: vi.fn(),
  kline: vi.fn(),
  watchlist: vi.fn(),
  saveWatchlist: vi.fn(),
}));
vi.mock("../../api/modules/market", () => ({ marketApi: api }));
vi.mock("./MarketChart", () => ({
  default: ({ bars }: { bars: unknown[] }) => (
    <div data-testid="bars">{bars.length}</div>
  ),
}));
beforeEach(() => {
  vi.clearAllMocks();
  api.status.mockResolvedValue({ configured: true });
  api.search.mockResolvedValue({ items: [] });
  api.kline.mockResolvedValue({ bars: [] });
  api.watchlist.mockResolvedValue({
    revision: "0",
    groups: ["默认"],
    items: [],
  });
});
it("ignores stale search results and cancels pending work on unmount", async () => {
  let resolve!: (value: unknown) => void;
  api.search.mockImplementationOnce(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  const view = render(<Market />);
  fireEvent.change(screen.getByLabelText("搜索证券"), {
    target: { value: "old" },
  });
  await waitFor(() => expect(api.search).toHaveBeenCalledTimes(1));
  const signal = api.search.mock.calls[0][1] as AbortSignal;
  fireEvent.change(screen.getByLabelText("搜索证券"), {
    target: { value: "new" },
  });
  expect(signal.aborted).toBe(true);
  await act(async () =>
    resolve({ items: [{ symbol: "600519.SH", name: "旧结果" }] }),
  );
  expect(screen.queryByText(/旧结果/)).not.toBeInTheDocument();
  await waitFor(() => expect(api.search).toHaveBeenCalledTimes(2));
  const latest = api.search.mock.calls[1][1] as AbortSignal;
  view.unmount();
  expect(latest.aborted).toBe(true);
});
it("reloads the latest watchlist on conflict without retrying the write", async () => {
  api.saveWatchlist.mockRejectedValue(
    new Error("Request failed: 409 Conflict"),
  );
  render(<Market />);
  const add = await screen.findByRole("button", { name: "加入自选" });
  await waitFor(() => expect(add).toBeEnabled());
  fireEvent.click(add);
  await screen.findByText("自选股已在其他页面修改，已重新加载，请重试。");
  expect(api.watchlist).toHaveBeenCalledTimes(2);
  expect(api.saveWatchlist).toHaveBeenCalledTimes(1);
});
it("clears previous bars immediately and aborts their request when switching symbols", async () => {
  api.watchlist.mockResolvedValue({
    revision: "1",
    groups: ["默认"],
    items: [{ symbol: "600519.SH", name: "贵州茅台", groups: ["默认"] }],
  });
  let finish!: (value: unknown) => void;
  api.kline.mockImplementationOnce(
    () =>
      new Promise((r) => {
        finish = r;
      }),
  );
  const view = render(<Market />);
  await screen.findByText(/贵州茅台/);
  const signal = api.kline.mock.calls[0][2] as AbortSignal;
  fireEvent.click(screen.getByRole("button", { name: "贵州茅台 600519.SH" }));
  expect(signal.aborted).toBe(true);
  await act(async () =>
    finish({
      bars: [{ date: "2026-11-05", open: 1, high: 2, low: 1, close: 2 }],
    }),
  );
  expect(screen.getByTestId("bars")).toHaveTextContent("0");
  view.unmount();
});

it("preserves an in-flight chart request when selecting its current symbol", async () => {
  api.watchlist.mockResolvedValue({
    revision: "1",
    groups: ["默认"],
    items: [{ symbol: "000001.SH", name: "上证指数", groups: ["默认"] }],
  });
  api.kline.mockImplementationOnce(() => new Promise(() => {}));
  render(<Market />);
  await screen.findByRole("button", { name: "上证指数 000001.SH" });
  await waitFor(() => expect(api.kline).toHaveBeenCalledTimes(1));
  const signal = api.kline.mock.calls[0][2] as AbortSignal;
  fireEvent.click(screen.getByRole("button", { name: "上证指数 000001.SH" }));
  expect(signal.aborted).toBe(false);
});
it("shows readable backend details instead of the transport envelope", async () => {
  api.kline.mockRejectedValue(
    new Error(
      'Request failed: 502 Bad Gateway - {"detail":"数据服务暂不可用"}',
    ),
  );
  render(<Market />);
  await screen.findByText("数据服务暂不可用");
  expect(screen.queryByText(/Request failed:/)).not.toBeInTheDocument();
});

it("does not allow refresh to abort a pending watchlist save", async () => {
  let finish!: (value: unknown) => void;
  api.saveWatchlist.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  render(<Market />);
  const add = await screen.findByRole("button", { name: "加入自选" });
  await waitFor(() => expect(add).toBeEnabled());
  fireEvent.click(add);
  await waitFor(() => expect(api.saveWatchlist).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("button", { name: /刷\s*新/ })).toBeDisabled();
  const signal = api.saveWatchlist.mock.calls[0][1] as AbortSignal;
  await act(async () =>
    finish({
      revision: "1",
      groups: ["默认"],
      items: [{ symbol: "000001.SH", name: "上证指数", groups: ["默认"] }],
    }),
  );
  expect(signal.aborted).toBe(false);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "移出自选" })).toBeEnabled(),
  );
});
