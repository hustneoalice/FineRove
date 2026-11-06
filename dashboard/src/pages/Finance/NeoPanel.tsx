import { useEffect, useRef, useState } from "react";
import { Alert, Button, Card, Input, Select, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";
import {
  financeApi,
  type NeoCatalog,
  type NeoRequest,
  type NeoResult,
} from "../../api/modules/finance";

function previousMarketDate() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const part = (name: string) =>
    parts.find((item) => item.type === name)!.value;
  const day = new Date(
    `${part("year")}-${part("month")}-${part("day")}T00:00:00Z`,
  );
  day.setUTCDate(day.getUTCDate() - 1);
  return day.toISOString().slice(0, 10);
}

export default function Finance() {
  const { t } = useTranslation();
  const serviceError = t("finance.failed", "服务暂不可用");
  const [catalog, setCatalog] = useState<NeoCatalog>();
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [instrument, setInstrument] = useState("CN:SZ:stock:300274");
  const [end, setEnd] = useState(previousMarketDate);
  const [adjust, setAdjust] = useState<NeoRequest["adjust"]>("qfq");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<NeoResult>();
  const pending = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const cancel = () => {
    generation.current += 1;
    pending.current?.abort();
    setBusy(false);
    setResult(undefined);
    setError("");
  };
  useEffect(() => {
    const controller = new AbortController();
    financeApi
      .catalog(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          setCatalog(value);
          setError("");
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setError(reason instanceof Error ? reason.message : serviceError);
      });
    return () => controller.abort();
  }, [reload, serviceError]);
  useEffect(
    () => () => {
      generation.current += 1;
      pending.current?.abort();
    },
    [],
  );
  const evaluate = async () => {
    cancel();
    const version = generation.current;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    try {
      const value = await financeApi.evaluate(
        {
          capability: "neo.trend_histogram",
          instrument_id: instrument,
          end,
          adjust,
          period: "day",
          limit: 100,
        },
        controller.signal,
      );
      if (version === generation.current) setResult(value);
    } catch (reason) {
      if (version === generation.current && !controller.signal.aborted)
        setError(reason instanceof Error ? reason.message : serviceError);
    } finally {
      if (version === generation.current) setBusy(false);
    }
  };
  const points = result?.points.slice(-120) ?? [];
  const scale = Math.max(
    1,
    ...points.map((point) => Math.abs(point.value ?? 0)),
  );
  return (
    <Space
      direction="vertical"
      size="large"
      style={{
        width: "100%",
        maxWidth: 1100,
        padding: 24,
        boxSizing: "border-box",
        margin: "0 auto",
      }}
    >
      <div>
        <Typography.Title level={2}>
          {t("finance.title", "NEO 核心指标")}
        </Typography.Title>
        <Typography.Paragraph type="secondary">
          {t(
            "finance.protection",
            "核心指标由私有服务计算，工作台只接收结果。",
          )}
        </Typography.Paragraph>
      </div>
      {catalog && !catalog.configured && (
        <Alert
          type="info"
          showIcon
          message={t("finance.disconnected", "尚未连接私有计算服务")}
        />
      )}
      {error && (
        <Alert
          type="error"
          showIcon
          message={error}
          action={
            !catalog ? (
              <Button onClick={() => setReload((value) => value + 1)}>
                {t("finance.retry", "重试")}
              </Button>
            ) : undefined
          }
        />
      )}
      <Space wrap>
        {catalog?.items.map((item) => (
          <Button
            key={item.id}
            type={item.id === "neo.trend_histogram" ? "primary" : "default"}
            disabled={!item.connected || item.id !== "neo.trend_histogram"}
          >
            {item.name}
          </Button>
        ))}
      </Space>
      <Card>
        <Space wrap align="end" size="middle">
          <div>
            <label htmlFor="neo-instrument">
              {t("finance.instrument", "证券标识")}
            </label>
            <Input
              id="neo-instrument"
              value={instrument}
              style={{ width: 260, display: "block" }}
              onChange={(event) => {
                cancel();
                setInstrument(event.target.value);
              }}
            />
          </div>
          <div>
            <label htmlFor="neo-end">{t("finance.end", "截至日期")}</label>
            <Input
              id="neo-end"
              type="date"
              value={end}
              style={{ display: "block" }}
              onChange={(event) => {
                cancel();
                setEnd(event.target.value);
              }}
            />
          </div>
          <div>
            <label htmlFor="neo-adjust">
              {t("finance.adjust", "复权方式")}
            </label>
            <Select
              id="neo-adjust"
              value={adjust}
              style={{ width: 120, display: "block" }}
              options={[
                { value: "qfq", label: t("finance.qfq", "前复权") },
                { value: "raw", label: t("finance.raw", "不复权") },
                { value: "hfq", label: t("finance.hfq", "后复权") },
              ]}
              onChange={(value) => {
                cancel();
                setAdjust(value);
              }}
            />
          </div>
          <Button
            type="primary"
            loading={busy}
            disabled={
              !catalog?.configured ||
              !catalog.items.some(
                (item) => item.id === "neo.trend_histogram" && item.connected,
              ) ||
              !instrument ||
              !end
            }
            onClick={() => void evaluate()}
          >
            {t("finance.fetch", "获取指标")}
          </Button>
        </Space>
      </Card>
      {result && (
        <Card title={result.instrument_id}>
          <Space wrap>
            <span>{result.as_of}</span>
            <span>{result.adjust}</span>
            <span>{result.rule_version}</span>
          </Space>
          {points.some((point) => point.value !== null) ? (
            <svg
              role="img"
              aria-label={t("finance.chart", "趋势柱线结果")}
              viewBox="0 0 720 220"
              style={{ width: "100%", maxHeight: 300 }}
            >
              <line
                x1="0"
                x2="720"
                y1="110"
                y2="110"
                stroke="currentColor"
                opacity="0.2"
              />
              {points.map((point, index) =>
                point.value === null ? null : (
                  <rect
                    key={point.date}
                    x={(index * 720) / points.length + 1}
                    y={
                      point.value >= 0 ? 110 - (point.value / scale) * 95 : 110
                    }
                    width={Math.max(1, 720 / points.length - 2)}
                    height={Math.max(1, (Math.abs(point.value) / scale) * 95)}
                    fill={point.value >= 0 ? "#cf1322" : "#237804"}
                  >
                    <title>
                      {point.date}: {point.value}
                    </title>
                  </rect>
                ),
              )}
            </svg>
          ) : (
            <Typography.Paragraph>
              {t("finance.empty", "当前范围没有可展示的数据。")}
            </Typography.Paragraph>
          )}
          <Typography.Paragraph type="secondary">
            {t(
              "finance.verification",
              "迁移公式尚未完成逐点一致性验证；请结合原始行情核对。",
            )}
          </Typography.Paragraph>
          {result.warnings.map((warning) => (
            <Typography.Paragraph key={warning}>{warning}</Typography.Paragraph>
          ))}
          <Typography.Text type="secondary">
            {t("finance.snapshot", "数据快照")}: {result.snapshot_id}
          </Typography.Text>
        </Card>
      )}
    </Space>
  );
}
