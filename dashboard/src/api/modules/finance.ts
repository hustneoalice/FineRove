import { request } from "../request";

export interface NeoCapability {
  id: string;
  name: string;
  connected: boolean;
  origin: string;
  verification_status: string;
}

export interface NeoCatalog {
  configured: boolean;
  expert_tool_available: boolean;
  items: NeoCapability[];
}

export interface NeoRequest {
  capability: "neo.trend_histogram";
  instrument_id: string;
  period: "day";
  adjust: "raw" | "qfq" | "hfq";
  end: string;
  limit: number;
}

export interface NeoResult {
  status: "ok" | "empty";
  capability: string;
  instrument_id: string;
  as_of: string | null;
  adjust: string;
  rule_version: string;
  verification_status: string;
  snapshot_id: string;
  points: { date: string; value: number | null }[];
  warnings: string[];
}

export const financeApi = {
  catalog: (signal?: AbortSignal) =>
    request<NeoCatalog>("/finance/neo/catalog", { signal }),
  evaluate: (body: NeoRequest, signal?: AbortSignal) =>
    request<NeoResult>("/finance/neo/evaluate", {
      method: "POST",
      body: JSON.stringify(body),
      signal,
    }),
};
