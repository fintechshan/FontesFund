import React, { useState, useRef, useEffect } from "react";
import { PortfolioData } from "../types";
import { TrendingUp, Award, Activity } from "lucide-react";

interface PerformanceChartProps {
  portfolio: PortfolioData;
}

export default function PerformanceChart({ portfolio }: PerformanceChartProps) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(500);
  const height = 240;
  const paddingLeft = 40;
  const paddingRight = 20;
  const paddingTop = 30;
  const paddingBottom = 40;

  // Responsive width tracking
  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (let entry of entries) {
        setWidth(Math.max(280, entry.contentRect.width));
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const data = portfolio.perfHistory;

  // Find min/max values for scaling
  // Start with a cumulative base of 100 on Year 0 (or just scale from simple percents)
  // Let's draw cumulative returns starting at 100% in 2020 to show long-term growth
  const initialValue = 100.0;
  let cumPortfolio = [initialValue];
  let cumBenchmark = [initialValue];

  for (let i = 0; i < data.length; i++) {
    const prevPort = cumPortfolio[cumPortfolio.length - 1];
    const prevBench = cumBenchmark[cumBenchmark.length - 1];
    cumPortfolio.push(prevPort * (1 + data[i].portfolio / 100));
    cumBenchmark.push(prevBench * (1 + data[i].benchmark / 100));
  }

  // Create timeline points including starting node 100
  const timeLabels = ["2020(起点)", ...data.map(d => d.year.toString())];
  
  const minVal = Math.min(...cumPortfolio, ...cumBenchmark) * 0.95;
  const maxVal = Math.max(...cumPortfolio, ...cumBenchmark) * 1.05;
  const valueRange = maxVal - minVal;

  // Translate coordinates
  const getX = (index: number) => {
    const step = (width - paddingLeft - paddingRight) / (timeLabels.length - 1);
    return paddingLeft + index * step;
  };

  const getY = (val: number) => {
    return height - paddingBottom - ((val - minVal) / valueRange) * (height - paddingTop - paddingBottom);
  };

  // Generate SVG path strings
  let portfolioPath = "";
  let benchmarkPath = "";
  
  for (let i = 0; i < timeLabels.length; i++) {
    const x = getX(i);
    const yPort = getY(cumPortfolio[i]);
    const yBench = getY(cumBenchmark[i]);
    
    if (i === 0) {
      portfolioPath = `M ${x} ${yPort}`;
      benchmarkPath = `M ${x} ${yBench}`;
    } else {
      // Curve smoothing attempt using cubic bezier or straight lines for accurate financial representation
      portfolioPath += ` L ${x} ${yPort}`;
      benchmarkPath += ` L ${x} ${yBench}`;
    }
  }

  // Hover detection
  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const svgRect = e.currentTarget.getBoundingClientRect();
    const clientX = e.clientX - svgRect.left;
    const step = (width - paddingLeft - paddingRight) / (timeLabels.length - 1);
    
    // Find closest index
    const relativeX = clientX - paddingLeft;
    let index = Math.round(relativeX / step);
    index = Math.max(0, Math.min(timeLabels.length - 1, index));
    setHoveredIdx(index);
  };

  const handleMouseLeave = () => {
    setHoveredIdx(null);
  };

  // Calculate CAGR
  const yearsCount = data.length;
  const portfolioCagr = ((Math.pow(cumPortfolio[cumPortfolio.length - 1] / 100, 1 / yearsCount) - 1) * 100).toFixed(2);
  const benchmarkCagr = ((Math.pow(cumBenchmark[cumBenchmark.length - 1] / 100, 1 / yearsCount) - 1) * 100).toFixed(2);
  const outperformance = (parseFloat(portfolioCagr) - parseFloat(benchmarkCagr)).toFixed(2);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 text-white" ref={containerRef}>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div>
          <div className="flex items-center gap-2">
            <span className="p-1 rounded-md bg-teal-500/20 text-teal-400">
              <Activity className="h-4 w-4" />
            </span>
            <h3 className="text-base font-semibold text-slate-100 font-sans tracking-tight">历史复合业绩模拟表现</h3>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            假设从2020年起投 100 分，持续持有First Capital投资组合 vs 基准指数的表现对垒。
          </p>
        </div>

        <div className="flex gap-4">
          <div className="bg-slate-950 px-3 py-1.5 rounded-lg border border-slate-800 text-center">
            <div className="text-[10px] text-slate-400 font-mono">平台复合年化 (CAGR)</div>
            <div className="text-sm font-bold text-teal-400 font-mono">+{portfolioCagr}%</div>
          </div>
          <div className="bg-slate-950 px-3 py-1.5 rounded-lg border border-slate-800 text-center">
            <div className="text-[10px] text-slate-400 font-mono">市场指数年化</div>
            <div className="text-sm font-bold text-slate-300 font-mono">+{benchmarkCagr}%</div>
          </div>
        </div>
      </div>

      {/* SVG Canvas */}
      <div className="relative h-[250px] w-full">
        <svg
          width={width}
          height={height}
          className="overflow-visible select-none cursor-crosshair"
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
          id="performance-svg-chart"
        >
          {/* Y Axis Grid lines */}
          {[0, 0.25, 0.5, 0.75, 1].map((ratio, idx) => {
            const val = minVal + ratio * valueRange;
            const y = getY(val);
            return (
              <g key={idx}>
                <line
                  x1={paddingLeft}
                  y1={y}
                  x2={width - paddingRight}
                  y2={y}
                  stroke="#1e293b"
                  strokeDasharray="4,4"
                  strokeWidth="1"
                />
                <text
                  x={paddingLeft - 8}
                  y={y + 4}
                  fill="#64748b"
                  fontSize="10"
                  textAnchor="end"
                  fontFamily="monospace"
                >
                  {val.toFixed(0)}分
                </text>
              </g>
            );
          })}

          {/* X Axis labels */}
          {timeLabels.map((lbl, idx) => {
            const x = getX(idx);
            return (
              <text
                key={idx}
                x={x}
                y={height - 12}
                fill="#64748b"
                fontSize="10"
                textAnchor="middle"
                fontFamily="sans-serif"
              >
                {lbl}
              </text>
            );
          })}

          {/* Benchmark Line (Gray/Transparent) */}
          <path
            d={benchmarkPath}
            fill="none"
            stroke="#475569"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Portfolio Line (Teal Glowing) */}
          <path
            d={portfolioPath}
            fill="none"
            stroke="#14b8a6"
            strokeWidth="3.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="filter drop-shadow-[0_2px_8px_rgba(20,184,166,0.5)]"
          />

          {/* Circles at data nodes */}
          {timeLabels.map((_, idx) => {
            const x = getX(idx);
            const yPort = getY(cumPortfolio[idx]);
            const yBench = getY(cumBenchmark[idx]);
            const isHovered = hoveredIdx === idx;

            return (
              <g key={idx}>
                {/* Portfolio dots */}
                <circle
                  cx={x}
                  cy={yPort}
                  r={isHovered ? 6 : 3}
                  fill="#14b8a6"
                  stroke="#0f172a"
                  strokeWidth={isHovered ? 2 : 1}
                />
                {/* Benchmark dots */}
                <circle
                  cx={x}
                  cy={yBench}
                  r={isHovered ? 5 : 2}
                  fill="#64748b"
                  stroke="#0f172a"
                  strokeWidth={isHovered ? 1.5 : 1}
                />
              </g>
            );
          })}

          {/* Interactive Guideline and Tooltip */}
          {hoveredIdx !== null && (
            <g>
              {/* Vertical line tracer */}
              <line
                x1={getX(hoveredIdx)}
                y1={paddingTop}
                x2={getX(hoveredIdx)}
                y2={height - paddingBottom}
                stroke="#0ea5e9"
                strokeWidth="1.5"
                strokeDasharray="2,2"
              />

              {/* Floating values readout */}
              <g>
                <rect
                  x={getX(hoveredIdx) + (hoveredIdx > timeLabels.length / 2 ? -155 : 15)}
                  y={40}
                  width="140"
                  height="74"
                  rx="8"
                  fill="#020617"
                  stroke="#334155"
                  strokeWidth="1"
                />
                <text
                  x={getX(hoveredIdx) + (hoveredIdx > timeLabels.length / 2 ? -85 : 85)}
                  y={57}
                  fill="#f1f5f9"
                  fontSize="11"
                  fontWeight="bold"
                  textAnchor="middle"
                >
                  {timeLabels[hoveredIdx]} 净值表现
                </text>
                <text
                  x={getX(hoveredIdx) + (hoveredIdx > timeLabels.length / 2 ? -143 : 27)}
                  y={79}
                  fill="#14b8a6"
                  fontSize="10.5"
                  fontFamily="monospace"
                  textAnchor="start"
                >
                  首府组合: {cumPortfolio[hoveredIdx].toFixed(1)} 分
                </text>
                <text
                  x={getX(hoveredIdx) + (hoveredIdx > timeLabels.length / 2 ? -143 : 27)}
                  y={98}
                  fill="#94a3b8"
                  fontSize="10.5"
                  fontFamily="monospace"
                  textAnchor="start"
                >
                  市场大盘: {cumBenchmark[hoveredIdx].toFixed(1)} 分
                </text>
              </g>
            </g>
          )}
        </svg>
      </div>

      {/* Underlying info */}
      <div className="mt-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 pt-4 border-t border-slate-800/80">
        <div className="flex flex-wrap items-center gap-4 text-xs">
          <div className="flex items-center gap-1.5">
            <span className="inline-block h-3 w-3 rounded-full bg-teal-500" />
            <span className="text-slate-300">第一资本量化/智能投顾产品</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-full bg-slate-600" />
            <span className="text-slate-400">沪深300 / 股债混合基准比例</span>
          </div>
        </div>

        <div className="text-xs text-teal-400 flex items-center gap-1 font-sans">
          <TrendingUp className="h-4 w-4" />
          <span>相比传统大盘，超额年化收益高达 {outperformance}%</span>
        </div>
      </div>
    </div>
  );
}
