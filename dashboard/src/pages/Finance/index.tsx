import { lazy, Suspense } from "react";
import { Spin, Tabs } from "antd";
import { useTranslation } from "react-i18next";
const Market = lazy(() => import("./NativeWorkbench"));
const NeoPanel = lazy(() => import("./NeoPanel"));

export default function Finance() {
  const { t } = useTranslation();
  return (
    <div style={{ padding: 20, width: "100%", boxSizing: "border-box" }}>
      <Tabs
        defaultActiveKey="market"
        destroyOnHidden
        items={[
          {
            key: "market",
            label: t("finance.market.tab", "看盘与自选"),
            children: (
              <Suspense fallback={<Spin />}>
                <Market />
              </Suspense>
            ),
          },
          {
            key: "neo",
            label: t("finance.market.neoTab", "NEO 自研指标"),
            children: (
              <Suspense fallback={<Spin />}>
                <NeoPanel />
              </Suspense>
            ),
          },
        ]}
      />
    </div>
  );
}
