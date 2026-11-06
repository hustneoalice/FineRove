import "./styles.css";
import { initStorage } from "./storage";
import { initBridge } from "./bridge";
let started = false;
let attempts = 0;
function ready(): void {
  if (started) return;
  if (++attempts > 20) {
    clearInterval(readyTimer);
    const failure = document.createElement("div");
    failure.className = "bempty";
    failure.textContent = "FinRove 会话未连接，请从金融工作台入口重新打开。";
    document.body.replaceChildren(failure);
    return;
  }
  parent.postMessage({ type: "finerove:finance:ready" }, location.origin);
}
const readyTimer = window.setInterval(ready, 500);
window.addEventListener("pagehide", () => clearInterval(readyTimer));
window.addEventListener("message", async (event) => {
  if (event.origin !== location.origin || event.source !== parent) return;
  const d = event.data;
  if (
    started ||
    !d ||
    d.type !== "finerove:finance:init" ||
    typeof d.session !== "string" ||
    !d.session ||
    !Number.isSafeInteger(d.user?.id) ||
    typeof d.user?.username !== "string" ||
    !["zh", "en"].includes(d.locale)
  )
    return;
  started = true;
  clearInterval(readyTimer);
  try {
    initStorage(d.user.id);
    initBridge(
      d.session,
      d.user,
      typeof d.timezone === "string" ? d.timezone : "Asia/Shanghai",
    );
    document.documentElement.lang = d.locale === "en" ? "en" : "zh-CN";
    const sync = await import("./sync");
    await sync.hydrate();
    await import("./main");
    sync.initSync();
  } catch (error) {
    const message = document.createElement("div");
    message.className = "bempty";
    message.textContent = `金融工作台加载失败：${
      error instanceof Error ? error.message : String(error)
    }。请重新打开工作台。`;
    document.body.replaceChildren(message);
  }
});
ready();
