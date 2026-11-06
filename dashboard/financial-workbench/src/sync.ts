import { rpc, BridgeError } from "./bridge";
import { storage } from "./storage";
import {
  beginApply,
  endApply,
  isApplying,
  getState,
  loadAppearance,
  loadCardsFrom,
  loadWatchlistFrom,
  loadWatchGroupsFrom,
  CARD_DEFS,
  type CardPrefs,
} from "./store";
import { toast } from "./ui";
interface WatchDocument {
  revision: string;
  groups: string[];
  items: {
    symbol: string;
    name: string;
    groups: string[];
    ts?: string | null;
    notes: { id: string; date: string; text: string }[];
  }[];
}
interface PreferencesDocument {
  revision: string;
  preferences: Record<string, unknown>;
}
let watchRevision = "0",
  prefsRevision = "0";
let cloudPreferences: Record<string, unknown> = {};
let saving = false;
const dirty = new Set<"watchlist" | "preferences">();
function applyWatch(doc: WatchDocument): void {
  watchRevision = doc.revision;
  loadWatchGroupsFrom(doc.groups);
  loadWatchlistFrom(
    doc.items.map((w) => ({
      ...w,
      ts: w.ts ? Date.parse(w.ts) || Date.now() : Date.now(),
      notes: w.notes || [],
    })),
  );
}
export async function hydrate(): Promise<void> {
  // Server snapshots, including empty documents, are authoritative. No legacy import or upload.
  const [watch, prefs] = await Promise.all([
    rpc<WatchDocument>("/finance/watchlist"),
    rpc<PreferencesDocument>("/finance/preferences"),
  ]);
  beginApply();
  try {
    applyWatch(watch);
    prefsRevision = prefs.revision;
    cloudPreferences = prefs.preferences;
    storage.clearPreferences();
    const native = prefs.preferences.native;
    if (native && typeof native === "object" && !Array.isArray(native)) {
      for (const [k, v] of Object.entries(native))
        if (
          typeof v === "string" &&
          k.startsWith("yc_") &&
          !["yc_user", "yc_watchlist", "yc_watch_groups", "yc_token"].includes(
            k,
          )
        )
          storage.setItem(k, v);
    }
    const j = (k: string): unknown => {
      try {
        return JSON.parse(storage.getItem(k) || "null");
      } catch {
        return null;
      }
    };
    loadAppearance({
      theme: j("yc_theme") === "light" ? "light" : "dark",
      dir: j("yc_dir") === "intl" ? "intl" : "cn",
      accent: ["amber", "teal", "indigo", "rose"].includes(
        j("yc_accent") as string,
      )
        ? (j("yc_accent") as "amber")
        : "amber",
    });
    const cards = j("yc_cards") as CardPrefs | null;
    loadCardsFrom(
      Object.fromEntries(
        CARD_DEFS.map((c, i) => [
          c.id,
          {
            on: cards?.[c.id]?.on ?? true,
            mode: cards?.[c.id]?.mode === "detailed" ? "detailed" : "simple",
            order: cards?.[c.id]?.order ?? i,
          },
        ]),
      ),
    );
  } finally {
    endApply();
  }
}
async function save(): Promise<void> {
  if (saving) return;
  saving = true;
  try {
    while (dirty.size) {
      const kind = dirty.values().next().value!;
      dirty.delete(kind);
      try {
        if (kind === "watchlist") {
          const s = getState();
          const doc = await rpc<WatchDocument>("/finance/watchlist", "PUT", {
            revision: watchRevision,
            groups: s.watchGroups,
            items: s.watchlist.map((w) => ({
              ...w,
              ts: new Date(w.ts).toISOString(),
            })),
          });
          watchRevision = doc.revision;
        } else {
          const doc = await rpc<PreferencesDocument>(
            "/finance/preferences",
            "PUT",
            {
              revision: prefsRevision,
              preferences: { ...cloudPreferences, native: storage.snapshot() },
            },
          );
          prefsRevision = doc.revision;
          cloudPreferences = doc.preferences;
        }
      } catch (error) {
        if (error instanceof BridgeError && error.status === 409) {
          dirty.clear();
          await hydrate();
          document.dispatchEvent(new CustomEvent("yc:kprefs"));
          toast("另一窗口已修改，已载入服务器最新版本；请重新操作");
        } else
          toast(
            `同步失败，当前修改尚未保存：${
              error instanceof Error ? error.message : String(error)
            }`,
          );
      }
    }
  } finally {
    saving = false;
  }
}
export function initSync(): void {
  let preferencesTimer = 0;
  document.addEventListener("finerove:native-preference", () => {
    if (isApplying()) return;
    clearTimeout(preferencesTimer);
    preferencesTimer = window.setTimeout(() => {
      dirty.add("preferences");
      void save();
    }, 200);
  });
  document.addEventListener("yc:local", (e) => {
    const kind = (e as CustomEvent).detail;
    dirty.add(kind === "watchlist" ? "watchlist" : "preferences");
    void save();
  });
}
