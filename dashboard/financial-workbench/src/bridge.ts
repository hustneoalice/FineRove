export interface Identity {
  id: number;
  username: string;
  display_name?: string;
  locale?: string;
}
export let identity: Identity;
export let serverTimezone = "Asia/Shanghai";
let session = "";
type Pending = {
  resolve: (v: unknown) => void;
  reject: (e: Error) => void;
  cleanup: () => void;
};
const pending = new Map<string, Pending>();
export class BridgeError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export function initBridge(
  nextSession: string,
  user: Identity,
  timezone: string,
): void {
  session = nextSession;
  identity = user;
  serverTimezone = timezone;
}
window.addEventListener("message", (event) => {
  if (event.origin !== location.origin || event.source !== parent) return;
  const d = event.data;
  if (
    !d ||
    d.type !== "finerove:finance:response" ||
    d.session !== session ||
    typeof d.id !== "string"
  )
    return;
  const p = pending.get(d.id);
  if (!p) return;
  p.cleanup();
  if (d.error)
    p.reject(
      new BridgeError(
        Number(d.error.status) || 500,
        String(d.error.message || "金融服务请求失败"),
      ),
    );
  else p.resolve(d.result);
});
export function rpc<T>(
  path: string,
  method: "GET" | "PUT" | "POST" = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  if (!session) return Promise.reject(new Error("FinRove 会话尚未建立"));
  if (signal?.aborted)
    return Promise.reject(new DOMException("请求已取消", "AbortError"));
  if (pending.size >= 32)
    return Promise.reject(new Error("请求繁忙，请稍后重试"));
  return new Promise<T>((resolve, reject) => {
    const id = crypto.randomUUID();
    const cancel = (error: Error): void => {
      const p = pending.get(id);
      if (!p) return;
      p.cleanup();
      parent.postMessage(
        { type: "finerove:finance:cancel", session, id },
        location.origin,
      );
      reject(error);
    };
    const abort = (): void =>
      cancel(new DOMException("请求已取消", "AbortError"));
    const timer = window.setTimeout(
      () => cancel(new BridgeError(504, "行情服务请求超时")),
      25000,
    );
    const cleanup = (): void => {
      clearTimeout(timer);
      pending.delete(id);
      signal?.removeEventListener("abort", abort);
    };
    pending.set(id, { resolve: (v) => resolve(v as T), reject, cleanup });
    signal?.addEventListener("abort", abort, { once: true });
    parent.postMessage(
      {
        type: "finerove:finance:request",
        session,
        id,
        path,
        method,
        ...(body === undefined ? {} : { body }),
      },
      location.origin,
    );
  });
}
window.addEventListener("pagehide", () => {
  for (const [id, p] of pending) {
    parent.postMessage(
      { type: "finerove:finance:cancel", session, id },
      location.origin,
    );
    p.cleanup();
    p.reject(new DOMException("工作台已关闭", "AbortError"));
  }
});
