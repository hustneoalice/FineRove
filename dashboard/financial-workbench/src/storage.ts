let prefix = "";
export function initStorage(userId: number): void {
  if (!Number.isSafeInteger(userId) || userId < 1) throw new Error("无效账户");
  prefix = `finerove.financial.${userId}.`;
}
function key(name: string): string {
  if (!prefix) throw new Error("金融账户尚未初始化");
  return prefix + name;
}
function changed(name: string): void {
  if (
    !["yc_watchlist", "yc_watch_groups", "yc_user", "yc_token"].includes(name)
  )
    document.dispatchEvent(new Event("finerove:native-preference"));
}
export const storage = {
  getItem(name: string): string | null {
    return localStorage.getItem(key(name));
  },
  setItem(name: string, value: string): void {
    localStorage.setItem(key(name), value);
    changed(name);
  },
  removeItem(name: string): void {
    localStorage.removeItem(key(name));
    changed(name);
  },
  clearPreferences(): void {
    for (const name of Object.keys(storage.snapshot()))
      storage.removeItem(name);
  },
  snapshot(): Record<string, string> {
    if (!prefix) throw new Error("金融账户尚未初始化");
    const out: Record<string, string> = {};
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (
        k?.startsWith(prefix) &&
        !["yc_watchlist", "yc_watch_groups", "yc_user", "yc_token"].includes(
          k.slice(prefix.length),
        )
      )
        out[k.slice(prefix.length)] = localStorage.getItem(k)!;
    }
    return out;
  },
};
