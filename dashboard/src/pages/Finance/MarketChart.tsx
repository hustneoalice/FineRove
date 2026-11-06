/* SPDX-License-Identifier: AGPL-3.0-only
 * Generic candle styling adapted from YuChao frontend/src/pages/kline.ts
 * lines 25-27 and 1111-1131 (local source /Users/neo/workspace/yuchao,
 * GNU AGPL v3, https://www.gnu.org/licenses/agpl-3.0.html).
 * Only hollow rising / solid falling candle presentation is reused.
 * No YuChao indicator calculations or proprietary formulas are included.
 */
import { useEffect, useRef } from "react";
import { init, dispose } from "klinecharts";
import { theme } from "antd";
import { useTranslation } from "react-i18next";
import type { MarketBar } from "../../api/modules/market";

export default function MarketChart({
  symbol,
  bars,
}: {
  symbol: string;
  bars: MarketBar[];
}) {
  const { t, i18n } = useTranslation();
  const locale = i18n.language.startsWith("zh") ? "zh-CN" : "en-US";
  const container = useRef<HTMLDivElement>(null);
  const { token } = theme.useToken();
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const chart = init(element, {
      styles: {
        grid: { show: false },
        candle: {
          type: "candle_solid",
          bar: ({ current }) => {
            const up = "#EF5350",
              down = "#519C2C",
              neutral = "#757575";
            if (!current)
              return {
                color: neutral,
                borderColor: neutral,
                wickColor: neutral,
              };
            const color =
              current.close > current.open
                ? up
                : current.close < current.open
                ? down
                : neutral;
            return {
              color:
                current.close > current.open ? token.colorBgContainer : color,
              borderColor: color,
              wickColor: color,
            };
          },
        },
      },
    });
    if (!chart) return;
    chart.setLocale(locale);
    chart.setTimezone("Asia/Shanghai");
    chart.setDataLoader({
      getBars: ({ callback, type }) =>
        callback(
          type === "init"
            ? bars.map((bar) => ({
                ...bar,
                volume: bar.volume ?? undefined,
                turnover: bar.amount ?? undefined,
                timestamp: new Date(`${bar.date}T00:00:00+08:00`).getTime(),
              }))
            : [],
          false,
        ),
    });
    chart.setSymbol({ ticker: symbol, pricePrecision: 2, volumePrecision: 0 });
    chart.setPeriod({ span: 1, type: "day" });
    chart.createIndicator({ name: "MA", paneId: "candle_pane" }, true);
    chart.createIndicator("VOL");
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element);
    return () => {
      observer.disconnect();
      dispose(element);
    };
  }, [symbol, bars, token.colorBgContainer, locale]);
  return (
    <div
      ref={container}
      role="img"
      aria-label={`${symbol} ${t("finance.market.chartLabel", "日K线图")}`}
      style={{
        height: "min(60vh, 620px)",
        minHeight: 360,
        width: "100%",
        background: token.colorBgContainer,
      }}
    />
  );
}
