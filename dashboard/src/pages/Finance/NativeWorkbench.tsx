import { useEffect, useRef, useState } from "react";
import { Alert, Button, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { getAuthToken, request } from "../../api/request";
import { useServerTimezone } from "../../hooks/useServerTimezone";

const readable = new Set([
  "/finance/market/status",
  "/finance/market/search",
  "/finance/market/kline",
  "/finance/market/minute",
  "/finance/market/quote",
  "/finance/market/quotes",
  "/finance/market/indices",
  "/finance/market/sparks",
  "/finance/market/depth",
  "/finance/market/trades",
  "/finance/market/news",
  "/finance/market/reports",
  "/finance/market/shareholders",
  "/finance/market/fundflow",
  "/finance/watchlist",
  "/finance/preferences",
  "/finance/neo/catalog",
]);
const writable = new Set(["/finance/watchlist", "/finance/preferences"]);

export default function NativeWorkbench() {
  const { t, i18n } = useTranslation();
  const timezone = useServerTimezone();
  const locale = i18n.language.startsWith("zh") ? "zh" : "en";
  const frame = useRef<HTMLIFrameElement>(null);
  const [cycle, setCycle] = useState(0);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const rejectedMessage = t(
    "finance.native.rejected",
    "此操作暂未接入工作台。",
  );
  const tooLargeMessage = t(
    "finance.native.tooLarge",
    "保存内容过大，请减少后重试。",
  );
  const failureMessage = t(
    "finance.native.failed",
    "数据暂不可用，请稍后重试。",
  );

  useEffect(() => {
    const pending = new Map<string, AbortController>();
    const identity = new AbortController();
    const session = crypto.randomUUID();
    let token = "";
    let initialized = false;
    let initializing = false;
    let disposed = false;
    setReady(false);
    setError("");
    const send = (value: object) => {
      if (!disposed)
        frame.current?.contentWindow?.postMessage(
          value,
          window.location.origin,
        );
    };
    const reset = () => {
      pending.forEach((controller) => controller.abort());
      initialized = false;
      setCycle((value) => value + 1);
    };
    const receive = async (event: MessageEvent) => {
      if (
        event.origin !== window.location.origin ||
        event.source !== frame.current?.contentWindow
      )
        return;
      const data = event.data as Record<string, unknown> | null;
      if (!data || typeof data !== "object") return;
      if (data.type === "finerove:finance:ready") {
        if (initializing) return;
        initializing = true;
        try {
          token = getAuthToken();
          const user = await request<{
            id: number;
            username: string;
            display_name?: string | null;
            locale?: string;
          }>("/auth/me", { signal: identity.signal });
          if (disposed) return;
          if (getAuthToken() !== token) {
            reset();
            return;
          }
          initialized = true;
          send({
            type: "finerove:finance:init",
            session,
            user,
            locale,
            timezone,
          });
          setReady(true);
        } catch (reason) {
          if (!disposed)
            setError(reason instanceof Error ? reason.message : String(reason));
        } finally {
          initializing = false;
        }
        return;
      }
      if (
        !initialized ||
        data.session !== session ||
        typeof data.id !== "string"
      )
        return;
      if (data.type === "finerove:finance:cancel") {
        pending.get(data.id)?.abort();
        return;
      }
      if (data.type !== "finerove:finance:request") return;
      // A renewed or replaced login starts a fresh child document. It must never
      // write a different account's response into the previous account's cache.
      if (token !== getAuthToken()) {
        reset();
        return;
      }
      const path = typeof data.path === "string" ? data.path : "";
      const method =
        data.method === "PUT" || data.method === "POST" ? data.method : "GET";
      let allowed = false;
      try {
        const url = new URL(path, window.location.origin);
        allowed =
          path.startsWith("/finance/") &&
          url.origin === window.location.origin &&
          (method === "GET"
            ? readable.has(url.pathname)
            : method === "PUT"
            ? writable.has(url.pathname)
            : url.pathname === "/finance/neo/evaluate");
      } catch {
        /* rejected below */
      }
      if (!allowed || pending.has(data.id) || pending.size >= 32) {
        send({
          type: "finerove:finance:response",
          session,
          id: data.id,
          error: { status: 400, message: rejectedMessage },
        });
        return;
      }
      const controller = new AbortController();
      pending.set(data.id, controller);
      try {
        const body =
          data.body === undefined ? undefined : JSON.stringify(data.body);
        if (body && body.length > 1024 * 1024) throw new Error(tooLargeMessage);
        const result = await request<unknown>(path, {
          method,
          body,
          signal: controller.signal,
        });
        if (token !== getAuthToken()) {
          reset();
          return;
        }
        if (!controller.signal.aborted)
          send({
            type: "finerove:finance:response",
            session,
            id: data.id,
            result,
          });
      } catch (reason) {
        if (!controller.signal.aborted) {
          const raw = reason instanceof Error ? reason.message : String(reason);
          const status = Number(
            raw.match(/Request failed: (\d{3})/)?.[1] ?? 502,
          );
          let message = failureMessage;
          try {
            const payload = JSON.parse(raw.slice(raw.indexOf(" - ") + 3)) as {
              detail?: unknown;
              error?: { message?: string };
            };
            if (typeof payload.detail === "string") message = payload.detail;
            else if (payload.error?.message) message = payload.error.message;
          } catch {
            /* keep localized message */
          }
          send({
            type: "finerove:finance:response",
            session,
            id: data.id,
            error: { status, message },
          });
        }
      } finally {
        pending.delete(data.id);
      }
    };
    const listener = (event: MessageEvent) => {
      void receive(event);
    };
    const authChanged = (event: StorageEvent) => {
      if (event.key === "auth_token") reset();
    };
    window.addEventListener("message", listener);
    window.addEventListener("storage", authChanged);
    return () => {
      disposed = true;
      identity.abort();
      pending.forEach((controller) => controller.abort());
      window.removeEventListener("message", listener);
      window.removeEventListener("storage", authChanged);
    };
  }, [
    cycle,
    locale,
    timezone,
    rejectedMessage,
    tooLargeMessage,
    failureMessage,
  ]);

  return (
    <div
      style={{
        width: "100%",
        height: "calc(100dvh - 72px)",
        minHeight: 600,
        position: "relative",
        background: "#0a0a0b",
      }}
    >
      {error && (
        <Alert
          type="error"
          message={error}
          action={
            <Button onClick={() => setCycle((value) => value + 1)}>
              {t("finance.retry", "重试")}
            </Button>
          }
        />
      )}
      {!ready && !error && (
        <Spin style={{ position: "absolute", top: 24, left: "50%" }} />
      )}
      <iframe
        key={`${cycle}:${locale}:${timezone}`}
        ref={frame}
        src={`/financial-workbench/index.html?v=${cycle}&locale=${locale}&timezone=${encodeURIComponent(
          timezone,
        )}`}
        title={t("finance.native.title", "NEO 原生看盘工作台")}
        style={{ border: 0, width: "100%", height: "100%", display: "block" }}
      />
    </div>
  );
}
