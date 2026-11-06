/** Public transport and date mapping only. Indicator formulas stay on the private server. */
import type { Bar } from "./api";
import { rpc } from "./bridge";

export interface TrendPoint {
  date: string;
  value: number | null;
}
export interface TrendResult {
  instrument_id: string;
  adjust: string;
  input_snapshot_id: string;
  rule_version: string;
  as_of: string | null;
  points: TrendPoint[];
  warnings: string[];
  coverage: { bars: number; warmup_limit: number };
}

export function makeTrendRequest(
  symbol: string,
  bars: Bar[],
  now = new Date(),
) {
  if (!/^(6\d{5}\.SH|[03]\d{5}\.SZ)$/.test(symbol))
    throw new Error("NEO 趋势柱线当前支持沪深 A 股日线，请选择个股");
  const today = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
  const input = bars
    .filter((b) => b.date.length === 10 && b.date < today)
    .slice(-2000)
    .map((b) => ({
      date: b.date,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
      volume: b.volume ?? null,
      amount: b.amount ?? null,
    }));
  if (!input.length) throw new Error("暂无已收盘日线可供 NEO 计算");
  const [code, exchange] = symbol.split(".");
  return {
    capability: "neo.trend_histogram" as const,
    instrument_id: `CN:${exchange}:stock:${code}`,
    period: "day" as const,
    adjust: "qfq" as const,
    end: input.at(-1)!.date,
    limit: Math.min(500, input.length),
    bars: input,
  };
}

export function alignTrendPoints(
  bars: { date: string }[],
  points: TrendPoint[],
) {
  const byDate = new Map(points.map((p) => [p.date, p.value]));
  return bars.map((b) => ({ value: byDate.get(b.date) ?? null }));
}

export const evaluateTrend = (
  body: ReturnType<typeof makeTrendRequest>,
  signal: AbortSignal,
) => rpc<TrendResult>("/finance/neo/evaluate", "POST", body, signal);
