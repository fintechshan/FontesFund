import React from "react";
import { PortfolioData } from "../types";
import { PieChart, List, DollarSign, Wallet, ShieldAlert, ArrowUpRight } from "lucide-react";
import { motion } from "motion/react";

interface PortfolioBreakdownProps {
  portfolio: PortfolioData;
}

export default function PortfolioBreakdown({ portfolio }: PortfolioBreakdownProps) {
  // SVG Donut Calculations
  const radius = 60;
  const strokeWidth = 14;
  const circumference = 2 * Math.PI * radius;
  
  let accumulatedPercent = 0;

  return (
    <div className="bg-white border border-slate-100 rounded-2xl p-6 shadow-sm">
      <div className="flex items-center justify-between gap-4 pb-4 border-b border-slate-100 mb-6">
        <div>
          <h3 className="text-base font-semibold text-slate-900 tracking-tight flex items-center gap-2">
            <PieChart className="h-4.5 w-4.5 text-indigo-600" />
            底层投顾资产配置配比
          </h3>
          <p className="text-xs text-slate-500 mt-1">
            采用前沿马科维茨均值方差模型及动态因子配对，对底层权益、固定收益及另类对冲资产实现深度精筛。
          </p>
        </div>
        <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-indigo-50 text-indigo-700 font-mono tracking-wider shrink-0 uppercase">
          ROBO MODEL
        </span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
        {/* Left Side: SVG Donut visualization */}
        <div className="lg:col-span-5 flex flex-col items-center justify-center bg-slate-50/50 rounded-2xl py-6 border border-slate-100">
          <div className="relative h-44 w-44 flex items-center justify-center">
            <svg width="160" height="160" viewBox="0 0 160 160" className="transform -rotate-90 select-none">
              <circle
                cx="80"
                cy="80"
                r={radius}
                fill="transparent"
                stroke="#f1f5f9"
                strokeWidth={strokeWidth}
              />
              {portfolio.assets.map((asset, idx) => {
                const strokeDashOffset = circumference - (asset.weight / 100) * circumference;
                const rotation = (accumulatedPercent / 100) * 360;
                accumulatedPercent += asset.weight;

                return (
                  <circle
                    key={idx}
                    cx="80"
                    cy="80"
                    r={radius}
                    fill="transparent"
                    stroke={asset.color}
                    strokeWidth={strokeWidth}
                    strokeDasharray={circumference}
                    strokeDashoffset={strokeDashOffset}
                    transform={`rotate(${rotation} 80 80)`}
                    strokeLinecap="round"
                    className="transition-all duration-500"
                  />
                );
              })}
            </svg>

            {/* Inner text readout */}
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
              <span className="text-xs text-slate-400 font-mono">期望年化 yield</span>
              <span className="text-2xl font-bold text-slate-800 tracking-tight my-0.5">
                {portfolio.expectedReturn.toFixed(1)}%
              </span>
              <span className="text-[10px] text-teal-600 font-medium bg-teal-50 px-1.5 py-0.5 rounded-full font-mono">
                Sharpe {portfolio.sharpeRatio.toFixed(2)}
              </span>
            </div>
          </div>

          <div className="flex gap-6 mt-4 text-xs font-mono">
            <div className="text-center">
              <span className="text-slate-400 block text-[10px] uppercase">预计年化波动</span>
              <span className="text-slate-700 font-semibold">{portfolio.expectedVolatility.toFixed(1)}%</span>
            </div>
            <div className="h-6 w-px bg-slate-200" />
            <div className="text-center">
              <span className="text-slate-400 block text-[10px] uppercase">标底产品代码</span>
              <span className="text-slate-700 font-semibold">{portfolio.assets[0]?.ticker ? "ETF 穿透" : "中国A股量化"}</span>
            </div>
          </div>
        </div>

        {/* Right Side: Detailed Itemized List */}
        <div className="lg:col-span-7 space-y-4">
          <div className="flex items-center justify-between text-xs font-semibold text-slate-400 uppercase tracking-wider px-2">
            <span className="flex items-center gap-1.5">
              <List className="h-3.5 w-3.5" />
              明细持仓与交易代码
            </span>
            <span>目标配置占比 Weight</span>
          </div>

          <div className="space-y-2.5">
            {portfolio.assets.map((asset, idx) => (
              <div
                key={idx}
                className="p-3 bg-white border border-slate-100 hover:border-slate-200 rounded-xl transition-all shadow-xs flex items-center justify-between gap-4"
              >
                <div className="flex items-center gap-3 min-w-0">
                  {/* Category Color Dot */}
                  <span
                    className="h-3 w-3 rounded-md shrink-0 block"
                    style={{ backgroundColor: asset.color }}
                  />
                  
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-sm font-semibold text-slate-800 truncate">
                        {asset.name}
                      </span>
                      {asset.ticker && (
                        <span className="text-[10px] font-bold bg-slate-100 text-slate-600 px-1 rounded uppercase font-mono">
                          {asset.ticker}
                        </span>
                      )}
                    </div>
                    <span className="text-[10px] text-slate-400 font-medium">
                      板块分布: {asset.category}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <div className="text-right">
                    <span className="text-base font-bold text-slate-900 font-mono block">
                      {asset.weight}%
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-6 p-4 rounded-xl bg-indigo-50/50 border border-indigo-100/40 flex items-start gap-3">
        <ShieldAlert className="h-5 w-5 text-indigo-600 shrink-0 mt-0.5" />
        <div>
          <h4 className="text-xs font-bold text-indigo-950">
            第一资本极速全天候智能重置与零滑点平稳调仓模型 (First Capital Group Rebalancing Model)
          </h4>
          <p className="text-[11px] text-indigo-900/80 mt-1 leading-relaxed">
            我们每日计算偏离度漂移。当市场大起大落引发各因子或大宗权重偏离预设比例超过 <b>4%</b> 时，平台清算算法将自动在后台极速配对交易，一键调仓。投顾账户全程享受免印花红利，确保您的配置始终处于科学均值有效前沿。
          </p>
        </div>
      </div>
    </div>
  );
}
