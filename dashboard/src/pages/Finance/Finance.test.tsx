import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ catalog: vi.fn(), evaluate: vi.fn() }));
vi.mock("../../api/modules/finance", () => ({ financeApi: api }));
const catalog = {
  configured: true,
  expert_tool_available: false,
  items: [
    {
      id: "neo.trend_histogram",
      name: "NEO 趋势柱线",
      connected: true,
      origin: "formula_migration",
      verification_status: "not_pointwise_verified",
    },
    {
      id: "neo.money_bag",
      name: "NEO 钱袋子",
      connected: false,
      origin: "approximation",
      verification_status: "unverified",
    },
  ],
};
const result = (id: string) => ({
  schema_version: 1,
  status: "ok",
  capability: "neo.trend_histogram",
  instrument_id: id,
  period: "day",
  adjust: "qfq",
  as_of: "2026-11-04",
  generated_at: "2026-11-04T20:00:00+08:00",
  bar_state: "closed",
  rule_version: "v1",
  origin: "formula_migration",
  verification_status: "not_pointwise_verified",
  snapshot_id: id,
  points: [{ date: "2026-11-04", value: 1.2 }],
  latest: {},
  warnings: [],
  coverage: {},
});

beforeEach(() => {
  api.catalog.mockReset().mockResolvedValue(catalog);
  api.evaluate.mockReset();
});

async function mount() {
  const { default: Finance } = await import("./index");
  render(<Finance />);
  await screen.findByRole("button", { name: /NEO 趋势柱线/ });
}

describe("NEO financial workspace", () => {
  it("shows unavailable core capabilities honestly and never evaluates on mount", async () => {
    api.catalog.mockResolvedValue({ ...catalog, configured: false });
    await mount();
    expect(screen.getByRole("button", { name: "获取指标" })).toBeDisabled();
    expect(screen.getByText(/尚未连接私有计算服务/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /NEO 钱袋子/ })).toBeDisabled();
    expect(api.evaluate).not.toHaveBeenCalled();
  });

  it("submits explicit inputs and renders the server snapshot", async () => {
    api.evaluate.mockResolvedValue(result("CN:SZ:stock:300274"));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "获取指标" }));
    await screen.findByText("CN:SZ:stock:300274");
    expect(api.evaluate.mock.calls[0][0]).toMatchObject({
      instrument_id: "CN:SZ:stock:300274",
      capability: "neo.trend_histogram",
      period: "day",
      adjust: "qfq",
    });
    expect(screen.getByText("2026-11-04")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "趋势柱线结果" }),
    ).toBeInTheDocument();
  });

  it("aborts a stale request and ignores its late result after switching stocks", async () => {
    let finish!: (value: unknown) => void;
    api.evaluate.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "获取指标" }));
    await waitFor(() => expect(api.evaluate).toHaveBeenCalledTimes(1));
    const signal = api.evaluate.mock.calls[0][1] as AbortSignal;
    fireEvent.change(screen.getByLabelText("证券标识"), {
      target: { value: "CN:SH:stock:600519" },
    });
    expect(signal.aborted).toBe(true);
    finish(result("CN:SZ:stock:300274"));
    api.evaluate.mockResolvedValueOnce(result("CN:SH:stock:600519"));
    fireEvent.click(screen.getByRole("button", { name: "获取指标" }));
    await screen.findByText("CN:SH:stock:600519");
    expect(screen.queryByText("CN:SZ:stock:300274")).not.toBeInTheDocument();
  });

  it("allows retry after an upstream failure without fabricating a chart", async () => {
    api.evaluate.mockRejectedValueOnce(new Error("服务暂不可用"));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "获取指标" }));
    await screen.findByText("服务暂不可用");
    expect(
      screen.queryByRole("img", { name: "趋势柱线结果" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "获取指标" })).toBeEnabled();
  });
});
