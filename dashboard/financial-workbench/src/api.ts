import { rpc } from "./bridge";
export interface UserPublic {
  id: string;
  username?: string | null;
  email: string;
  tier: "free" | "pro";
  role: string;
  display_name?: string;
}
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}
interface ReqOpts {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  raw?: boolean;
}
const MARKET_ROUTES = new Set([
  "status",
  "search",
  "kline",
  "minute",
  "quote",
  "quotes",
  "indices",
  "sparks",
  "depth",
  "trades",
  "news",
  "reports",
  "shareholders",
  "fundflow",
]);
async function req<T>(path: string, opts?: ReqOpts): Promise<T> {
  const url = new URL(path, location.origin);
  const name = url.pathname.replace("/market/", "");
  if (!url.pathname.startsWith("/market/") || !MARKET_ROUTES.has(name))
    throw new ApiError(
      503,
      "migration_unavailable",
      "此功能尚未接入 FinRove 行情服务",
    );
  if (name === "kline") {
    url.searchParams.delete("with");
    url.searchParams.set(
      "limit",
      String(
        Math.min(
          1000,
          Math.max(1, Number(url.searchParams.get("limit") || 1000)),
        ),
      ),
    );
  }
  return rpc<T>(
    "/finance" + url.pathname + url.search,
    "GET",
    undefined,
    opts?.signal,
  );
}

export interface Bar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number | null;
  amount?: number | null;
  pct_chg?: number | null;
  turnover_rate?: number | null;
  indicators?: Record<string, number | null> | null;
}
export interface Kline {
  symbol: string;
  name?: string;
  period: string;
  adjust: string;
  bars: Bar[];
}
export interface Quote {
  symbol: string;
  name?: string;
  market?: string;
  industry?: string;
  concept?: string;
  status?: string;
  date?: string;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  pct_chg?: number;
  volume?: number;
  amount?: number;
  turnover_rate?: number;

  rt_price?: number;
  rt_time?: string;
  rt_date?: string;
  rt_live?: boolean;
  rt_prev_close?: number;
  valuation?: {
    date: string;
    pe_ttm?: number;
    pb?: number;
    ps_ttm?: number;
    total_mv?: number;
    circ_mv?: number;
  } | null;
  capital_flow?: {
    date: string;
    net_main?: number;
    net_super?: number;
    net_large?: number;
    net_medium?: number;
    net_small?: number;
  } | null;
}
export interface SearchHit {
  symbol: string;
  name?: string;
  market?: string;
  industry?: string;
  status?: string;
  kind?: "stock" | "fund" | "index" | "sector";
  sub?: string | null;
}

export interface IndexQuote {
  symbol: string;
  name: string;
  price?: number | null;
  chg?: number | null;
  pct?: number | null;
  amount?: number | null;
}

export interface FundFlowTotals {
  net_main?: number | null;
  net_super?: number | null;
  net_large?: number | null;
  net_medium?: number | null;
  net_small?: number | null;
}
export interface FundFlowRange {
  symbol: string;
  start?: string | null;
  end?: string | null;
  items: ({ date: string } & FundFlowTotals)[];
  totals?: FundFlowTotals | null;
  covered: number;
  available: boolean;
  note?: string | null;
}
export interface NewsItem {
  time: string;
  source: string;
  title: string;
  summary: string;
  url: string;
}
export interface ReportItem {
  date: string;
  org: string;
  rating: string;
  title: string;
  industry: string;
  url: string;
}

const query = (q: Record<string, unknown>): string =>
  new URLSearchParams(
    Object.entries(q)
      .filter(([, v]) => v != null)
      .map(([k, v]) => [k, String(v)]),
  ).toString();
interface SparkItem {
  symbol: string;
  prev_close: number | null;
  points: number[];
}
async function batches<T>(
  symbols: string[],
  size: number,
  path: string,
): Promise<{ items: T[]; missing: string[] }> {
  const out: { items: T[]; missing: string[] } = { items: [], missing: [] };
  for (let i = 0; i < symbols.length; i += size) {
    const result = await req<{ items: T[]; missing: string[] }>(
      path +
        "?symbols=" +
        encodeURIComponent(symbols.slice(i, i + size).join(",")),
    );
    out.items.push(...result.items);
    out.missing.push(...result.missing);
  }
  return out;
}
export const marketApi = {
  kline: (
    q: {
      symbol: string;
      adjust?: string;
      with?: string;
      limit?: number;
      start?: string;
      end?: string;
      freq?: string;
    },
    opts?: { signal?: AbortSignal },
  ) => req<Kline>("/market/kline?" + query(q), opts),
  minute: (symbol: string) =>
    req<{
      symbol: string;
      date: string;
      prev_close?: number;
      bars: (Bar & { avg: number; has_avg?: boolean })[];
    }>("/market/minute?" + query({ symbol })),
  quote: (symbol: string, opts?: { signal?: AbortSignal }) =>
    req<Quote>("/market/quote?" + query({ symbol }), opts),
  quotes: (symbols: string[]) => batches<Quote>(symbols, 50, "/market/quotes"),
  sparks: (symbols: string[]) =>
    batches<SparkItem>(symbols, 20, "/market/sparks"),
  search: (q: string, limit = 10, kinds?: string[]) =>
    req<{ items: SearchHit[]; total: number }>(
      "/market/search?" + query({ q, limit, kinds: kinds?.join(",") }),
    ),
  indices: () =>
    req<{ items: IndexQuote[]; total_amount?: number | null }>(
      "/market/indices",
    ),
  fundflow: (q: {
    symbol: string;
    start?: string;
    end?: string;
    limit?: number;
  }) => req<FundFlowRange>("/market/fundflow?" + query(q)),
  news: (symbol: string, limit = 12) =>
    req<{ items: NewsItem[] }>("/market/news?" + query({ symbol, limit })),
  reports: (symbol: string, limit = 12) =>
    req<{ items: ReportItem[] }>("/market/reports?" + query({ symbol, limit })),
  industryReports: (
    _symbol: string,
    _limit = 12,
  ): Promise<{ industry: string; items: ReportItem[]; skipped?: boolean }> =>
    Promise.reject(
      new ApiError(503, "migration_unavailable", "行业研报服务尚未接入"),
    ),
};
