import { request } from "../request";

export type Adjustment = "raw" | "qfq" | "hfq";
export interface MarketSecurity {
  symbol: string;
  name: string | null;
  market?: string | null;
  kind?: string | null;
}
export interface MarketBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number | null;
  amount?: number | null;
  pct_chg?: number | null;
  turnover_rate?: number | null;
  live?: boolean;
}
export interface MarketKline {
  symbol: string;
  name?: string | null;
  period: "day";
  adjust: Adjustment;
  bars: MarketBar[];
}
export interface MarketQuote {
  symbol: string;
  name?: string | null;
  price?: number | null;
  close?: number | null;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  volume?: number | null;
  amount?: number | null;
  pct_chg?: number | null;
  date?: string;
}
export interface WatchlistDocument {
  revision: string;
  groups: string[];
  items: { symbol: string; name: string; groups: string[] }[];
}
export const marketApi = {
  status: (signal?: AbortSignal) =>
    request<{ configured: boolean }>("/finance/market/status", { signal }),
  search: (q: string, signal?: AbortSignal) =>
    request<{ items: MarketSecurity[]; total: number }>(
      `/finance/market/search?${new URLSearchParams({ q, limit: "20" })}`,
      { signal },
    ),
  kline: (symbol: string, adjust: Adjustment, signal?: AbortSignal) =>
    request<MarketKline>(
      `/finance/market/kline?${new URLSearchParams({
        symbol,
        adjust,
        limit: "500",
      })}`,
      { signal },
    ),
  quote: (symbol: string, signal?: AbortSignal) =>
    request<MarketQuote>(
      `/finance/market/quote?${new URLSearchParams({ symbol })}`,
      { signal },
    ),
  watchlist: (signal?: AbortSignal) =>
    request<WatchlistDocument>("/finance/watchlist", { signal }),
  saveWatchlist: (document: WatchlistDocument, signal?: AbortSignal) =>
    request<WatchlistDocument>("/finance/watchlist", {
      method: "PUT",
      body: JSON.stringify(document),
      signal,
    }),
};
