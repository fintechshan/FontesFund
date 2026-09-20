/**
 * Types and Interfaces for First Capital Wealth Management (第一资本投顾)
 */

export interface PortfolioAsset {
  name: string;
  ticker?: string;
  category: string; // 'Equity' | 'Fixed Income' | 'Commodity' | 'Cash' or Factor names
  weight: number; // percentage, e.g. 35 for 35%
  color: string;
}

export interface PortfolioData {
  riskLevel: number; // 1 to 7
  name: string;
  description: string;
  expectedReturn: number; // yearly return %
  expectedVolatility: number; // yearly vol %
  sharpeRatio: number;
  assets: PortfolioAsset[];
  perfHistory: { year: number | string; portfolio: number; benchmark: number }[];
}

export interface Question {
  id: number;
  text: string;
  options: {
    text: string;
    score: number; // contributor to Risk Rating
  }[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  timestamp: string;
}
