import { storage } from "./storage";
import { identity, rpc } from "./bridge";
import { ic, injectIcons } from "./icons";
import { applyAppearance, getState, patch, setUser, subscribe } from "./store";
import { bindModalChrome, toast } from "./ui";
import { stockSearch } from "./searchbox";
import {
  initMarket,
  klResize,
  openStock,
  renderKline,
  renderRight,
  cancelNeoTrend,
} from "./pages/market";
import { initWatchlist, renderWatchlist } from "./pages/watchlist";
import { initCards, renderCards } from "./pages/cards";
import { initSettings, openSettingsTab } from "./pages/settings";
import { initWatchPanel } from "./watch";
const AVAILABLE = new Set(["market", "watchlist", "cards", "settings"]);
function goPage(p: string): void {
  if (!AVAILABLE.has(p)) {
    toast("此菜单正在迁移，服务尚未接通");
    return;
  }
  document
    .querySelectorAll(".page")
    .forEach((x) => x.classList.toggle("on", x.id === "page-" + p));
  document
    .querySelectorAll<HTMLElement>("#rail a, #mtabs a")
    .forEach((a) => a.classList.toggle("on", a.dataset.page === p));
  if (p === "market") {
    renderKline();
    klResize();
  } else cancelNeoTrend();
  if (p === "watchlist") renderWatchlist();
  if (p === "cards") renderCards();
}
/* ── 全局搜索（共享组件：代码/名称/拼音模糊 + 最近搜索历史 + 涨跌幅回填） ── */
function initSearch(): void {
  const input = document.getElementById("ginput") as HTMLInputElement;
  const drop = document.getElementById("gdrop")!;
  stockSearch({
    input,
    list: drop,
    scope: ".gsearch",
    setVisible: (v) => drop.classList.toggle("on", v),
    onPick: (u) => {
      input.value = "";
      input.blur();
      drop.classList.remove("on");
      if (u.kind === "sector") {
        goPage("sectors");
        return;
      }
      goPage("market");
      void openStock({ symbol: u.symbol, name: u.name || u.symbol });
      toast(`已切换至 ${u.name || u.symbol}`);
    },
  });
  // Cmd/Ctrl+K 聚焦全局搜索
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      input.focus();
      input.select();
    }
  });
}

/* ── 侧栏宽度拖拽（--rail-w，localStorage 持久化） ── */
function initRailResize(): void {
  const grip = document.getElementById("rail-grip")!;
  const apply = (w: number) =>
    document.documentElement.style.setProperty("--rail-w", `${w}px`);
  const saved = Number(storage.getItem("yc_rail_w"));
  if (saved >= 48 && saved <= 220) apply(saved);
  grip.addEventListener("mousedown", (e) => {
    e.preventDefault();
    grip.classList.add("on");
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    const move = (ev: MouseEvent) => {
      // 预留拖拽手柄自身 3px 悬出，取指针位置即目标宽度
      const w = Math.min(220, Math.max(48, ev.clientX));
      apply(w);
      storage.setItem("yc_rail_w", String(w));
      // 行情页图表跟随重排
      clearTimeout((window as unknown as { _rz?: number })._rz);
      (window as unknown as { _rz?: number })._rz = window.setTimeout(() => {
        if (document.getElementById("page-market")!.classList.contains("on"))
          klResize();
      }, 120);
    };
    const up = () => {
      grip.classList.remove("on");
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  });
}

/* ── 设备模式（桌面 / 折叠屏 / 普通屏）：三款宽度，body.mobile+f/phone 驱动布局 ── */
type DeviceMode = "desktop" | "fold" | "phone";
function applyDevice(m: DeviceMode, persist = true): void {
  document.body.classList.toggle("mobile", m !== "desktop");
  document.body.classList.toggle("fold", m === "fold");
  document.body.classList.toggle("phone", m === "phone");
  document
    .querySelectorAll<HTMLElement>("#dev-toggle button")
    .forEach((b) => b.classList.toggle("on", b.dataset.dev === m));
  if (persist) storage.setItem("yc_device", m);
  if (document.getElementById("page-market")!.classList.contains("on"))
    klResize();
}
function initDevice(): void {
  const saved = storage.getItem("yc_device") as DeviceMode | null;
  const w = window.innerWidth;
  const auto: DeviceMode = w <= 480 ? "phone" : w <= 820 ? "fold" : "desktop";
  const mode: DeviceMode =
    saved === "desktop" || saved === "fold" || saved === "phone" ? saved : auto;
  applyDevice(mode, saved != null); // 首次访问跟随视口且不落盘，手动切换后才记忆
  document.getElementById("dev-toggle")!.addEventListener("click", (e) => {
    const b = (e.target as HTMLElement).closest<HTMLElement>(
      "button[data-dev]",
    );
    if (b) applyDevice(b.dataset.dev as DeviceMode);
  });
  document
    .querySelectorAll<HTMLElement>("#mtabs a")
    .forEach((a) => a.addEventListener("click", () => goPage(a.dataset.page!)));
  // 移动端行情页「图表 / 卡片」分段：卡片态隐藏 K 线列，直达信息卡片区免滚动
  document.getElementById("m-mkt-seg")!.addEventListener("click", (e) => {
    const b = (e.target as HTMLElement).closest<HTMLElement>("button[data-mv]");
    if (!b) return;
    const cards = b.dataset.mv === "cards";
    document.body.classList.toggle("m-cards", cards);
    document
      .querySelectorAll<HTMLElement>("#m-mkt-seg button")
      .forEach((x) => x.classList.toggle("on", x === b));
    if (!cards) klResize();
  });
}

function boot(): void {
  applyAppearance();
  injectIcons();
  bindModalChrome();
  setUser({
    id: String(identity.id),
    username: identity.username,
    display_name: identity.display_name,
    email: "",
    tier: "free",
    role: "user",
  });
  document.getElementById("user-name")!.textContent =
    identity.display_name || identity.username;
  document.getElementById("user-ava")!.textContent = (
    identity.display_name || identity.username
  ).slice(0, 1);
  document.getElementById("userchip")!.title = "FinRove 统一账户";
  document.getElementById("vipbadge-t")!.textContent = "NEO 自研指标";
  document.getElementById("vipbadge")!.addEventListener("click", () => {
    goPage("settings");
    openSettingsTab("vip");
  });
  document.getElementById("userchip")!.addEventListener("click", () => {
    goPage("settings");
    openSettingsTab("account");
  });
  document.querySelectorAll<HTMLElement>("#rail a, #mtabs a").forEach((a) => {
    if (!AVAILABLE.has(a.dataset.page || "")) {
      a.setAttribute("aria-disabled", "true");
      a.title = "此菜单正在迁移，服务尚未接通";
      a.style.opacity = ".45";
    }
    a.addEventListener("click", () => goPage(a.dataset.page!));
  });
  initDevice();
  initRailResize();
  initSearch();
  initMarket();
  initWatchlist();
  initCards();
  initSettings();
  initWatchPanel();
  const btn = document.getElementById("btn-theme")!;
  const drawTheme = (): void => {
    btn.innerHTML = ic(getState().theme === "dark" ? "moon" : "sun", 16);
  };
  drawTheme();
  btn.addEventListener("click", () =>
    patch("theme", getState().theme === "dark" ? "light" : "dark"),
  );
  subscribe(drawTheme);
  document.getElementById("datachip")!.addEventListener("click", () => {
    goPage("settings");
    openSettingsTab("data");
  });
  void rpc<{ available?: boolean; provider?: string }>("/finance/market/status")
    .then((status) => {
      document.getElementById("datachip-t")!.textContent =
        status.available === false ? "行情服务未连接" : "行情服务已连接";
    })
    .catch(() => {
      document.getElementById("datachip-t")!.textContent = "行情服务未连接";
    });
  document.addEventListener("yc:goto-page", (e) =>
    goPage((e as CustomEvent).detail),
  );
  document.addEventListener("yc:open-stock", (e) => {
    goPage("market");
    const d = (e as CustomEvent).detail;
    void openStock(d, d.from);
  });
  document.addEventListener("yc:open-sector", () => goPage("sectors"));
  document.addEventListener("yc:goto-settings", (e) => {
    goPage("settings");
    openSettingsTab((e as CustomEvent).detail);
  });
  document.addEventListener("yc:patch-theme", (e) =>
    patch("theme", (e as CustomEvent).detail),
  );
  subscribe(() => {
    applyAppearance();
    if (document.getElementById("page-market")!.classList.contains("on")) {
      renderRight();
      renderKline();
    }
  });
  void openStock({ symbol: "000001.SH", name: "上证指数" });
}
boot();
