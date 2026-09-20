import { PortfolioData, Question } from "./types";

// 第一资本（上市代码：1269.HK）全球多资产 ETF 配置模型 (Risk Levels 1 to 7)
export const usEtfPortfolios: PortfolioData[] = [
  {
    riskLevel: 1,
    name: "全球安泰守护组合 (Level 1)",
    description: "极低风险偏好，以本金安全和高流动性为终极原则。重仓配置超短期政府国债与高等级货币工具，抵抗通胀损耗。",
    expectedReturn: 3.2,
    expectedVolatility: 1.5,
    sharpeRatio: 1.80,
    assets: [
      { name: "超短期国债 ETF (BIL)", ticker: "BIL", category: "现金类工具", weight: 65, color: "#0d9488" },
      { name: "美国中短期通胀国债 ETF (VTIP)", ticker: "VTIP", category: "固定收益", weight: 20, color: "#0ea5e9" },
      { name: "投资级公司债 ETF (LQD)", ticker: "LQD", category: "固定收益", weight: 10, color: "#3b82f6" },
      { name: "黄金信托 ETF (GLD)", ticker: "GLD", category: "大宗/黄金", weight: 5, color: "#eab308" }
    ],
    perfHistory: [
      { year: "2021", portfolio: 1.1, benchmark: 0.5 },
      { year: "2022", portfolio: 1.5, benchmark: -0.2 },
      { year: "2023", portfolio: 4.2, benchmark: 3.5 },
      { year: "2024", portfolio: 4.8, benchmark: 4.0 },
      { year: "2025", portfolio: 3.6, benchmark: 3.1 }
    ]
  },
  {
    riskLevel: 2,
    name: "全球稳健增值组合 (Level 2)",
    description: "较低风险偏好，旨在实现稳健的现金分红和利息收入，提供适当的通胀防御能力。",
    expectedReturn: 4.5,
    expectedVolatility: 3.2,
    sharpeRatio: 1.25,
    assets: [
      { name: "超短期国债 ETF (BIL)", ticker: "BIL", category: "现金类工具", weight: 30, color: "#0d9488" },
      { name: "美国中短期通胀国债 ETF (VTIP)", ticker: "VTIP", category: "固定收益", weight: 30, color: "#0ea5e9" },
      { name: "投资级公司债 ETF (LQD)", ticker: "LQD", category: "固定收益", weight: 20, color: "#3b82f6" },
      { name: "标普500低波动 ETF (SPLV)", ticker: "SPLV", category: "全球股票", weight: 15, color: "#6366f1" },
      { name: "黄金信托 ETF (GLD)", ticker: "GLD", category: "大宗/黄金", weight: 5, color: "#eab308" }
    ],
    perfHistory: [
      { year: "2021", portfolio: 2.8, benchmark: 1.2 },
      { year: "2022", portfolio: -1.2, benchmark: -3.5 },
      { year: "2023", portfolio: 6.8, benchmark: 5.2 },
      { year: "2024", portfolio: 7.2, benchmark: 6.1 },
      { year: "2025", portfolio: 5.1, benchmark: 4.4 }
    ]
  },
  {
    riskLevel: 3,
    name: "全球均衡防御组合 (Level 3)",
    description: "中低风险偏好。在保障债券固定收益底仓的前提下，通过全球大市值蓝筹股获取稳步上升的红利机会。",
    expectedReturn: 5.8,
    expectedVolatility: 5.1,
    sharpeRatio: 0.98,
    assets: [
      { name: "美国中短期通胀国债 ETF (VTIP)", ticker: "VTIP", category: "固定收益", weight: 25, color: "#0ea5e9" },
      { name: "投资级公司债 ETF (LQD)", ticker: "LQD", category: "固定收益", weight: 25, color: "#3b82f6" },
      { name: "标普500价值股 ETF (IVE)", ticker: "IVE", category: "全球股票", weight: 20, color: "#6366f1" },
      { name: "先锋全球股票 ETF (VT)", ticker: "VT", category: "全球股票", weight: 20, color: "#4f46e5" },
      { name: "黄金信托 ETF (GLD)", ticker: "GLD", category: "大宗/黄金", weight: 10, color: "#eab308" }
    ],
    perfHistory: [
      { year: "2021", portfolio: 5.4, benchmark: 3.1 },
      { year: "2022", portfolio: -4.8, benchmark: -8.2 },
      { year: "2023", portfolio: 10.5, benchmark: 8.5 },
      { year: "2024", portfolio: 11.2, benchmark: 9.8 },
      { year: "2025", portfolio: 7.4, benchmark: 6.2 }
    ]
  },
  {
    riskLevel: 4,
    name: "全球平衡平衡组合 (Level 4)",
    description: "标准中度风险匹配，即经典的股债平衡策略(均衡偏好)。在股票获取上行增值与债券抵御熊市波动之间实现科学平移。",
    expectedReturn: 7.1,
    expectedVolatility: 7.5,
    sharpeRatio: 0.84,
    assets: [
      { name: "标普500 ETF (SPY)", ticker: "SPY", category: "全球股票", weight: 25, color: "#6366f1" },
      { name: "先锋全球股票 ETF (VT)", ticker: "VT", category: "全球股票", weight: 20, color: "#4f46e5" },
      { name: "非美发达市场 ETF (VEA)", ticker: "VEA", category: "全球股票", weight: 10, color: "#8b5cf6" },
      { name: "彭博全美综合债券 ETF (AGG)", ticker: "AGG", category: "固定收益", weight: 35, color: "#3b82f6" },
      { name: "黄金信托 ETF (GLD)", ticker: "GLD", category: "大宗/黄金", weight: 10, color: "#eab308" }
    ],
    perfHistory: [
      { year: "2021", portfolio: 9.2, benchmark: 7.1 },
      { year: "2022", portfolio: -9.5, benchmark: -13.6 },
      { year: "2023", portfolio: 14.8, benchmark: 12.1 },
      { year: "2024", portfolio: 16.5, benchmark: 14.2 },
      { year: "2025", portfolio: 10.2, benchmark: 8.4 }
    ]
  },
  {
    riskLevel: 5,
    name: "全球均衡增长组合 (Level 5)",
    description: "中高风险偏好，定位于长期资产累积。以全球发达国家及新兴市场股票为主力配置，辅以小份额高收益信用债和黄金对冲。",
    expectedReturn: 8.4,
    expectedVolatility: 10.2,
    sharpeRatio: 0.74,
    assets: [
      { name: "标普500 ETF (SPY)", ticker: "SPY", category: "全球股票", weight: 35, color: "#6366f1" },
      { name: "先锋全球股票 ETF (VT)", ticker: "VT", category: "全球股票", weight: 20, color: "#4f46e5" },
      { name: "新兴市场股票 ETF (VWO)", ticker: "VWO", category: "全球股票", weight: 15, color: "#a855f7" },
      { name: "高收益公司债 ETF (HYG)", ticker: "HYG", category: "固定收益", weight: 20, color: "#3b82f6" },
      { name: "黄金信托 ETF (GLD)", ticker: "GLD", category: "大宗/黄金", weight: 10, color: "#eab308" }
    ],
    perfHistory: [
      { year: "2021", portfolio: 12.8, benchmark: 9.5 },
      { year: "2022", portfolio: -13.2, benchmark: -18.1 },
      { year: "2023", portfolio: 18.4, benchmark: 15.6 },
      { year: "2024", portfolio: 21.0, benchmark: 18.2 },
      { year: "2025", portfolio: 12.8, benchmark: 10.5 }
    ]
  },
  {
    riskLevel: 6,
    name: "全球成长领航组合 (Level 6)",
    description: "高风险偏好。侧重于捕捉科技浪潮与全球经济高增速红利，允许适度回撤以极大限度扩容长期资本的复合增值空间。",
    expectedReturn: 9.8,
    expectedVolatility: 13.8,
    sharpeRatio: 0.65,
    assets: [
      { name: "纳斯达克100交易信托 (QQQ)", ticker: "QQQ", category: "全球股票", weight: 40, color: "#ec4899" },
      { name: "标普500 ETF (SPY)", ticker: "SPY", category: "全球股票", weight: 25, color: "#6366f1" },
      { name: "新兴市场股票 ETF (VWO)", ticker: "VWO", category: "全球股票", weight: 15, color: "#a855f7" },
      { name: "彭博全美综合债券 ETF (AGG)", ticker: "AGG", category: "固定收益", weight: 10, color: "#3b82f6" },
      { name: "黄金信托 ETF (GLD)", ticker: "GLD", category: "大宗/黄金", weight: 10, color: "#eab308" }
    ],
    perfHistory: [
      { year: "2021", portfolio: 17.5, benchmark: 12.8 },
      { year: "2022", portfolio: -18.9, benchmark: -21.4 },
      { year: "2023", portfolio: 22.8, benchmark: 19.2 },
      { year: "2024", portfolio: 25.4, benchmark: 21.5 },
      { year: "2025", portfolio: 15.2, benchmark: 12.1 }
    ]
  },
  {
    riskLevel: 7,
    name: "全球极速开拓组合 (Level 7)",
    description: "极高风险偏好，致力于在长周期内通过跨国、跨行业、高beta因子的核心与卫星组合夺取超凡回报，极少防御持仓。",
    expectedReturn: 11.5,
    expectedVolatility: 17.5,
    sharpeRatio: 0.61,
    assets: [
      { name: "纳斯达克100交易信托 (QQQ)", ticker: "QQQ", category: "全球股票", weight: 50, color: "#ec4899" },
      { name: "先锋全球股票 ETF (VT)", ticker: "VT", category: "全球股票", weight: 30, color: "#4f46e5" },
      { name: "新兴市场股票 ETF (VWO)", ticker: "VWO", category: "全球股票", weight: 15, color: "#a855f7" },
      { name: "黄金信托 ETF (GLD)", ticker: "GLD", category: "大宗/黄金", weight: 5, color: "#eab308" }
    ],
    perfHistory: [
      { year: "2021", portfolio: 21.2, benchmark: 15.4 },
      { year: "2022", portfolio: -24.5, benchmark: -25.2 },
      { year: "2023", portfolio: 28.5, benchmark: 23.4 },
      { year: "2024", portfolio: 31.2, benchmark: 26.1 },
      { year: "2025", portfolio: 18.5, benchmark: 14.8 }
    ]
  }
];

// China A-Share Quantitative Portfolios (Risk Levels represented as low, mid, high risk strategies)
export const aSharePortfolios: PortfolioData[] = [
  {
    riskLevel: 2, // Low Vol Factor Strategy
    name: "红利低波基本面策略 (A股量化1号)",
    description: "侧重红利因子(HIGH DIVIDEND)与低波动因子(LOW VOLATILITY)，精选估值低起、现金流健康、派息率高且波动较小的白马股，用量化多因子层层过滤排雷。长期跑赢沪深300指数，防守抗跌性能出众。",
    expectedReturn: 8.5,
    expectedVolatility: 9.8,
    sharpeRatio: 0.95,
    assets: [
      { name: "中证红利指数池精选 (高股息因子)", category: "红利因子", weight: 45, color: "#10b981" },
      { name: "央企稳健白马池精选 (低波质量因子)", category: "央企/低波动", weight: 35, color: "#06b6d4" },
      { name: "防守性大公用板块精选 (高稳态类债)", category: "基本面质量", weight: 15, color: "#3b82f6" },
      { name: "国债逆回购与高流动现金", category: "低风险现金", weight: 5, color: "#0d9488" }
    ],
    perfHistory: [
      { year: "2021", portfolio: 12.2, benchmark: -5.2 },
      { year: "2022", portfolio: -2.1, benchmark: -21.6 },
      { year: "2023", portfolio: 4.8, benchmark: -11.4 },
      { year: "2024", portfolio: 15.6, benchmark: 4.1 },
      { year: "2025", portfolio: 9.4, benchmark: -1.2 }
    ]
  },
  {
    riskLevel: 4, // Multi-Factor Core EQ Strategy
    name: "中盘多因子增强动量策略 (A股量化2号)",
    description: "偏均衡风险，定位于中证500与中证800指数精选增强，结合成长因子(GROWTH)、动量因子(MOMENTUM)与分析师一致预期，动态捕捉景气度扩张的细分龙头，追求可控风险下的稳健阿尔法Alpha。",
    expectedReturn: 12.4,
    expectedVolatility: 15.2,
    sharpeRatio: 0.81,
    assets: [
      { name: "高景气中盘多因子策略池", category: "成长/盈利因子", weight: 40, color: "#ec4899" },
      { name: "中证500指数底层成长池增强", category: "指数优选", weight: 30, color: "#8b5cf6" },
      { name: "量化动量因子趋势追踪池", category: "价格动量", weight: 20, color: "#f59e0b" },
      { name: "国债逆回购与底仓流动资金", category: "低风险现金", weight: 10, color: "#0d9488" }
    ],
    perfHistory: [
      { year: "2021", portfolio: 18.5, benchmark: 12.0 },
      { year: "2022", portfolio: -15.4, benchmark: -20.3 },
      { year: "2023", portfolio: 2.3, benchmark: -7.4 },
      { year: "2024", portfolio: 21.4, benchmark: 10.3 },
      { year: "2025", portfolio: 14.8, benchmark: 1.5 }
    ]
  },
  {
    riskLevel: 6, // High beta/Neural Network enhanced high growth
    name: "AI 神经增强绝对收益Alpha 策略 (A股量化3号)",
    description: "高风险高增值，引入深度神经网络、机器学习自然语言情绪分析与非线性多因子模型，每日/每周高速换手捕捉微盘Alpha溢价与题材周期动量，追求超越市场波动的超额绝对收益。",
    expectedReturn: 18.1,
    expectedVolatility: 22.4,
    sharpeRatio: 0.76,
    assets: [
      { name: "机器学习非线性预测高超额池", category: "神经网络Alpha", weight: 50, color: "#3b82f6" },
      { name: "全天候新闻及舆情情绪量化池", category: "情绪因子", weight: 25, color: "#ec4899" },
      { name: "流动性与价量微粒波动超频池", category: "价量/换手率", weight: 20, color: "#a855f7" },
      { name: "对冲工具及期权防守仓位", category: "期权/备兑", weight: 5, color: "#e11d48" }
    ],
    perfHistory: [
      { year: "2021", portfolio: 35.6, benchmark: 12.0 },
      { year: "2022", portfolio: -13.8, benchmark: -20.3 },
      { year: "2023", portfolio: 12.4, benchmark: -7.4 },
      { year: "2024", portfolio: 39.8, benchmark: 10.3 },
      { year: "2025", portfolio: 22.4, benchmark: 1.5 }
    ]
  }
];

// 7 Risk Questionnaire Questions
export const riskQuestions: Question[] = [
  {
    id: 1,
    text: "您进行本次投资的主要终极目的是什么？",
    options: [
      { text: "极为抗拒任何本金亏损，安全度过退休期，希望保持资产基本购买力", score: 1 },
      { text: "希望获取稳定的红利生息，辅以轻微的价格温和增长", score: 2 },
      { text: "追求长期资产复利回报，愿意阶段性承受市场波动力度", score: 4 },
      { text: "渴望通过大比例配置成长型金融工具夺取超凡的高额成长", score: 6 }
    ]
  },
  {
    id: 2,
    text: "本笔闲置资金您计划投资多长期限，期间是否需要随时支取？",
    options: [
      { text: "小于1年，对流动性要求极高，不可锁定", score: 1 },
      { text: "1-3年，希望获得比一般储蓄好一些的中短期稳健回报", score: 3 },
      { text: "3-5年，资金无需急用，可接受中等年限滚动", score: 5 },
      { text: "5年以上或无限期，追求极度的跨越牛熊期的复利增长", score: 7 }
    ]
  },
  {
    id: 3,
    text: "当市场遭遇突发波动，您配置的资产在1个月内下跌了10%时，您会有何种心态与操作？",
    options: [
      { text: "感到极度焦虑、失眠，强烈要求立刻平仓锁定剩余资金", score: 1 },
      { text: "感到明显的心理不适，会不断观察行情并寻找止损机会", score: 3 },
      { text: "能够保持情绪基本平稳，视其为资产的理性常态波动，冷静持仓", score: 5 },
      { text: "视作便宜买入的极佳折价加仓黄金时机，会追加闲置资金", score: 7 }
    ]
  },
  {
    id: 4,
    text: "在您的家庭日常总资产中，本金投资账户占据的比例大概是多少？",
    options: [
      { text: "超过 70%（高度依赖这笔资金增值维持核心生活的品质）", score: 1 },
      { text: "35% - 70%（中等比重，需要对总本金表现留有戒备）", score: 3 },
      { text: "15% - 35%（资产占比合理，对核心生活几乎无扰动）", score: 5 },
      { text: "低于 15%（属于极度充裕的纯闲散资金，专注于风险开拓）", score: 7 }
    ]
  },
  {
    id: 5,
    text: "以下哪一项对您来说更契合您对投资组合收益与风险关系的期望？",
    options: [
      { text: "极低波动预期：目标年化 3-4% 左右，历史最大回撤争取在 1% 以内", score: 1 },
      { text: "温和均衡预期：目标年化 5-8% 左右，中途最大回撤可承受 5-8%", score: 3 },
      { text: "成长探索预期：目标年化 8-12% 左右，中途最大回撤可承受 15-20%", score: 5 },
      { text: "极致收益突破：目标年化 15% 以上，中期遭遇 30% 回撤也毫无动摇", score: 7 }
    ]
  },
  {
    id: 6,
    text: "您的家庭核心被动收入（如工资、物业租金等）整体稳定度评估如何？",
    options: [
      { text: "不太稳定或已退休，无长期持续的大额收入进账", score: 1 },
      { text: "基本稳定，但面临中规中矩的行业洗牌不确定性", score: 3 },
      { text: "非常稳定，属于高弹性专业人士或旱涝保收的成熟职业", score: 5 },
      { text: "实力充盈，多资产多现金源源不断流入", score: 7 }
    ]
  },
  {
    id: 7,
    text: "您此前是否有接触并投资股票、公募基金、ETF或海外理财的经历？",
    options: [
      { text: "完全零经验或仅做过极低风险的银行理财/宝宝类产品", score: 1 },
      { text: "1-3年浅层交易经验，知晓基本术语，但偶有亏折", score: 3 },
      { text: "3-5年经验，熟谙多元资产分类，能成熟配对和止盈", score: 5 },
      { text: "5年以上资深理财，经历过多轮完整的全球及中国大牛熊周期", score: 7 }
    ]
  }
];

// 第一资本（1269.HK）集团买方投顾费率结构 (Fee Structure)
export const feeStructure = [
  { threshold: 10000, fee: 0.75, description: "1万美金账户以内，享受第一资本顶级买方资产顾问咨询，标准年管理费率。" },
  { threshold: 50000, fee: 0.65, description: "5万美金账户以内，伴随资金体量扩大，费率自动平滑下降，优化长期持有复利。" },
  { threshold: 100000, fee: 0.55, description: "10万美金账户以内，专属大额账户配置降载费率红利，大幅跑赢公募和传统渠道。" },
  { threshold: 1000000, fee: 0.35, description: "百万大额以上超级专属费率，顶格一键对齐，提供专属私人财富经理1v1咨询专线。" }
];

// Multi-tier quantitative A-share standard fee
export const aShareFeeRate = 0.45; // Fixed 0.45% per annum for quant advisors, zero purchase and redemption surcharge
