import React, { useState } from "react";
import { motion } from "motion/react";
import { riskQuestions } from "../data";
import { ShieldCheck, HelpCircle, ChevronRight, RotateCcw, Award } from "lucide-react";

interface RiskAssessmentProps {
  onComplete: (score: number) => void;
  currentScore: number | null;
  onReset: () => void;
}

export default function RiskAssessment({ onComplete, currentScore, onReset }: RiskAssessmentProps) {
  const [currentIdx, setCurrentIdx] = useState<number>(0);
  const [answers, setAnswers] = useState<Record<number, number>>({});

  const handleSelectOption = (questionId: number, score: number) => {
    const updatedAnswers = { ...answers, [questionId]: score };
    setAnswers(updatedAnswers);

    if (currentIdx < riskQuestions.length - 1) {
      // Small delayed transition
      setTimeout(() => {
        setCurrentIdx(prev => prev + 1);
      }, 250);
    } else {
      // Calculate final weighted risk score (1-7 range)
      const allScores = Object.values(updatedAnswers) as number[];
      const totalScore = allScores.reduce((sum: number, s: number) => sum + s, 0);
      const rawAvg = totalScore / riskQuestions.length;
      
      // Map average to standard 1 to 7 integer scale
      const roundedScore = Math.min(7, Math.max(1, Math.round(rawAvg)));
      onComplete(roundedScore);
    }
  };

  const handlePrev = () => {
    if (currentIdx > 0) {
      setCurrentIdx(currentIdx - 1);
    }
  };

  const currentQuestion = riskQuestions[currentIdx];
  const progressPercent = Math.round(((currentIdx + (currentScore ? 1 : 0)) / riskQuestions.length) * 100);

  // If completed, show beautifully styled summary panel
  if (currentScore !== null) {
    return (
      <div id="risk-result" className="bg-slate-900 border border-slate-800 rounded-2xl p-6 md:p-8 text-white relative overflow-hidden shadow-2xl">
        <div className="absolute top-0 right-0 w-64 h-64 bg-teal-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute -bottom-10 -left-10 w-64 h-64 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />

        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 relative z-10">
          <div className="flex items-start gap-4">
            <div className="h-12 w-12 rounded-xl bg-teal-500/20 flex items-center justify-center text-teal-400 shrink-0">
              <Award className="h-6 w-6" id="award-icon" />
            </div>
            <div>
              <p className="text-slate-400 text-xs font-mono tracking-wider">FIRST CAPITAL ASSESSMENT</p>
              <h3 className="text-xl font-sans font-semibold text-slate-100 tracking-tight mt-1">您的理财风险归属等级</h3>
              <p className="text-slate-400 text-sm mt-1 max-w-md">
                基于第一资本智能量化测评模型，深度模拟您的投资限期、资产依赖度与最大跌幅风险容忍值，评定结果如下：
              </p>
            </div>
          </div>
          <div className="flex flex-col items-center justify-center bg-slate-950/80 border border-slate-800 rounded-2xl px-8 py-6 text-center shrink-0 min-w-[180px]">
            <span className="text-slate-500 text-xs font-semibold uppercase tracking-wider">Risk Level</span>
            <span className="text-6xl font-extrabold text-teal-400 tracking-tighter my-2 font-mono">
              L{currentScore}
            </span>
            <span className="text-slate-300 text-sm font-semibold">
              {currentScore <= 2 ? "保守/防御型" : currentScore <= 5 ? "平衡/增值型" : "积极/自律成长型"}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-8 pt-6 border-t border-slate-800 relative z-10">
          <div className="bg-slate-950/30 border border-slate-800/50 rounded-xl p-4">
            <h4 className="text-sm font-semibold text-teal-400 flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-teal-400" />
              组合配置匹配
            </h4>
            <p className="text-xs text-slate-300 mt-2 leading-relaxed">
              系统将根据此级别推荐：美股全资产ETF组合 <b>Level {currentScore}</b>，或适配的中国A股 
              {currentScore <= 3 ? " 红利低波量化策略" : currentScore <= 5 ? " 中盘多因子策略" : " AI智能自适应Absolute Alpha策略"}。
            </p>
          </div>
          <div className="bg-slate-950/30 border border-slate-800/50 rounded-xl p-4">
            <h4 className="text-sm font-semibold text-sky-400 flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-sky-400" />
              动态再平衡条件
            </h4>
            <p className="text-xs text-slate-300 mt-2 leading-relaxed">
              您的投资组合将享受 First Capital 智能重置，若投资偏离度在特定周期中大于 {currentScore <= 3 ? "3%" : "5%"}, 算法策略将实施零手续费自动化再平衡。
            </p>
          </div>
          <div className="bg-slate-950/30 border border-slate-800/50 rounded-xl p-4">
            <h4 className="text-sm font-semibold text-indigo-400 flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-indigo-400" />
              建议理财周期
            </h4>
            <p className="text-xs text-slate-300 mt-2 leading-relaxed">
              为充分平摊风险周期并发挥量化因子的复利效应，本等级模型建议您持续持有至少 <b>{currentScore <= 2 ? "12个月" : currentScore <= 5 ? "24个月" : "36个月"}</b>。
            </p>
          </div>
        </div>

        <div className="mt-6 flex justify-end">
          <button
            onClick={() => {
              setAnswers({});
              setCurrentIdx(0);
              onReset();
            }}
            className="px-4 py-2 border border-slate-700 hover:border-teal-500 rounded-lg text-xs font-semibold tracking-wide flex items-center gap-1.5 transition-all duration-200 text-slate-300 hover:text-white"
            id="re-test-btn"
          >
            <RotateCcw className="h-3 w-3" />
            重新测试风险偏好
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-100 rounded-2xl p-6 md:p-8 shadow-sm">
      {/* Risk progress banner */}
      <div className="flex items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-2 text-slate-700">
          <ShieldCheck className="h-5 w-5 text-teal-600" />
          <h3 className="text-base font-semibold tracking-tight">First Capital 智能财富基因评测</h3>
        </div>
        <span className="text-xs text-slate-500 font-mono">
          第 {currentIdx + 1} / {riskQuestions.length} 题
        </span>
      </div>

      {/* Progress slider */}
      <div className="w-full bg-slate-100 h-1.5 rounded-full mb-8 overflow-hidden pointer-events-none">
        <div
          className="bg-indigo-600 h-full transition-all duration-300 rounded-full"
          style={{ width: `${progressPercent}%` }}
        />
      </div>

      {/* Question Content */}
      <div className="min-h-[120px]">
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-800 mb-3">
          <HelpCircle className="h-3.5 w-3.5" />
          理财偏好调查
        </span>
        <h4 className="text-lg font-medium text-slate-900 tracking-tight leading-snug">
          {currentQuestion.text}
        </h4>
      </div>

      {/* Answer Options */}
      <div className="grid grid-cols-1 gap-3 mt-6">
        {currentQuestion.options.map((opt, oIdx) => (
          <button
            key={oIdx}
            onClick={() => handleSelectOption(currentQuestion.id, opt.score)}
            className="w-full text-left p-4 rounded-xl border border-slate-200 hover:border-indigo-600 hover:bg-slate-50/50 transition-all duration-200 group flex items-start justify-between gap-4"
            id={`q-${currentQuestion.id}-opt-${oIdx}`}
          >
            <span className="text-sm text-slate-700 group-hover:text-slate-950 font-sans leading-relaxed">
              {opt.text}
            </span>
            <span className="h-5 w-5 rounded-full border border-slate-300 group-hover:border-indigo-600 flex items-center justify-center shrink-0 mt-0.5">
              <span className="h-2 w-2 rounded-full bg-transparent group-hover:bg-indigo-600 transition-colors" />
            </span>
          </button>
        ))}
      </div>

      {/* Back button */}
      <div className="flex justify-between items-center mt-8 pt-4 border-t border-slate-100">
        <p className="text-xs text-slate-400">
          * 根据第一资本 (上市代码：1269.HK) 集团合规与风险评级标准科学规范设计。
        </p>
        
        {currentIdx > 0 && (
          <button
            onClick={handlePrev}
            className="px-3.5 py-1.5 border border-slate-200 hover:bg-slate-50 rounded-lg text-xs font-medium text-slate-600 flex items-center gap-1 transition-all"
            id="back-step-btn"
          >
            返回上一题
          </button>
        )}
      </div>
    </div>
  );
}
