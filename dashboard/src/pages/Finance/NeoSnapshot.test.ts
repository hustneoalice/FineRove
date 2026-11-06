import { describe, expect, it } from "vitest";
import {
  makeTrendRequest,
  alignTrendPoints,
} from "../../../financial-workbench/src/neo";

const bars = [
  { date: "2020-01-01", open: 10, high: 12, low: 9, close: 11 },
  { date: "2020-01-02", open: 11, high: 13, low: 10, close: 12 },
  { date: "2020-01-03", open: 12, high: 14, low: 11, close: 13 },
];
describe("native NEO input snapshot", () => {
  it("sends the displayed prices and full available warmup, excluding unclosed dates", () => {
    const request = makeTrendRequest(
      "600519.SH",
      bars,
      new Date("2020-01-03T03:00:00Z"),
    );
    expect(request.instrument_id).toBe("CN:SH:stock:600519");
    expect(request.end).toBe("2020-01-02");
    expect(request.adjust).toBe("qfq");
    expect(request.bars.map((b) => [b.date, b.close])).toEqual([
      ["2020-01-01", 11],
      ["2020-01-02", 12],
    ]);
  });
  it("does not request stock indicators on indices or unsupported exchanges", () => {
    for (const symbol of ["000001.SH", "510300.SH", "430047.BJ"])
      expect(() => makeTrendRequest(symbol, bars)).toThrow();
  });
  it("aligns by date and leaves missing/current bars empty, including real zero values", () => {
    expect(
      alignTrendPoints(bars, [
        { date: "2020-01-02", value: 0 },
        { date: "2020-01-01", value: -1 },
      ]),
    ).toEqual([{ value: -1 }, { value: 0 }, { value: null }]);
  });
});
