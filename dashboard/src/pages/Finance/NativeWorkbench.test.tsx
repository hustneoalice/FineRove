import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import NativeWorkbench from "./NativeWorkbench";

const api = vi.hoisted(() => ({ request: vi.fn(), token: "local-session" }));
vi.mock("../../api/request", () => ({
  request: api.request,
  getAuthToken: () => api.token,
}));
vi.mock("../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));

beforeEach(() => {
  api.token = "local-session";
  api.request.mockReset().mockImplementation((path: string) => {
    if (path === "/auth/me")
      return Promise.resolve({ id: 1, username: "neo", locale: "zh" });
    return Promise.resolve({ symbol: "600519.SH", bars: [] });
  });
});

function message(
  frame: HTMLIFrameElement,
  data: object,
  source: Window | null = frame.contentWindow,
) {
  fireEvent(
    window,
    new MessageEvent("message", {
      data,
      source,
      origin: window.location.origin,
    }),
  );
}

it("initializes the original workbench without sending a bearer credential", async () => {
  render(<NativeWorkbench />);
  const frame = screen.getByTitle("NEO 原生看盘工作台") as HTMLIFrameElement;
  const send = vi.spyOn(frame.contentWindow!, "postMessage");
  message(frame, { type: "finerove:finance:ready" });
  await waitFor(() => expect(send).toHaveBeenCalled());
  expect(send.mock.calls[0][0]).toMatchObject({
    type: "finerove:finance:init",
    user: { id: 1 },
  });
  expect(JSON.stringify(send.mock.calls)).not.toContain("local-session");
});

it("only forwards fixed finance paths from its own frame", async () => {
  render(<NativeWorkbench />);
  const frame = screen.getByTitle("NEO 原生看盘工作台") as HTMLIFrameElement;
  const send = vi.spyOn(frame.contentWindow!, "postMessage");
  message(frame, { type: "finerove:finance:ready" });
  await waitFor(() => expect(send).toHaveBeenCalled());
  const session = send.mock.calls[0][0].session;
  message(
    frame,
    {
      type: "finerove:finance:request",
      session,
      id: "a",
      path: "/finance/market/kline?symbol=600519.SH",
      method: "GET",
    },
    window,
  );
  message(frame, {
    type: "finerove:finance:request",
    session,
    id: "b",
    path: "/admin/users",
    method: "GET",
  });
  await waitFor(() =>
    expect(send.mock.calls.some(([value]) => value.id === "b")).toBe(true),
  );
  expect(api.request.mock.calls).toHaveLength(1);
  message(frame, {
    type: "finerove:finance:request",
    session,
    id: "c",
    path: "/finance/market/kline?symbol=600519.SH",
    method: "GET",
  });
  await waitFor(() => expect(api.request).toHaveBeenCalledTimes(2));
});

it("aborts pending work when leaving the workbench", async () => {
  const view = render(<NativeWorkbench />);
  const frame = screen.getByTitle("NEO 原生看盘工作台") as HTMLIFrameElement;
  const send = vi.spyOn(frame.contentWindow!, "postMessage");
  message(frame, { type: "finerove:finance:ready" });
  await waitFor(() => expect(send).toHaveBeenCalled());
  api.request.mockImplementationOnce(() => new Promise(() => {}));
  message(frame, {
    type: "finerove:finance:request",
    session: send.mock.calls[0][0].session,
    id: "c",
    path: "/finance/market/kline?symbol=600519.SH",
    method: "GET",
  });
  await waitFor(() => expect(api.request).toHaveBeenCalledTimes(2));
  const signal = api.request.mock.calls[1][1].signal as AbortSignal;
  view.unmount();
  expect(signal.aborted).toBe(true);
});

it("reloads the child before a replaced login can receive another account's data", async () => {
  render(<NativeWorkbench />);
  const frame = screen.getByTitle("NEO 原生看盘工作台") as HTMLIFrameElement;
  const send = vi.spyOn(frame.contentWindow!, "postMessage");
  message(frame, { type: "finerove:finance:ready" });
  await waitFor(() => expect(send).toHaveBeenCalled());
  api.token = "replacement-session";
  message(frame, {
    type: "finerove:finance:request",
    session: send.mock.calls[0][0].session,
    id: "c",
    path: "/finance/watchlist",
    method: "GET",
  });
  await waitFor(() =>
    expect(screen.getByTitle("NEO 原生看盘工作台")).not.toBe(frame),
  );
  expect(api.request).toHaveBeenCalledTimes(1);
});
