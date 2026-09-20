import React, { useState, useEffect, useRef } from "react";
import { usEtfPortfolios, aSharePortfolios, feeStructure, aShareFeeRate } from "./data";
import { PortfolioData, ChatMessage } from "./types";
import RiskAssessment from "./components/RiskAssessment";
import PortfolioBreakdown from "./components/PortfolioBreakdown";
import PerformanceChart from "./components/PerformanceChart";
import { 
  Shield, 
  TrendingUp, 
  Compass, 
  HelpCircle, 
  MessageSquare, 
  Sparkles, 
  ArrowRight, 
  Info, 
  DollarSign, 
  Sliders, 
  ChevronRight, 
  Send, 
  Zap, 
  Lock, 
  UserCheck, 
  RotateCcw,
  CheckCircle2,
  BookOpen
} from "lucide-react";

export default function App() {
  // Navigation tabs (strictly for content organization on a single screen)
  const [activeTab, setActiveTab] = useState<"investment" | "quant" | "etf" | "about">("investment");

  // Core configuration states
  const [targetType, setTargetType] = useState<"A_SHARE" | "US_ETF">("US_ETF");
  const [riskLevel, setRiskLevel] = useState<number>(4); // default Level 4
  const [investmentAmount, setInvestmentAmount] = useState<number>(50); // in ten thousand RMB (e.g. 500k yuan / ~70k usd)
  const [showRiskModal, setShowRiskModal] = useState<boolean>(false);
  const [assessedRiskScore, setAssessedRiskScore] = useState<number | null>(null);

  // Chatbot state
  const [chatInput, setChatInput] = useState<string>("");
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      text: "您好！我是第一资本AI财富顾问。我精通中国A股因子量化多因子策略以及美股全球多资产ETF配置模型。您可以随时向我咨询当前等级资产配比的逻辑、季调优化建议、或者任何关于抗跌、抗通胀、夏普比率等专业资产配置问题。",
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }
  ]);
  const [isTyping, setIsTyping] = useState<boolean>(false);
  const chatBottomRef = useRef<HTMLDivElement>(null);

  // AI Advisor Analysis assessment state
  const [aiAnalysis, setAiAnalysis] = useState<string | null>(null);
  const [generatingAnalysis, setGeneratingAnalysis] = useState<boolean>(false);

  // Quick Chat Prompts
  const quickPrompts = [
    "解析红利低波因子的抗风险表现",
    "第一资本在全球多资产配置上的大宗对冲权重",
    "现在是投资美股ETF还是中国A股量化的好时机？",
    "介绍下A股量化策略里的防守央企板块"
  ];

  // Pick correct portfolio based on targetType & riskLevel
  const getCurrentPortfolio = (): PortfolioData => {
    if (targetType === "US_ETF") {
      // Find exact risk level ETF portfolio
      return usEtfPortfolios.find(p => p.riskLevel === riskLevel) || usEtfPortfolios[3];
    } else {
      // China A-Share has 3 strategies mapped roughly to low, mid, high risk:
      // Level 1-3 -> AShare 1 (Low Vol, level 2)
      // Level 4-5 -> AShare 2 (Multi-Factor, level 4)
      // Level 6-7 -> AShare 3 (AI Neural, level 6)
      if (riskLevel <= 3) {
        return aSharePortfolios[0];
      } else if (riskLevel <= 5) {
        return aSharePortfolios[1];
      } else {
        return aSharePortfolios[2];
      }
    }
  };

  const currentPortfolio = getCurrentPortfolio();

  // Scroll to bottom of chat
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory, isTyping]);

  // Handle questionnaire completion
  const handleRiskAssessmentComplete = (score: number) => {
    setAssessedRiskScore(score);
    setRiskLevel(score);
    // Suggest appropriate initial strategy
    if (score >= 6) {
      setTargetType("A_SHARE"); // A-share AI alpha excels in high-volatility/tactical return seekers
    } else {
      setTargetType("US_ETF");
    }
    setShowRiskModal(false);
    
    // Automatically inject a system message recommending the portfolio
    const systemRec = `我的智能评测结果显示您的风险偏好为 L${score}（${score <= 2 ? "保守型" : score <= 5 ? "平衡型" : "进取型"}）。我已为您自动匹配并配置了【${score >= 6 ? "中国A股量化先锋 Alpha 策略" : "美股全球资产配置 ETF 组合（第一资本全天候配置）"}】。欢迎查阅下方详细的研究报告偏好与成分配比。`;
    setChatHistory(prev => [
      ...prev,
      {
        id: `assessment-${Date.now()}`,
        role: "assistant",
        text: systemRec,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      }
    ]);
  };

  // Generate specialized Advisor Markdown analysis by calling our server endpoint
  const requestQuarterlyAnalysis = async () => {
    setGeneratingAnalysis(true);
    setAiAnalysis(null);
    try {
      const response = await fetch("/api/portfolio-analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          riskScore: riskLevel,
          targetType: targetType,
          amount: investmentAmount,
          age: 38, // general assumption, or customized
          horizon: riskLevel <= 2 ? "中短期 (1-2年)" : riskLevel <= 5 ? "中期稳健 (2-4年)" : "长期复利 (5年以上)"
        })
      });
      if (!response.ok) throw new Error("API Network error");
      const result = await response.json();
      setAiAnalysis(result.text);
    } catch (e) {
      console.error(e);
      setAiAnalysis("### 顾问季度建议书生成异常\n\n服务暂时失联。当前组合偏好可通过量化模型即时校准，建议参考下方底层大数法则进行基本判断。本AI建议根据量化模型生成，历史业绩不代表未来表现。");
    } finally {
      setGeneratingAnalysis(false);
    }
  };

  // Run initial report suggestion on risk or target update
  useEffect(() => {
    setAiAnalysis(null);
  }, [riskLevel, targetType, investmentAmount]);

  // Handle chat submission
  const handleSendChat = async (textToSend?: string) => {
    const rawMsg = textToSend || chatInput;
    if (!rawMsg.trim()) return;

    if (!textToSend) {
      setChatInput("");
    }

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      text: rawMsg,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setChatHistory(prev => [...prev, userMsg]);
    setIsTyping(true);

    try {
      // Map history correctly for server endpoint
      const formattedHistory = chatHistory.slice(-10).map(msg => ({
        role: msg.role,
        text: msg.text
      }));

      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: rawMsg,
          history: formattedHistory
        })
      });

      if (!res.ok) throw new Error("Chat api failed");
      const data = await res.json();

      setIsTyping(false);
      setChatHistory(prev => [
        ...prev,
        {
          id: `ai-${Date.now()}`,
          role: "assistant",
          text: data.text,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        }
      ]);
    } catch (error) {
      console.error(error);
      setIsTyping(false);
      setChatHistory(prev => [
        ...prev,
        {
          id: `ai-err-${Date.now()}`,
          role: "assistant",
          text: "十分抱歉，我正处于后台算法调仓期间，信号偶有波动。请在下方重试发送，或者您可以点击旁边的‘专属建议书’进行一键报告评定。",
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        }
      ]);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSendChat();
    }
  };

  // Format Helper for markdown-like bullet points & headers
  const renderMarkdown = (text: string) => {
    return text.split("\n").map((line, i) => {
      // Headers
      if (line.startsWith("### ")) {
        return <h4 key={i} className="text-sm font-bold text-teal-400 mt-4 mb-2">{line.replace("### ", "")}</h4>;
      }
      if (line.startsWith("## ")) {
        return <h3 key={i} className="text-base font-bold text-teal-400 mt-5 mb-2 border-b border-slate-800 pb-1">{line.replace("## ", "")}</h3>;
      }
      if (line.startsWith("# ")) {
        return <h3 key={i} className="text-lg font-bold text-white mt-6 mb-3 border-b border-teal-500/20 pb-1.5">{line.replace("# ", "")}</h3>;
      }
      // Bullet points
      if (line.trim().startsWith("- ")) {
        return (
          <li key={i} className="ml-4 list-disc text-xs text-slate-300 leading-relaxed mb-1">
            {line.substring(2)}
          </li>
        );
      }
      if (line.trim().startsWith("* ")) {
        return (
          <li key={i} className="ml-4 list-disc text-xs text-slate-300 leading-relaxed mb-1">
            {line.substring(2)}
          </li>
        );
      }
      // Number lines
      if (/^\d+\.\s/.test(line.trim())) {
        return (
          <p key={i} className="text-xs text-slate-200 pl-2 leading-relaxed mb-2 font-medium">
            {line}
          </p>
        );
      }
      // Bold items
      if (line.includes("**")) {
        const parts = line.split("**");
        return (
          <p key={i} className="text-xs text-slate-300 leading-relaxed mb-2">
            {parts.map((p, idx) => idx % 2 === 1 ? <strong key={idx} className="text-teal-300 font-semibold">{p}</strong> : p)}
          </p>
        );
      }
      // Empty lines
      if (!line.trim()) return <div key={i} className="h-2" />;
      
      return <p key={i} className="text-xs text-slate-300 leading-relaxed mb-1.5">{line}</p>;
    });
  };

  // First Capital (1269.hk) calculated average fee based on amount
  const getCalculatedFee = (amt: number): number => {
    // 50万人民币 = ~7.1万美元
    const parsedUsd = amt * 10000 / 7.2; // 1 USD = 7.2 CNY approximately
    if (parsedUsd <= 10000) return feeStructure[0].fee;
    if (parsedUsd <= 50000) return feeStructure[1].fee;
    if (parsedUsd <= 100000) return feeStructure[2].fee;
    return feeStructure[3].fee;
  };

  return (
    <div className="bg-[#0A0E14] text-slate-100 font-sans min-h-screen flex flex-col antialiased selection:bg-blue-600/30 selection:text-white">
      
      {/* Dynamic Geometric Accent Line */}
      <div className="h-1 w-full bg-gradient-to-r from-blue-600 via-teal-400 to-indigo-600" />

      {/* Header Container */}
      <header className="border-b border-slate-800/90 bg-[#0D121A] sticky top-0 z-40 backdrop-blur-md bg-opacity-95 px-4 md:px-10 py-4" id="app-header">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
          
          {/* Logo & Slogan */}
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-blue-600 flex items-center justify-center rounded-sm rotate-45 shrink-0 transition-transform hover:rotate-90 duration-500">
              <div className="w-5 h-5 border-2 border-white -rotate-45" />
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <span className="text-xl font-extrabold tracking-tight text-white font-sans">
                  FIRST CAPITAL
                </span>
                <span className="text-xs bg-blue-500/20 text-blue-400 border border-blue-500/30 px-1.5 py-0.5 rounded-sm font-mono uppercase tracking-wider">
                  Quant Robo
                </span>
              </div>
              <p className="text-[10px] text-slate-500 tracking-widest font-mono uppercase mt-0.5">
                中国A股量化 & 全球美股ETF智能投顾机构
              </p>
            </div>
          </div>

          {/* Navigation links - organize screens in dashboard */}
          <nav className="flex flex-wrap gap-1.5 md:gap-4 text-xs font-semibold uppercase tracking-wider text-slate-400">
            <button 
              onClick={() => { setActiveTab("investment"); }}
              className={`px-3 py-2 rounded-sm transition-all ${activeTab === "investment" ? "text-white bg-slate-800 border-l-2 border-blue-500 font-bold" : "hover:text-white hover:bg-slate-900/50"}`}
              id="nav-invest-tab"
            >
              一站式智投
            </button>
            <button 
              onClick={() => { setActiveTab("quant"); setTargetType("A_SHARE"); }}
              className={`px-3 py-2 rounded-sm transition-all ${activeTab === "quant" ? "text-white bg-slate-800 border-l-2 border-pink-500 font-bold" : "hover:text-white hover:bg-slate-900/50"}`}
              id="nav-quant-tab"
            >
              A股量化多因子
            </button>
            <button 
              onClick={() => { setActiveTab("etf"); setTargetType("US_ETF"); }}
              className={`px-3 py-2 rounded-sm transition-all ${activeTab === "etf" ? "text-white bg-slate-800 border-l-2 border-teal-500 font-bold" : "hover:text-white hover:bg-slate-900/50"}`}
              id="nav-etf-tab"
            >
              美股ETF全球分散
            </button>
            <button 
              onClick={() => { setActiveTab("about"); }}
              className={`px-3 py-2 rounded-sm transition-all ${activeTab === "about" ? "text-white bg-slate-800 border-l-2 border-violet-500 font-bold" : "hover:text-white hover:bg-slate-900/50"}`}
              id="nav-about-tab"
            >
              首控上市公司背景
            </button>
          </nav>

          <div className="flex items-center gap-3 shrink-0">
            {assessedRiskScore ? (
              <span className="text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2.5 py-1 rounded-sm font-mono font-semibold">
                理财评估：L{assessedRiskScore}
              </span>
            ) : (
              <button 
                onClick={() => setShowRiskModal(true)}
                className="px-4 py-1.5 border border-blue-500 text-blue-400 text-xs font-bold hover:bg-blue-500 hover:text-white transition-all rounded-sm tracking-wide"
                id="header-risk-btn"
              >
                专属风险测评
              </button>
            )}
            
            <a 
              href="#ai-assistant-widget" 
              className="p-1.5 rounded-sm bg-slate-800/80 hover:bg-slate-700 text-slate-300 hover:text-white"
              title="智能投顾问答"
            >
              <MessageSquare className="h-4.5 w-4.5" />
            </a>
          </div>

        </div>
      </header>

      {/* Main Body */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-4 md:p-8 space-y-8 relative z-10">
        
        {/* Banner Section */}
        <section className="bg-gradient-to-br from-[#0c131a] to-[#121c27] border border-slate-800/80 rounded-2xl p-6 md:p-10 relative overflow-hidden shadow-2xl">
          <div className="absolute top-0 right-0 w-96 h-96 bg-blue-600/10 rounded-full blur-3xl pointer-events-none" />
          <div className="absolute -bottom-20 -left-20 w-96 h-96 bg-teal-500/10 rounded-full blur-3xl pointer-events-none" />

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center relative z-10">
            {/* Slogan details */}
            <div className="lg:col-span-7 space-y-4">
              <div className="inline-flex items-center gap-2 px-3 py-1 bg-blue-500/10 text-blue-400 border border-blue-500/20 rounded-full text-xs font-mono font-medium uppercase tracking-wider">
                <Compass className="h-3.5 w-3.5 animate-spin" />
                第一资本全新升级
              </div>
              
              <h1 className="text-3xl md:text-5xl font-extrabold tracking-tight text-white leading-tight">
                量化配置 & 全球智投 <br />
                <span className="bg-gradient-to-r from-blue-400 via-teal-300 to-indigo-400 bg-clip-text text-transparent">
                  一键开启专业资产包
                </span>
              </h1>
              
              <p className="text-slate-300 text-sm md:text-base leading-relaxed max-w-2xl">
                作为港股上市公司首控集团旗下（上市代码：<b>1269.HK</b>）的创新智能金融科技品牌，第一资本为您融合了<b>中国A股多因子增强量化策略</b>（旨在战胜沪深300提取超额阿尔法系数）与<b>美股跨资产ETF全球配置策略</b>（通过量化穿透低费率优质ETF，平衡汇率、黄金等另类保值仓位），带来透明、合规、专业的全球买方顾问平台服务。
              </p>

              <div className="flex flex-wrap items-center gap-3 pt-2">
                <button
                  onClick={() => setShowRiskModal(true)}
                  className="px-6 py-3 bg-blue-600 text-white font-bold text-xs uppercase tracking-widest rounded-sm shadow-lg hover:bg-blue-500 transition-all flex items-center gap-2 cursor-pointer"
                  id="cta-survey-btn"
                >
                  智能财富评测 (3分钟)
                  <ArrowRight className="h-4 w-4" />
                </button>
                <a
                  href="#ai-assistant-widget"
                  className="px-5 py-3 border border-slate-700 hover:border-slate-500 text-slate-300 hover:text-white font-bold text-xs uppercase tracking-widest rounded-sm transition-all"
                >
                  AI 顾问直聊咨询
                </a>
              </div>
            </div>

            {/* Quick Overview Highlight Stats */}
            <div className="lg:col-span-5 grid grid-cols-2 gap-4">
              <div className="bg-slate-900/80 border border-slate-800/80 rounded-xl p-4 transition-all hover:border-blue-500/30">
                <div className="text-xs text-slate-500 font-mono uppercase">Assets Under Advisory</div>
                <div className="text-3xl font-extrabold text-white mt-1.5 font-mono tracking-tight">$1.2B+</div>
                <p className="text-[10px] text-slate-400 mt-2">受托及顾问财富规模（美金等值）</p>
              </div>

              <div className="bg-slate-900/80 border border-slate-800/80 rounded-xl p-4 transition-all hover:border-pink-500/30">
                <div className="text-xs text-slate-500 font-mono uppercase">Average Benchmark Alpha</div>
                <div className="text-3xl font-extrabold text-[#f43f5e] mt-1.5 font-mono tracking-tight">+6.8%</div>
                <p className="text-[10px] text-slate-400 mt-2">A股量化因子的历史超额收益中值</p>
              </div>

              <div className="bg-slate-900/80 border border-slate-800/80 rounded-xl p-4 transition-all hover:border-teal-500/30">
                <div className="text-xs text-slate-500 font-mono uppercase">Fee Standard</div>
                <div className="text-3xl font-extrabold text-teal-400 mt-1.5 font-mono tracking-tight">0.35%起</div>
                <p className="text-[10px] text-slate-400 mt-2">无购入赎回费，费率降幅对标欧美</p>
              </div>

              <div className="bg-slate-900/80 border border-slate-800/80 rounded-xl p-4 transition-all hover:border-indigo-500/30">
                <div className="text-xs text-slate-500 font-mono uppercase">Registered Users</div>
                <div className="text-3xl font-extrabold text-indigo-400 mt-1.5 font-mono tracking-tight">42,000+</div>
                <p className="text-[10px] text-slate-400 mt-2">高净值华人投资者及出海配置首选</p>
              </div>
            </div>
          </div>
        </section>

        {/* Tab content conditional renderings */}
        {activeTab === "about" ? (
          <section className="bg-slate-900 border border-slate-800 rounded-2xl p-6 md:p-8 space-y-6" id="about-first-capital-section">
            <div className="border-b border-slate-800 pb-4">
              <h2 className="text-2xl font-bold text-white tracking-tight">关于第一资本 (首控集团上市代号 1269.HK) 核心优势</h2>
              <p className="text-slate-400 text-xs mt-1">
                为什么选择资产配置，而不是单一重仓个股？
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="bg-slate-950/50 border border-slate-800 p-5 rounded-xl space-y-3">
                <div className="h-10 w-10 rounded-lg bg-blue-500/10 text-blue-400 flex items-center justify-center font-bold font-mono">01</div>
                <h4 className="text-base font-semibold text-slate-100">底层资产全球透支</h4>
                <p className="text-xs text-slate-400 leading-relaxed">
                  通过低成本指数ETF（Exchange Traded Funds）一键横跨美国标普500、纳克指数、德国DAX、新兴市场及政府短期中长期债券，杜绝单一持仓暴雷风险。
                </p>
              </div>

              <div className="bg-slate-950/50 border border-slate-800 p-5 rounded-xl space-y-3">
                <div className="h-10 w-10 rounded-lg bg-teal-500/10 text-teal-400 flex items-center justify-center font-bold font-mono">02</div>
                <h4 className="text-base font-semibold text-slate-100">全权委托自动重平衡</h4>
                <p className="text-xs text-slate-400 leading-relaxed">
                  偏离量化界值时自动再平衡(Rebalancing)。例如因股市大涨导致股票权重增加，系统会在零滑点下自动将多盈股票赎回买入债券，锁定利润实现长青复利。
                </p>
              </div>

              <div className="bg-slate-950/50 border border-slate-800 p-5 rounded-xl space-y-3">
                <div className="h-10 w-10 rounded-lg bg-indigo-500/10 text-indigo-400 flex items-center justify-center font-bold font-mono">03</div>
                <h4 className="text-base font-semibold text-slate-100">大额资产专属降费</h4>
                <p className="text-xs text-slate-400 leading-relaxed">
                  区别于基金销售的抽成佣金模式，第一资本采用欧美同步的“管理费率递减法”。规模越大，顾问费越低（最低至 0.35%），实现与客户本金共进退的核心利益捆绑。
                </p>
              </div>
            </div>

            <div className="bg-[#0C1118] border border-slate-800 p-6 rounded-xl flex flex-col md:flex-row gap-6 items-center justify-between">
              <div>
                <h4 className="text-sm font-bold text-white">觉得问卷复杂？直接与第一资本AI团队取得联系</h4>
                <p className="text-xs text-slate-400 mt-1 max-w-xl">
                  AI高级投顾依托第一资本核心BP商业计划书，可全天候解答因子归因、行业周期轮动、美日利差及大宗黄金的配比哲学。
                </p>
              </div>
              <button 
                onClick={() => setActiveTab("investment")}
                className="px-6 py-2.5 bg-blue-600 text-white rounded-sm text-xs font-bold leading-none tracking-widest uppercase hover:bg-blue-500"
              >
                点此进入投顾交互终端
              </button>
            </div>
          </section>
        ) : (
          <div className="space-y-8">
            
            {/* Risk Assessment Questionnaire Trigger Spot (or inline display) */}
            {showRiskModal && (
              <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-xs flex items-center justify-center p-4 z-50">
                <div className="w-full max-w-2xl bg-white rounded-2xl overflow-hidden shadow-2xl relative">
                  <div className="bg-slate-900 px-6 py-4 flex items-center justify-between text-white border-b border-slate-800">
                    <div className="flex items-center gap-2">
                      <Shield className="h-4.5 w-4.5 text-teal-400" />
                      <span className="text-sm font-bold">First Capital 投资风险偏好测评</span>
                    </div>
                    <button 
                      onClick={() => setShowRiskModal(false)}
                      className="text-slate-400 hover:text-white font-mono text-lg p-1"
                    >
                      ✕
                    </button>
                  </div>
                  <div>
                    <RiskAssessment 
                      onComplete={handleRiskAssessmentComplete}
                      currentScore={assessedRiskScore}
                      onReset={() => setAssessedRiskScore(null)}
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Core Interactive Workspace: Left Pane (Strategy settings & AI Advisor) & Right Pane (Selected Portfolio performance breakdown) */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
              
              {/* Left Column: Config Panel (Risk level selector, amount settings, action triggers) - 5 Cols */}
              <div className="lg:col-span-5 space-y-6">
                
                {/* Portfolio Settings Card */}
                <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 md:p-6 space-y-6">
                  <div className="border-b border-slate-800 pb-3 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Sliders className="h-4 w-4 text-blue-500" />
                      <h2 className="text-sm font-mono font-bold text-slate-100 tracking-wider">PORTFOLIO ALIGNMENT</h2>
                    </div>
                    <button
                      onClick={() => setShowRiskModal(true)}
                      className="text-xs text-blue-400 hover:text-blue-300 font-semibold flex items-center gap-1.5"
                      id="reset-survey-btn-inline"
                    >
                      <RotateCcw className="h-3 w-3" />
                      重新测评
                    </button>
                  </div>

                  {/* Product class selection */}
                  <div className="space-y-2">
                    <label className="text-xs text-slate-400 font-medium">主打智投产品大类</label>
                    <div className="grid grid-cols-2 gap-2 bg-[#0A0E14] p-1 rounded-sm border border-slate-800">
                      <button
                        onClick={() => { setTargetType("US_ETF"); }}
                        className={`py-2 text-center text-xs font-bold transition-all ${targetType === "US_ETF" ? "bg-blue-600 text-white rounded-sm" : "text-slate-400 hover:text-white"}`}
                        id="select-us-etf-btn"
                      >
                        美股全球ETF组合（全天候智配）
                      </button>
                      <button
                        onClick={() => { setTargetType("A_SHARE"); }}
                        className={`py-2 text-center text-xs font-bold transition-all ${targetType === "A_SHARE" ? "bg-blue-600 text-white rounded-sm" : "text-slate-400 hover:text-white"}`}
                        id="select-a-share-btn"
                      >
                        中国A股多因子量化 strategy
                      </button>
                    </div>
                  </div>

                  {/* Risk Level Slider Selector */}
                  <div className="space-y-3">
                    <div className="flex justify-between items-center">
                      <label className="text-xs text-slate-400 font-medium">风险适应配置评级 (Risk Range)</label>
                      <span className="text-xs bg-blue-500/20 text-white border border-blue-500/30 px-2 py-0.5 rounded-sm font-mono font-bold">
                        Level {riskLevel} / 7
                      </span>
                    </div>

                    <div className="flex gap-1.5 justify-between">
                      {[1, 2, 3, 4, 5, 6, 7].map((lvl) => (
                        <button
                          key={lvl}
                          onClick={() => setRiskLevel(lvl)}
                          className={`w-full py-1.5 rounded-xs text-xs font-mono font-bold border transition-all ${riskLevel === lvl ? "bg-blue-600 text-white border-blue-400" : "bg-[#0A0E14] text-slate-500 border-slate-800 hover:border-slate-700 hover:text-slate-300"}`}
                          id={`risk-lvl-btn-${lvl}`}
                        >
                          L{lvl}
                        </button>
                      ))}
                    </div>

                    <div className="flex justify-between text-[10px] text-slate-500 font-mono">
                      <span>L1: 绝对安泰型</span>
                      <span>L4: 股债平衡增强</span>
                      <span>L7: 极速复利追求</span>
                    </div>
                  </div>

                  {/* Investment Amount in CNY 十万 or 万 */}
                  <div className="space-y-3">
                    <div className="flex justify-between items-center">
                      <label className="text-xs text-slate-400 font-medium font-sans">理财储蓄本金规模</label>
                      <span className="text-xs text-slate-300 font-mono font-bold">
                        {investmentAmount} 万元 (RMB)
                      </span>
                    </div>
                    <input
                      type="range"
                      min="5"
                      max="1000"
                      step="5"
                      value={investmentAmount}
                      onChange={(e) => setInvestmentAmount(Number(e.target.value))}
                      className="w-full accent-blue-500 h-1.5 bg-slate-800 rounded-lg cursor-pointer"
                    />
                    <div className="flex justify-between text-[10px] text-slate-500 font-mono">
                      <span>5万元起投</span>
                      <span>500万限额</span>
                    </div>
                  </div>

                  {/* Interactive Fee Rate Display aligned with First Capital pricing schema */}
                  <div className="bg-[#0A0E14] border border-slate-800/80 rounded-xl p-3 flex items-center justify-between">
                    <div>
                      <div className="text-[10px] text-slate-500 font-mono">ANNUAL ADVISORY FEE (估值年顾问费)</div>
                      <div className="text-xs text-slate-300 mt-1 font-sans">
                        第一资本管理费率: <span className="font-mono font-bold text-teal-400">{targetType === "A_SHARE" ? aShareFeeRate : getCalculatedFee(investmentAmount)}%</span>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-[10px] text-slate-500 font-mono">EST. NET FEE (首年预计)</div>
                      <div className="text-xs font-bold text-teal-400 font-mono">
                        ¥{Math.round(investmentAmount * 10000 * (targetType === "A_SHARE" ? aShareFeeRate : getCalculatedFee(investmentAmount)) / 100)} / 年
                      </div>
                    </div>
                  </div>

                  {/* Advisory dynamic prompt panel */}
                  <div className="pt-2">
                    <button
                      onClick={requestQuarterlyAnalysis}
                      disabled={generatingAnalysis}
                      className="w-full py-3 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-bold text-xs uppercase tracking-widest rounded-sm transition-all shadow-md flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
                      id="generate-advice-btn"
                    >
                      {generatingAnalysis ? (
                        <>
                          <span className="animate-spin h-3.5 w-3.5 border-2 border-white border-t-transparent rounded-full" />
                          正在通过AI分析量化大纲...
                        </>
                      ) : (
                        <>
                          <Sparkles className="h-4 w-4" />
                          生成定制理财等级季度建议书
                        </>
                      )}
                    </button>
                    <p className="text-[9px] text-slate-500 text-center mt-2">
                      * 依托 Gemini 3.5 AI 顾问及第一资本量化模型数据，生成真实、严谨的多因子或资产配置大纲分析。
                    </p>
                  </div>

                </div>

                {/* Pricing / Comparison Table widget under First Capital listing style */}
                <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 md:p-6 space-y-4">
                  <div className="flex items-center gap-2">
                    <DollarSign className="h-4 w-4 text-pink-500" />
                    <h3 className="text-xs font-semibold uppercase tracking-wider font-mono text-slate-100">欧美买方投顾费率收费对比 (VS 传统银行)</h3>
                  </div>

                  <div className="space-y-2">
                    <div className="grid grid-cols-3 text-[10px] font-semibold text-slate-500 font-mono border-b border-slate-800 pb-1">
                      <span>本金档位</span>
                      <span className="text-center">第一资本顾问费</span>
                      <span className="text-right">传统银行及券商</span>
                    </div>

                    {feeStructure.map((f, i) => (
                      <div 
                        key={i} 
                        className={`grid grid-cols-3 text-xs py-1.5 ${investmentAmount * 10000 / 7.2 > f.threshold / 2 && investmentAmount * 10000 / 7.2 <= f.threshold ? "bg-blue-950/20 text-teal-400 font-semibold" : "text-slate-300"}`}
                      >
                        <span className="font-mono">
                          {f.threshold >= 1000000 ? "100w USD +" : `${f.threshold / 1000}k USD`}
                        </span>
                        <span className="text-center font-mono font-bold text-teal-400">
                          {f.fee}%
                        </span>
                        <span className="text-right text-slate-500 line-through">
                          1.2% - 1.8%
                        </span>
                      </div>
                    ))}
                  </div>

                  <p className="text-[10px] text-slate-500 leading-relaxed pt-1 border-t border-slate-800/60">
                    * 我们的费用结构无任何申购费、赎回费入场开户附加费用，不吃产品返佣，秉持买方投顾立场，始终服务于您。
                  </p>
                </div>

              </div>
              
              {/* Right Column: Breakdown & Interactive Performance - 7 Cols */}
              <div className="lg:col-span-7 space-y-8" id="portfolio-display-workspace">
                
                {/* Result header banner */}
                <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                  <div>
                    <span className="text-[10px] text-blue-500 font-mono uppercase tracking-widest font-semibold block">MATCHED ASSET ALLOCATION</span>
                    <h2 className="text-xl font-bold text-white tracking-tight mt-1">
                      {currentPortfolio.name}
                    </h2>
                    <p className="text-xs text-slate-400 mt-1 max-w-xl">
                      {currentPortfolio.description}
                    </p>
                  </div>
                  
                  <div className="shrink-0 flex items-center gap-2 bg-slate-950 p-3 rounded-xl border border-slate-800">
                    <div className="text-right">
                      <span className="text-[9px] text-slate-500 uppercase tracking-widest block">期望净回报</span>
                      <span className="text-lg font-bold text-emerald-400 font-mono">
                        +{currentPortfolio.expectedReturn.toFixed(1)}% <span className="text-xs font-normal">年化</span>
                      </span>
                    </div>
                  </div>
                </div>

                {/* Portfolio breakdown custom components (Donut and Asset Items) */}
                <PortfolioBreakdown portfolio={currentPortfolio} />

                {/* Performance simulated graph (Render with custom SVG grid) */}
                <PerformanceChart portfolio={currentPortfolio} />

                {/* Conditional AI dynamic quarter suggestion output */}
                {aiAnalysis && (
                  <div id="advisor-ai-report" className="bg-slate-900 border border-slate-800/80 rounded-2xl p-6 relative overflow-hidden shadow-xl">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-teal-500/10 rounded-full blur-2xl pointer-events-none" />
                    
                    <div className="flex items-center justify-between pb-4 border-b border-slate-800 mb-4">
                      <div className="flex items-center gap-2">
                        <div className="h-2 w-2 rounded-full bg-teal-400 animate-pulse" />
                        <h3 className="text-sm font-bold text-white">
                          第一资本 AI高级投资评级建议书
                        </h3>
                      </div>
                      <span className="text-[9px] font-semibold bg-slate-950 text-slate-500 px-2 py-0.5 rounded font-mono uppercase">
                        AI REPORT GENERATED
                      </span>
                    </div>

                    <div className="space-y-3 prose prose-slate prose-invert max-w-none">
                      {renderMarkdown(aiAnalysis)}
                    </div>

                    <div className="mt-6 pt-4 border-t border-slate-800 flex justify-between items-center text-[10px] text-slate-500">
                      <span>First Capital AI Robo Core • (基于Gemini技术构建)</span>
                      <span>报告时间: 今日</span>
                    </div>
                  </div>
                )}

              </div>

            </div>

            {/* AI Advisor Chatbot Terminal - Generous container at bottom */}
            <section id="ai-assistant-widget" className="bg-slate-900 border border-slate-800 rounded-3xl overflow-hidden shadow-2xl">
              
              {/* Chat Terminal Header */}
              <div className="px-6 py-5 bg-[#0D121A] border-b border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <div className="relative">
                    <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-blue-600 to-teal-400 flex items-center justify-center text-white font-bold shadow-md">
                      AI
                    </div>
                    <span className="absolute bottom-0 right-0 block h-2 py bg-teal-400 rounded-full ring-2 ring-slate-900" />
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-slate-100 flex items-center gap-1.5">
                      同享智投 - 第一资本 AI 智能投顾顾问
                    </h3>
                    <p className="text-xs text-slate-400 mt-0.5">
                      已挂载 A股量化多因子策略库、第一资本全天候全球多资产配置规则 及 本次风险测评等级参数
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-slate-400">当前对话状态:</span>
                  <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-teal-500/10 text-teal-400">
                    <Zap className="h-3.5 w-3.5" />
                    在线智能顾问
                  </span>
                </div>
              </div>

              {/* Chat Dialog body */}
              <div className="p-6 h-[340px] overflow-y-auto bg-slate-950/40 space-y-4 font-normal text-slate-200">
                {chatHistory.map((msg, i) => (
                  <div
                    key={msg.id || i}
                    className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"} items-start gap-3`}
                  >
                    {msg.role !== "user" && (
                      <div className="h-8 w-8 rounded-lg bg-teal-500/10 border border-teal-500/20 text-teal-400 text-xs font-mono font-bold flex items-center justify-center shrink-0 mt-0.5">
                        FC
                      </div>
                    )}
                    
                    <div className="max-w-[80%] space-y-1">
                      <div
                        className={`rounded-2xl px-4 py-3 text-xs leading-relaxed whitespace-pre-wrap ${
                          msg.role === "user"
                            ? "bg-blue-600 text-white rounded-tr-none"
                            : "bg-slate-900 border border-slate-800 text-slate-200 rounded-tl-none shadow-sm"
                        }`}
                      >
                        {msg.role === "assistant" && msg.text.includes("\n") ? (
                          <div className="prose prose-sm prose-invert">{renderMarkdown(msg.text)}</div>
                        ) : (
                          msg.text
                        )}
                      </div>
                      <span className="text-[9px] text-slate-500 font-mono tracking-wider block text-right px-1">
                        {msg.timestamp}
                      </span>
                    </div>

                    {msg.role === "user" && (
                      <div className="h-8 w-8 rounded-lg bg-blue-600/10 border border-blue-500/20 text-blue-400 text-xs font-mono font-bold flex items-center justify-center shrink-0 mt-0.5">
                        ME
                      </div>
                    )}
                  </div>
                ))}

                {isTyping && (
                  <div className="flex justify-start items-center gap-3">
                    <div className="h-8 w-8 rounded-lg bg-teal-500/10 border border-teal-500/20 text-teal-400 text-xs font-mono font-bold flex items-center justify-center shrink-0">
                      FC
                    </div>
                    <div className="bg-slate-900 border border-slate-800 rounded-2xl rounded-tl-none px-4 py-2.5 flex items-center gap-1">
                      <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                      <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                      <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                    </div>
                  </div>
                )}

                <div ref={chatBottomRef} />
              </div>

              {/* Chat Prompts Recommendation Panel */}
              <div className="px-6 py-3 bg-[#0D121A] border-t border-slate-800/60 flex items-center gap-3 overflow-x-auto whitespace-nowrap no-scrollbar scroll-smooth">
                <span className="text-[10px] text-slate-500 uppercase tracking-widest font-mono shrink-0">热门提问推荐:</span>
                <div className="flex gap-2">
                  {quickPrompts.map((pText, i) => (
                    <button
                      key={i}
                      onClick={() => handleSendChat(pText)}
                      className="px-3 py-1 rounded-full border border-slate-800 hover:border-blue-500 bg-slate-900/60 text-[11px] text-slate-300 hover:text-white transition-all font-sans cursor-pointer shrink-0"
                      id={`quick-prompt-${i}`}
                    >
                      {pText}
                    </button>
                  ))}
                </div>
              </div>

              {/* Chat input box */}
              <div className="p-4 bg-slate-950/80 border-t border-slate-800/80 flex items-center gap-3">
                <input
                  type="text"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={handleKeyPress}
                  placeholder={`咨询当前主打产品或针对 Level ${riskLevel} 专属配置提问...`}
                  className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-4 py-3 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 font-sans"
                  id="chat-user-input"
                />
                
                <button
                  onClick={() => handleSendChat()}
                  disabled={!chatInput.trim()}
                  className="px-5 py-3 bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs uppercase tracking-wider rounded-lg transition-all flex items-center gap-1.5 disabled:opacity-50 disabled:hover:bg-blue-600 cursor-pointer"
                  id="send-chat-btn"
                >
                  <Send className="h-3.5 w-3.5" />
                  发送
                </button>
              </div>

            </section>

          </div>
        )}

      </main>

      {/* Trust Compliance footer & details matching Geometric Balance */}
      <footer className="mt-20 border-t border-slate-800 bg-[#0D121A] py-10 px-4 md:px-10">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-8 text-xs text-slate-400">
          
          <div className="flex flex-wrap gap-12">
            <div className="flex flex-col">
              <span className="text-[10px] text-slate-600 uppercase tracking-widest mb-1.5">Assets Under Advisory</span>
              <span className="text-xl font-mono font-bold text-white">$1.2B+</span>
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] text-slate-600 uppercase tracking-widest mb-1.5">Registered Users</span>
              <span className="text-xl font-mono font-bold text-white">42,000+</span>
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] text-slate-600 uppercase tracking-widest mb-1.5">Compliant Partners</span>
              <span className="text-xl font-mono font-bold text-white">SEC / CSRC (合规托管)</span>
            </div>
          </div>

          <div className="text-slate-500 font-sans text-right max-w-sm leading-relaxed">
            <p>第一资本智能投顾团队。本AI建议及历史拟合回测基于统计因子生成。市场有风险，投资有风险，理财产品最终赎回表现不代表未来担保或保证利息收益。</p>
            <p className="mt-1">© 2026 First Capital (1269.HK). Powered by First Capital Global Asset Allocation framework.</p>
          </div>

        </div>
      </footer>
    </div>
  );
}
