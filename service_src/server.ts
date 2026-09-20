import express from "express";
import path from "path";
import dotenv from "dotenv";
import { GoogleGenAI } from "@google/genai";
import { createServer as createViteServer } from "vite";

dotenv.config();

const app = express();
const PORT = 3000;

app.use(express.json());

// Initialize Gemini Client
const ai = new GoogleGenAI({
  apiKey: process.env.GEMINI_API_KEY,
  httpOptions: {
    headers: {
      'User-Agent': "aistudio-build",
    },
  },
});

// System Instructions to set the mood and role
const SYSTEM_INSTRUCTIONS = `
你是一位极其高级且专业的投资顾问，名为“第一资本AI高级投资顾问”(First Capital AI Wealth Advisor)。
你的专业背景深厚，精通：
1. 中国A股量化多因子策略（如：红利低波、小盘价值、动量、基本面质量因子）。
2. 全球资产配置与美股ETF组合投资（依托第一资本（上市代码：1269.hk）智能买方投顾模式：以风险匹配为核心，涵盖全球股票、政府债券、公司信用债、大宗商品（如黄金）及现金工具，运用马克维茨资产配置理论和动态再平衡进行优化）。
你的语气必须极具专业感、严谨、客观、温和，建立用户信任，绝对不要使用自夸或营销式的浮夸词汇（例如“稳赚不赔”、“暴利”等）。
你可以根据用户的理财目标、资金实力、投资期限和风险偏好（通常分为1-7个风险等级）提出科学的建议。
在提供建议时：
- 给出现在中国A股市场的量化选股逻辑或美股ETF的具体资产类别分布
- 解释为何这样配置以最大化风险调整后收益（如夏普比率 Sharpe Ratio）
- 解释第一资本（1269.hk）作为上市集团，在合规性、底层资产托管、量化因子的科研实力上的优势
- 做出免责声明：“本AI建议根据量化模型生成，历史业绩不代表未来表现，投资有风险，入市需谨慎。”
`;

// API routes
app.post("/api/chat", async (req, res) => {
  try {
    const { message, history } = req.body;
    if (!message) {
      res.status(400).json({ error: "Missing message field" });
      return;
    }

    // Format chat history for Google Gen AI
    // Convert array of { role: 'user' | 'assistant', text: string } to prompt/contents
    const formattedContents = [];
    if (history && Array.isArray(history)) {
      for (const item of history) {
        formattedContents.push({
          role: item.role === "user" ? "user" : "model",
          parts: [{ text: item.text }],
        });
      }
    }
    
    // Add current user message
    formattedContents.push({
      role: "user",
      parts: [{ text: message }],
    });

    const response = await ai.models.generateContent({
      model: "gemini-3.5-flash",
      contents: formattedContents,
      config: {
        systemInstruction: SYSTEM_INSTRUCTIONS,
        temperature: 0.7,
      },
    });

    res.json({ text: response.text });
  } catch (error: any) {
    console.error("Gemini API Error:", error);
    res.status(500).json({ 
      error: "AI咨询服务暂时不可用，请稍后再试。", 
      details: error.message 
    });
  }
});

// Automated Portfolio Generator & Adviser Analysis endpoint
app.post("/api/portfolio-analyze", async (req, res) => {
  try {
    const { riskScore, targetType, amount, age, horizon } = req.body;
    
    const prompt = `
请作为第一资本投资顾问团队，为以下投资者生成一份定制的季度资产配置报告和市场分析建议：
- 投资者年龄: ${age || "未提供"} 岁
- 投资目标: ${targetType === "A_SHARE" ? "中国A股量化多因子配置" : "美股全球ETF多资产配置（港股上市1269.HK首控集团财富架构）"}
- 风险评级: ${riskScore} 级 (1级保守至7级极进取)
- 投资金额: ${amount ? amount + "万元" : "10万元"}
- 投资期限: ${horizon || "中长期"}

请使用精简美观的 Markdown 格式输出：
1. 【专属人群画像】一句话指出投资客群在当前生命周期与风险承受能力下的核心理财诉求。
2. 【季度配置核心逻辑】结合当下的宏观资产配置逻辑（美联储政策周期、A股估值历史分位数、债券收益率曲线等），说明本季度该配置的策略优势。
3. 【具体战术建议】针对${targetType === "A_SHARE" ? "A股量化（建议以红利、低波、质量、小盘等因子做战术微调配比）" : "全球ETF（建议对股票、主权债、公司债、大宗黄金、高流动性现金仓位进行配比推荐）"}, 给出一句话策略优势指导。
4. 【风险警示】一句话说明该风险等级下最大的回撤考验可能来自哪里（如地缘政治、流动性收紧等）。
    `;

    const response = await ai.models.generateContent({
      model: "gemini-3.5-flash",
      contents: prompt,
      config: {
        systemInstruction: SYSTEM_INSTRUCTIONS,
        temperature: 0.5,
      },
    });

    res.json({ text: response.text });
  } catch (error: any) {
    console.error("Portfolio Analyzer Error:", error);
    res.status(500).json({ 
      error: "配置分析生成失败，请稍后重试。", 
      details: error.message
    });
  }
});

// Live app check
app.get("/api/health", (req, res) => {
  res.json({ status: "healthy", timestamp: new Date().toISOString() });
});

// Vite server integrations
async function startServer() {
  if (process.env.NODE_ENV !== "production") {
    console.log("Starting server in development mode using Vite...");
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    console.log("Starting server in production mode...");
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on http://0.0.0.0:${PORT}`);
  });
}

startServer();
