import { getState, patch } from "../store";
import { ic } from "../icons";
import { esc } from "../fmt";
import { toast } from "../ui";
const NAV: [string, string, string][] = [
  ["data", "数据底座", "database"],
  ["look", "外观", "circle-half"],
  ["vip", "VIP 与订阅", "crown-simple"],
  ["account", "账户", "user"],
  ["feishu", "飞书推送", "paper-plane-tilt"],
  ["llm", "大模型", "spark"],
];
let tab = "look";
export function openSettingsTab(t: string): void {
  tab = NAV.some((n) => n[0] === t) ? t : "look";
  render();
}
function render(): void {
  document.getElementById("setnav")!.innerHTML = NAV.map(
    (n) =>
      `<button data-set="${n[0]}" class="${tab === n[0] ? "on" : ""}">${ic(
        n[2],
        15,
      )}<span>${n[1]}</span></button>`,
  ).join("");
  document
    .querySelectorAll<HTMLElement>("#setnav button")
    .forEach((b) =>
      b.addEventListener("click", () => openSettingsTab(b.dataset.set!)),
    );
  const body = document.getElementById("setbody")!;
  if (tab === "look") {
    renderLook(body);
    return;
  }
  if (tab === "account") {
    body.innerHTML = `<div class="setsec"><h3>FinRove 统一账户</h3><p>${esc(
      getState().user?.display_name || getState().user?.username || "",
    )}</p><p>账户及退出登录由外层 FinRove 账户菜单统一管理。</p></div>`;
    return;
  }
  body.innerHTML = `<div class="setsec"><h3>${NAV.find(
    (n) => n[0] === tab,
  )?.[1]}</h3><div class="bempty">${
    tab === "vip"
      ? "NEO 趋势柱线可在看盘页按需计算，权限由私服校验；其他自研指标尚未接入。"
      : "此服务正在迁移，请通过 FinRove 统一设置管理。原服务凭据和操作未接入。"
  }</div></div>`;
}
export function initSettings(): void {
  render();
}
function renderLook(body: HTMLElement): void {
  const s = getState();
  const swc: [string, string][] = [
    ["amber", "#FF9F43"],
    ["teal", "#2FD3C5"],
    ["indigo", "#8A94FF"],
    ["rose", "#F07C93"],
  ];
  body.innerHTML =
    `<div class="setsec"><div class="sh">${ic(
      "circle-half",
      15,
    )}<h3>外观与主题</h3></div>` +
    `<div class="setrow"><span class="lab">主题</span><div class="ctl"><span class="seg" id="set-theme">` +
    `<button class="${
      s.theme === "dark" ? "on" : ""
    }" data-t="dark">深色 · 看盘默认</button>` +
    `<button class="${
      s.theme === "light" ? "on" : ""
    }" data-t="light">浅色 · 文档</button></span></div></div>` +
    `<div class="setrow"><span class="lab">强调色</span><div class="ctl"><span class="swatches">` +
    swc
      .map(
        (c) =>
          `<span class="sw${s.accent === c[0] ? " on" : ""}" data-ac="${
            c[0]
          }" style="background:color-mix(in srgb,${
            c[1]
          } 18%,transparent)"><i style="background:${c[1]}"></i></span>`,
      )
      .join("") +
    `</span><span style="font-size:11px;color:var(--faint)">色度纪律：大面积底色 ≤0.04 · 强调 0.08–0.15 · 点睛 ≤0.22</span></div></div>` +
    `<div class="setrow"><span class="lab">涨跌方向</span><div class="ctl"><span class="seg" id="set-dir">` +
    `<button class="${
      s.dir === "cn" ? "on" : ""
    }" data-d="cn">红涨绿跌 · A股</button>` +
    `<button class="${
      s.dir === "intl" ? "on" : ""
    }" data-d="intl">绿涨红跌 · 国际</button></span></div></div></div>`;
  document.getElementById("set-theme")!.addEventListener("click", (e) => {
    const b = (e.target as HTMLElement).closest("button") as HTMLElement | null;
    if (b) {
      patch("theme", b.dataset.t as "dark" | "light");
      void render();
    }
  });
  document.getElementById("set-dir")!.addEventListener("click", (e) => {
    const b = (e.target as HTMLElement).closest("button") as HTMLElement | null;
    if (b) {
      patch("dir", b.dataset.d as "cn" | "intl");
      void render();
      toast("涨跌方向已切换");
    }
  });
  body.querySelectorAll<HTMLElement>(".sw[data-ac]").forEach((el) =>
    el.addEventListener("click", () => {
      patch("accent", el.dataset.ac as never);
      void render();
    }),
  );
}
