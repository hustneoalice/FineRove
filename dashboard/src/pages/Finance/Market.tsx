import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  List,
  Select,
  Space,
  Spin,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import {
  marketApi,
  type Adjustment,
  type MarketBar,
  type MarketSecurity,
  type WatchlistDocument,
} from "../../api/modules/market";
import MarketChart from "./MarketChart";
import "./Market.css";
import { apiErrorMessage } from "../../utils/apiError";

const message = (error: unknown) => apiErrorMessage(error, String(error));

export default function Market() {
  const { t } = useTranslation();
  const [security, setSecurity] = useState<MarketSecurity>({
    symbol: "000001.SH",
    name: t("finance.market.shanghai", "上证指数"),
  });
  const [adjust, setAdjust] = useState<Adjustment>("qfq");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<MarketSecurity[]>([]);
  const [searching, setSearching] = useState(false);
  const [bars, setBars] = useState<MarketBar[]>([]);
  const [loading, setLoading] = useState(false);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [marketError, setMarketError] = useState("");
  const [searchError, setSearchError] = useState("");
  const [watchError, setWatchError] = useState("");
  const [watchlist, setWatchlist] = useState<WatchlistDocument | null>(null);
  const [group, setGroup] = useState("");
  const [saving, setSaving] = useState(false);
  const [retry, setRetry] = useState(0);
  const mutation = useRef<AbortController | null>(null);
  const searchRequest = useRef<AbortController | null>(null);
  const chartRequest = useRef<AbortController | null>(null);

  useEffect(() => () => mutation.current?.abort(), []);

  useEffect(() => {
    const controller = new AbortController();
    marketApi
      .status(controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setConfigured(result.configured);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setMarketError(message(error));
      });
    marketApi
      .watchlist(controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setWatchlist(result);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setWatchError(message(error));
      });
    return () => {
      controller.abort();
    };
  }, [retry]);

  useEffect(() => {
    const controller = new AbortController();
    searchRequest.current = controller;
    setResults([]);
    setSearchError("");
    setSearching(false);
    if (!query.trim()) return () => controller.abort();
    const timer = window.setTimeout(() => {
      setSearching(true);
      marketApi
        .search(query.trim(), controller.signal)
        .then((result) => {
          if (!controller.signal.aborted) setResults(result.items);
        })
        .catch((error) => {
          if (!controller.signal.aborted) setSearchError(message(error));
        })
        .finally(() => {
          if (!controller.signal.aborted) setSearching(false);
        });
    }, 300);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  useEffect(() => {
    const controller = new AbortController();
    chartRequest.current = controller;
    setBars([]);
    setMarketError("");
    if (configured !== true) return () => controller.abort();
    setLoading(true);
    marketApi
      .kline(security.symbol, adjust, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) {
          setBars(result.bars);
          if (result.name)
            setSecurity((previous) => ({ ...previous, name: result.name! }));
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) setMarketError(message(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [security.symbol, adjust, configured, retry]);

  const choose = (item: MarketSecurity) => {
    if (item.symbol !== security.symbol) {
      chartRequest.current?.abort();
      setBars([]);
      setSecurity(item);
    }
    searchRequest.current?.abort();
    setQuery("");
    setResults([]);
  };
  const save = async (next: WatchlistDocument) => {
    if (saving) return;
    const controller = new AbortController();
    mutation.current = controller;
    setSaving(true);
    setWatchError("");
    try {
      const result = await marketApi.saveWatchlist(next, controller.signal);
      if (!controller.signal.aborted) setWatchlist(result);
    } catch (error) {
      if (controller.signal.aborted) return;
      if (
        /Request failed: 409\b/.test(
          error instanceof Error ? error.message : String(error),
        )
      ) {
        // A conflicting revision must never be automatically resubmitted.
        setWatchlist(null);
        setWatchError(
          t(
            "finance.market.conflict",
            "自选股已在其他页面修改，已重新加载，请重试。",
          ),
        );
        try {
          const latest = await marketApi.watchlist(controller.signal);
          if (!controller.signal.aborted) setWatchlist(latest);
        } catch (reloadError) {
          if (!controller.signal.aborted) setWatchError(message(reloadError));
        }
      } else setWatchError(message(error));
    } finally {
      if (!controller.signal.aborted) setSaving(false);
    }
  };
  const selected = watchlist?.items.some(
    (item) => item.symbol === security.symbol,
  );
  const toggle = () => {
    if (!watchlist) return;
    const target =
      group || watchlist.groups[0] || t("finance.market.defaultGroup", "默认");
    void save({
      ...watchlist,
      groups: watchlist.groups.length ? watchlist.groups : [target],
      items: selected
        ? watchlist.items.filter((item) => item.symbol !== security.symbol)
        : [
            ...watchlist.items,
            {
              symbol: security.symbol,
              name: security.name ?? "",
              groups: [target],
            },
          ],
    });
  };
  const latest = bars.at(-1);
  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      {configured === false && (
        <Alert
          type="warning"
          showIcon
          message={t(
            "finance.market.unconfigured",
            "行情服务尚未配置，请连接行情数据服务。",
          )}
        />
      )}
      {marketError && (
        <Alert
          type="error"
          showIcon
          message={marketError}
          action={
            <Button
              disabled={saving}
              onClick={() => setRetry((value) => value + 1)}
            >
              {t("finance.market.retry", "重试")}
            </Button>
          }
        />
      )}
      <div className="finance-market-grid">
        <Card title={t("finance.market.watchlist", "自选股")}>
          <Space direction="vertical" style={{ width: "100%" }}>
            <label htmlFor="market-search">
              {t("finance.market.search", "搜索证券")}
            </label>
            <Input
              id="market-search"
              aria-label={t("finance.market.search", "搜索证券")}
              value={query}
              maxLength={20}
              allowClear
              onChange={(event) => {
                searchRequest.current?.abort();
                setResults([]);
                setQuery(event.target.value.slice(0, 20));
              }}
              placeholder={t("finance.market.searchHint", "输入代码或名称")}
              suffix={searching ? <Spin size="small" /> : undefined}
            />
            {searchError && <Alert type="error" message={searchError} />}
            {query.trim() &&
              !searching &&
              results.length === 0 &&
              !searchError && (
                <Typography.Text type="secondary">
                  {t("finance.market.noResults", "暂无搜索结果")}
                </Typography.Text>
              )}
            {!!results.length && (
              <List
                size="small"
                dataSource={results}
                renderItem={(item) => (
                  <List.Item>
                    <Button
                      type="link"
                      onClick={() => choose(item)}
                      style={{
                        height: "auto",
                        whiteSpace: "normal",
                        textAlign: "left",
                      }}
                    >
                      {item.name} {item.symbol}
                    </Button>
                  </List.Item>
                )}
              />
            )}
            <Select
              aria-label={t("finance.market.group", "自选分组")}
              value={group}
              style={{ width: "100%" }}
              options={[
                { value: "", label: t("finance.market.allGroups", "全部分组") },
                ...(watchlist?.groups ?? []).map((value) => ({
                  value,
                  label: value,
                })),
              ]}
              onChange={setGroup}
            />
            {watchError && (
              <Alert type="warning" showIcon message={watchError} />
            )}
            <List
              size="small"
              loading={!watchlist && !watchError}
              locale={{
                emptyText: (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={t(
                      "finance.market.emptyWatchlist",
                      "自选股为空，搜索证券后加入自选。",
                    )}
                  />
                ),
              }}
              dataSource={(watchlist?.items ?? []).filter(
                (item) => !group || item.groups.includes(group),
              )}
              renderItem={(item) => (
                <List.Item
                  actions={[
                    <Button
                      key="remove"
                      type="text"
                      danger
                      disabled={saving}
                      aria-label={`${t("finance.market.remove", "移除")} ${
                        item.name || item.symbol
                      }`}
                      onClick={() =>
                        watchlist &&
                        void save({
                          ...watchlist,
                          items: watchlist.items.filter(
                            (row) => row.symbol !== item.symbol,
                          ),
                        })
                      }
                    >
                      {t("finance.market.remove", "移除")}
                    </Button>,
                  ]}
                >
                  <Button
                    type="link"
                    onClick={() => choose(item)}
                    style={{
                      height: "auto",
                      whiteSpace: "normal",
                      textAlign: "left",
                    }}
                  >
                    {item.name} {item.symbol}
                  </Button>
                </List.Item>
              )}
            />
          </Space>
        </Card>
        <Card
          title={`${security.name} ${security.symbol}`}
          style={{ minWidth: 0 }}
        >
          <Space wrap style={{ marginBottom: 16 }}>
            <Typography.Text>
              {t("finance.market.daily", "日线")}
            </Typography.Text>
            <Select
              aria-label={t("finance.market.adjust", "复权方式")}
              value={adjust}
              onChange={(value) => {
                chartRequest.current?.abort();
                setBars([]);
                setAdjust(value);
              }}
              options={[
                { value: "qfq", label: t("finance.market.qfq", "前复权") },
                { value: "hfq", label: t("finance.market.hfq", "后复权") },
                { value: "raw", label: t("finance.market.raw", "不复权") },
              ]}
            />
            <Button
              disabled={!watchlist || saving}
              loading={saving}
              onClick={toggle}
            >
              {selected
                ? t("finance.market.removeWatchlist", "移出自选")
                : t("finance.market.addWatchlist", "加入自选")}
            </Button>
            <Button
              disabled={configured !== true || loading || saving}
              onClick={() => {
                chartRequest.current?.abort();
                setBars([]);
                setRetry((value) => value + 1);
              }}
            >
              {t("finance.market.refresh", "刷新")}
            </Button>
          </Space>
          {latest && (
            <Typography.Paragraph>
              {latest.date} · {t("finance.market.close", "收盘")}{" "}
              {latest.close.toFixed(2)} · {t("finance.market.open", "开盘")}{" "}
              {latest.open.toFixed(2)} · {t("finance.market.high", "最高")}{" "}
              {latest.high.toFixed(2)} · {t("finance.market.low", "最低")}{" "}
              {latest.low.toFixed(2)}
              {latest.live ? ` · ${t("finance.market.live", "未收盘")}` : ""}
            </Typography.Paragraph>
          )}
          <Typography.Paragraph type="secondary">
            {t(
              "finance.market.chartHint",
              "MA 均线 · VOL 成交量；阳线空心红，阴线实心绿。",
            )}
          </Typography.Paragraph>
          <Spin spinning={loading}>
            <MarketChart symbol={security.symbol} bars={bars} />
          </Spin>
          {!loading && !bars.length && (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("finance.market.noBars", "暂无可用行情数据")}
            />
          )}
        </Card>
      </div>
    </Space>
  );
}
