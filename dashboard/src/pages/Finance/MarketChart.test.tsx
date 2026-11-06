import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import MarketChart from "./MarketChart";
const chart = vi.hoisted(() => ({
  setTimezone: vi.fn(),
  setLocale: vi.fn(),
  setDataLoader: vi.fn(),
  setSymbol: vi.fn(),
  setPeriod: vi.fn(),
  createIndicator: vi.fn(),
  resize: vi.fn(),
}));
const library = vi.hoisted(() => ({ init: vi.fn(), dispose: vi.fn() }));
vi.mock("klinecharts", () => library);
afterEach(() => vi.unstubAllGlobals());
it("keeps one chart for unchanged inputs and disconnects / disposes on unmount", () => {
  const disconnect = vi.fn();
  const observe = vi.fn();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe = observe;
      disconnect = disconnect;
    },
  );
  library.init.mockReturnValue(chart);
  const bars = [{ date: "2026-11-05", open: 1, high: 2, low: 1, close: 2 }];
  const view = render(<MarketChart symbol="600519.SH" bars={bars} />);
  expect(
    screen.getByRole("img", { name: "600519.SH 日K线图" }),
  ).toBeInTheDocument();
  expect(library.init).toHaveBeenCalledTimes(1);
  expect(observe).toHaveBeenCalledTimes(1);
  expect(chart.setLocale).toHaveBeenCalledWith("zh-CN");
  view.rerender(<MarketChart symbol="600519.SH" bars={bars} />);
  expect(library.init).toHaveBeenCalledTimes(1);
  expect(chart.createIndicator).toHaveBeenCalledTimes(2);
  view.unmount();
  expect(disconnect).toHaveBeenCalledTimes(1);
  expect(library.dispose).toHaveBeenCalledTimes(1);
});
