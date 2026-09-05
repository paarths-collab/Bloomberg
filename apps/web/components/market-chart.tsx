"use client";

import { AreaSeries, ColorType, createChart, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";

const sample = [6420,6412,6434,6440,6431,6452,6464,6459,6474,6468,6482,6491,6484,6500,6494,6512,6505,6518,6526,6519,6531,6544,6538,6551,6547,6562,6558,6574,6567,6582];

export function MarketChart() {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      autoSize: true,
      height: 300,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#6f7585",
        fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.035)" },
        horzLines: { color: "rgba(255,255,255,0.035)" },
      },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.07)" },
      timeScale: { borderColor: "rgba(255,255,255,0.07)", timeVisible: true, secondsVisible: false },
      crosshair: {
        vertLine: { color: "rgba(124, 140, 255, 0.35)" },
        horzLine: { color: "rgba(124, 140, 255, 0.25)" },
      },
    });

    const series = chart.addSeries(AreaSeries, {
      lineColor: "#9aa7ff",
      topColor: "rgba(115, 132, 255, 0.30)",
      bottomColor: "rgba(115, 132, 255, 0.01)",
      lineWidth: 2,
      priceLineVisible: false,
    });

    const now = Math.floor(Date.now() / 1000);
    series.setData(sample.map((value, index) => ({
      time: (now - (sample.length - index) * 60 * 30) as UTCTimestamp,
      value,
    })));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, []);

  return <div className="chart" ref={containerRef} aria-label="Intraday market chart" />;
}
