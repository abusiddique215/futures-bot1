import { useEffect, useRef } from "react";
import {
  createChart,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import type { EquityCurvePoint } from "@/lib/api";

interface Props {
  series: EquityCurvePoint[];
  height?: number;
  className?: string;
}

/**
 * Equity curve plot — TradingView Lightweight Charts v5.
 *
 * Renders a single line series from the bot's `equity_curve` payload.
 * Re-keys on every prop update (cheap; the JSON payload is bounded by
 * the journal's equity_snapshots row count and is typically <500 points
 * for a session).
 */
export function EquityCurve({ series, height = 240, className }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  // Construct chart once on mount.
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { color: "#11151c" },
        textColor: "#7d8590",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "#1f2733" },
        horzLines: { color: "#1f2733" },
      },
      rightPriceScale: { borderColor: "#1f2733" },
      timeScale: { borderColor: "#1f2733", timeVisible: true, secondsVisible: false },
    });
    const lineSeries = chart.addSeries(LineSeries, {
      color: "#3fb950",
      lineWidth: 2,
    });
    chartRef.current = chart;
    seriesRef.current = lineSeries;
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Push series data on every change.
  useEffect(() => {
    if (!seriesRef.current) return;
    const points = series
      .map((p) => ({
        time: (Math.floor(new Date(p.timestamp).getTime() / 1000)) as Time,
        value: p.equity,
      }))
      // Lightweight-charts requires strictly-ascending unique times.
      .filter((p, i, arr) => i === 0 || p.time !== arr[i - 1].time)
      .sort((a, b) => (a.time as number) - (b.time as number));
    seriesRef.current.setData(points);
    chartRef.current?.timeScale().fitContent();
  }, [series]);

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ height: `${height}px`, width: "100%" }}
    />
  );
}
