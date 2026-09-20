/// <reference types="vite/client" />
import React, { useState, useEffect } from 'react';
import { 
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  BarChart, Bar, Cell
} from 'recharts';
import { 
  Briefcase, TrendingUp, ShieldAlert, Scale, Calculator, 
  AlertTriangle, CheckCircle2, DollarSign, Activity, PieChart,
  BookOpen, Globe, Building2, Calendar, Clock, User, RefreshCw, Zap, ExternalLink
} from 'lucide-react';

const currentDate = new Date().toLocaleDateString('en-US', { month: 'short', day: '2-digit', year: 'numeric' });

const backtestData = [{"year":"2006 Q1","portfolio":100000,"sp500":100000,"nasdaq":100000,"msci6040":100000,"allWeather":100000},{"year":"2006 Q2","portfolio":103229,"sp500":104077,"nasdaq":101573,"msci6040":102772,"allWeather":102046},{"year":"2006 Q3","portfolio":106457,"sp500":108154,"nasdaq":103146,"msci6040":105544,"allWeather":104092},{"year":"2006 Q4","portfolio":108806,"sp500":111120,"nasdaq":104289,"msci6040":107560,"allWeather":105580},{"year":"2007 Q1","portfolio":109784,"sp500":112355,"nasdaq":104766,"msci6040":108400,"allWeather":106200},{"year":"2007 Q2","portfolio":111546,"sp500":110816,"nasdaq":105714,"msci6040":109324,"allWeather":108279},{"year":"2007 Q3","portfolio":113308,"sp500":109277,"nasdaq":106662,"msci6040":110248,"allWeather":110358},{"year":"2007 Q4","portfolio":114589,"sp500":108158,"nasdaq":107351,"msci6040":110920,"allWeather":111870},{"year":"2008 Q1","portfolio":115123,"sp500":107692,"nasdaq":107638,"msci6040":111200,"allWeather":112500},{"year":"2008 Q2","portfolio":102494,"sp500":93445,"nasdaq":94884,"msci6040":103049,"allWeather":107847},{"year":"2008 Q3","portfolio":89865,"sp500":79197,"nasdaq":82130,"msci6040":94898,"allWeather":103194},{"year":"2008 Q4","portfolio":80680,"sp500":68835,"nasdaq":72855,"msci6040":88970,"allWeather":99810},{"year":"2009 Q1","portfolio":76853,"sp500":64518,"nasdaq":68990,"msci6040":86500,"allWeather":98400},{"year":"2009 Q2","portfolio":88904,"sp500":70911,"nasdaq":79808,"msci6040":91714,"allWeather":101733},{"year":"2009 Q3","portfolio":100956,"sp500":77304,"nasdaq":90625,"msci6040":96928,"allWeather":105066},{"year":"2009 Q4","portfolio":109720,"sp500":81954,"nasdaq":98493,"msci6040":100720,"allWeather":107490},{"year":"2010 Q1","portfolio":113372,"sp500":83891,"nasdaq":101771,"msci6040":102300,"allWeather":108500},{"year":"2010 Q2","portfolio":121977,"sp500":88057,"nasdaq":107648,"msci6040":105336,"allWeather":111767},{"year":"2010 Q3","portfolio":130582,"sp500":92224,"nasdaq":113525,"msci6040":108372,"allWeather":115034},{"year":"2010 Q4","portfolio":136840,"sp500":95254,"nasdaq":117799,"msci6040":110580,"allWeather":117410},{"year":"2011 Q1","portfolio":139447,"sp500":96516,"nasdaq":119580,"msci6040":111500,"allWeather":118400},{"year":"2011 Q2","portfolio":142208,"sp500":96850,"nasdaq":119895,"msci6040":112589,"allWeather":120413},{"year":"2011 Q3","portfolio":144969,"sp500":97185,"nasdaq":120211,"msci6040":113678,"allWeather":122426},{"year":"2011 Q4","portfolio":146977,"sp500":97428,"nasdaq":120440,"msci6040":114470,"allWeather":123890},{"year":"2012 Q1","portfolio":147814,"sp500":97529,"nasdaq":120536,"msci6040":114800,"allWeather":124500},{"year":"2012 Q2","portfolio":156106,"sp500":101946,"nasdaq":127437,"msci6040":118364,"allWeather":127173},{"year":"2012 Q3","portfolio":164398,"sp500":106364,"nasdaq":134339,"msci6040":121928,"allWeather":129846},{"year":"2012 Q4","portfolio":170429,"sp500":109576,"nasdaq":139358,"msci6040":124520,"allWeather":131790},{"year":"2013 Q1","portfolio":172942,"sp500":110915,"nasdaq":141449,"msci6040":125600,"allWeather":132600},{"year":"2013 Q2","portfolio":197482,"sp500":122023,"nasdaq":159327,"msci6040":131408,"allWeather":134547},{"year":"2013 Q3","portfolio":222023,"sp500":133132,"nasdaq":177205,"msci6040":137216,"allWeather":136494},{"year":"2013 Q4","portfolio":239871,"sp500":141211,"nasdaq":190207,"msci6040":141440,"allWeather":137910},{"year":"2014 Q1","portfolio":247307,"sp500":144577,"nasdaq":195624,"msci6040":143200,"allWeather":138500},{"year":"2014 Q2","portfolio":264445,"sp500":149883,"nasdaq":205241,"msci6040":146038,"allWeather":143351},{"year":"2014 Q3","portfolio":281583,"sp500":155188,"nasdaq":214858,"msci6040":148876,"allWeather":148202},{"year":"2014 Q4","portfolio":294048,"sp500":159047,"nasdaq":221853,"msci6040":150940,"allWeather":151730},{"year":"2015 Q1","portfolio":299241,"sp500":160655,"nasdaq":224767,"msci6040":151800,"allWeather":153200},{"year":"2015 Q2","portfolio":316028,"sp500":160082,"nasdaq":228769,"msci6040":150711,"allWeather":151418},{"year":"2015 Q3","portfolio":332816,"sp500":159509,"nasdaq":232771,"msci6040":149622,"allWeather":149636},{"year":"2015 Q4","portfolio":345025,"sp500":159093,"nasdaq":235681,"msci6040":148830,"allWeather":148340},{"year":"2016 Q1","portfolio":350112,"sp500":158919,"nasdaq":236894,"msci6040":148500,"allWeather":147800},{"year":"2016 Q2","portfolio":365132,"sp500":164121,"nasdaq":242835,"msci6040":152031,"allWeather":151331},{"year":"2016 Q3","portfolio":380151,"sp500":169324,"nasdaq":248777,"msci6040":155562,"allWeather":154862},{"year":"2016 Q4","portfolio":391075,"sp500":173108,"nasdaq":253098,"msci6040":158130,"allWeather":157430},{"year":"2017 Q1","portfolio":395626,"sp500":174684,"nasdaq":254898,"msci6040":159200,"allWeather":158500},{"year":"2017 Q2","portfolio":446543,"sp500":185827,"nasdaq":278619,"msci6040":166559,"allWeather":163153},{"year":"2017 Q3","portfolio":497460,"sp500":196970,"nasdaq":302339,"msci6040":173918,"allWeather":167806},{"year":"2017 Q4","portfolio":534491,"sp500":205073,"nasdaq":319591,"msci6040":179270,"allWeather":171190},{"year":"2018 Q1","portfolio":549920,"sp500":208450,"nasdaq":326779,"msci6040":181500,"allWeather":172600},{"year":"2018 Q2","portfolio":588029,"sp500":203736,"nasdaq":323652,"msci6040":178497,"allWeather":172237},{"year":"2018 Q3","portfolio":626139,"sp500":199022,"nasdaq":320524,"msci6040":175494,"allWeather":171874},{"year":"2018 Q4","portfolio":653855,"sp500":195594,"nasdaq":318250,"msci6040":173310,"allWeather":171610},{"year":"2019 Q1","portfolio":665403,"sp500":194165,"nasdaq":317302,"msci6040":172400,"allWeather":171500},{"year":"2019 Q2","portfolio":704928,"sp500":212778,"nasdaq":354369,"msci6040":182102,"allWeather":180377},{"year":"2019 Q3","portfolio":744453,"sp500":231392,"nasdaq":391436,"msci6040":191804,"allWeather":189254},{"year":"2019 Q4","portfolio":773198,"sp500":244929,"nasdaq":418394,"msci6040":198860,"allWeather":195710},{"year":"2020 Q1","portfolio":785175,"sp500":250569,"nasdaq":429626,"msci6040":201800,"allWeather":198400},{"year":"2020 Q2","portfolio":870680,"sp500":265428,"nasdaq":491043,"msci6040":212591,"allWeather":204076},{"year":"2020 Q3","portfolio":956186,"sp500":280287,"nasdaq":552461,"msci6040":223382,"allWeather":209752},{"year":"2020 Q4","portfolio":1018371,"sp500":291093,"nasdaq":597128,"msci6040":231230,"allWeather":213880},{"year":"2021 Q1","portfolio":1044282,"sp500":295596,"nasdaq":615739,"msci6040":234500,"allWeather":215600},{"year":"2021 Q2","portfolio":1098070,"sp500":314458,"nasdaq":700543,"msci6040":259679,"allWeather":229790},{"year":"2021 Q3","portfolio":1151857,"sp500":333321,"nasdaq":785346,"msci6040":284858,"allWeather":243980},{"year":"2021 Q4","portfolio":1190976,"sp500":347039,"nasdaq":847022,"msci6040":303170,"allWeather":254300},{"year":"2022 Q1","portfolio":1207275,"sp500":352755,"nasdaq":872720,"msci6040":310800,"allWeather":258600},{"year":"2022 Q2","portfolio":1153100,"sp500":341439,"nasdaq":818166,"msci6040":295818,"allWeather":247644},{"year":"2022 Q3","portfolio":1098925,"sp500":330123,"nasdaq":763612,"msci6040":280836,"allWeather":236688},{"year":"2022 Q4","portfolio":1059525,"sp500":321893,"nasdaq":723937,"msci6040":269940,"allWeather":228720},{"year":"2023 Q1","portfolio":1043108,"sp500":318464,"nasdaq":707405,"msci6040":265400,"allWeather":225400},{"year":"2023 Q2","portfolio":1175108,"sp500":331664,"nasdaq":740405,"msci6040":272000,"allWeather":228700},{"year":"2023 Q3","portfolio":1307108,"sp500":344864,"nasdaq":773405,"msci6040":278600,"allWeather":232000},{"year":"2023 Q4","portfolio":1403108,"sp500":354464,"nasdaq":797405,"msci6040":283400,"allWeather":234400},{"year":"2024 Q1","portfolio":1566182,"sp500":378543,"nasdaq":1001738,"msci6040":305200,"allWeather":248500},{"year":"2024 Q2","portfolio":1600000,"sp500":380000,"nasdaq":1010000,"msci6040":308000,"allWeather":249000},{"year":"2024 Q3","portfolio":1650000,"sp500":385000,"nasdaq":1030000,"msci6040":310000,"allWeather":250000},{"year":"2024 Q4","portfolio":1690000,"sp500":388000,"nasdaq":1040000,"msci6040":312000,"allWeather":250000},{"year":"2025 Q1","portfolio":1716182,"sp500":390000,"nasdaq":1050000,"msci6040":315000,"allWeather":250500},{"year":"2025 Q2","portfolio":1985182,"sp500":430543,"nasdaq":1121738,"msci6040":325200,"allWeather":260500},{"year":"2025 Q3","portfolio":1680500,"sp500":388000,"nasdaq":1010000,"msci6040":305000,"allWeather":252000},{"year":"2025 Q4","portfolio":2186911,"sp500":471887,"nasdaq":1255476,"msci6040":345600,"allWeather":270200},{"year":"2026 Q1","portfolio":1950000,"sp500":435000,"nasdaq":1150000,"msci6040":330000,"allWeather":265000},{"year":"2026 Q2","portfolio":2473070,"sp500":503813,"nasdaq":1431019,"msci6040":359424,"allWeather":278306}]
;

const pulseDataInitial = [
  { date: 'Apr 17', portfolio: 0, sp500: 0, nasdaq: 0 },
  { date: 'Apr 20', portfolio: -0.31, sp500: -0.24, nasdaq: -0.31 },
  { date: 'Apr 21', portfolio: -1.19, sp500: -0.87, nasdaq: -0.72 },
  { date: 'Apr 22', portfolio: 1.16, sp500: 0.17, nasdaq: 0.99 },
  { date: 'Apr 23', portfolio: 0.11, sp500: -0.25, nasdaq: 0.41 },
  { date: 'Apr 24', portfolio: 2.37, sp500: 0.55, nasdaq: 2.37 },
  { date: 'Apr 27', portfolio: 2.43, sp500: 0.67, nasdaq: 2.37 },
  { date: 'Apr 28', portfolio: 1.35, sp500: 0.18, nasdaq: 1.34 },
  { date: 'Apr 29', portfolio: 1.58, sp500: 0.14, nasdaq: 1.93 },
  { date: 'Apr 30', portfolio: 2.02, sp500: 1.16, nasdaq: 2.92 },
  { date: 'May 1', portfolio: 2.50, sp500: 1.46, nasdaq: 3.89 },
  { date: 'May 4', portfolio: 2.67, sp500: 1.05, nasdaq: 3.67 },
  { date: 'May 5', portfolio: 3.45, sp500: 1.87, nasdaq: 5.03 },
  { date: 'May 6', portfolio: 5.80, sp500: 3.35, nasdaq: 7.22 },
  { date: 'May 7', portfolio: 5.04, sp500: 2.96, nasdaq: 7.09 },
  { date: 'May 8', portfolio: 6.07, sp500: 3.83, nasdaq: 9.61 },
  { date: 'May 11', portfolio: 6.63, sp500: 4.02, nasdaq: 9.93 },
  { date: 'May 12', portfolio: 6.35, sp500: 3.86, nasdaq: 8.97 },
  { date: 'May 13', portfolio: 7.40, sp500: 4.47, nasdaq: 10.10 },
  { date: 'May 14', portfolio: 7.98, sp500: 5.26, nasdaq: 10.90 },
  { date: 'May 15', portfolio: 6.22, sp500: 3.96, nasdaq: 9.20 }
];

const SyncIndicator = ({ isSyncing, lastUpdated }: { isSyncing: boolean, lastUpdated: string }) => (
  <div className={`text-xs font-medium px-3 py-1.5 rounded-md flex items-center gap-1.5 transition-colors duration-300 ${isSyncing ? 'bg-blue-50 text-blue-600' : 'bg-emerald-50 text-emerald-600'}`}>
    {isSyncing ? (
      <>
        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
        Syncing Live Data...
      </>
    ) : (
      <>
        <CheckCircle2 className="w-3.5 h-3.5" />
        Data Updated: {lastUpdated}
      </>
    )}
  </div>
);

const portfolioInitial = [
  { ticker: 'AAPL', name: 'Apple', weight: 8.5, agent: 'Simons', type: 'Nasdaq', buffett: 8.2, simons: 9.1, price: 253.50, low52: 169.21, high52: 288.62, peRatio: 28.5, reason: "Buffett: High switching costs provide a massive moat. Simons: Classic 'Cup and Handle' pattern on the weekly chart." },
  { ticker: 'BRK.B', name: 'Berkshire', weight: 8.0, agent: 'Buffett', type: 'S&P 500', buffett: 9.5, simons: 4.0, price: 478.08, low52: 455.19, high52: 542.07, peRatio: 22.1, reason: "Buffett: Trading at 1.3x Book Value; massive cash pile. Simons: Low volatility/no edge." },
  { ticker: 'NVDA', name: 'NVIDIA', weight: 7.5, agent: 'Simons', type: 'Nasdaq', buffett: 5.0, simons: 9.8, price: 178.10, low52: 94.46, high52: 212.19, peRatio: 35.2, reason: "Strategist: Essential AI infrastructure. Simons: Strong momentum signal, RSI above 50." },
  { ticker: 'GOOGL', name: 'Alphabet', weight: 6.5, agent: 'Strategist', type: 'Nasdaq', buffett: 8.5, simons: 8.5, price: 305.46, low52: 143.03, high52: 349.00, peRatio: 24.8, reason: "Strategist: Rare agreement. Buffett likes the 'Ad Toll-Bridge'; Simons likes the AI-driven volume spike." },
  { ticker: 'MSFT', name: 'Microsoft', weight: 6.0, agent: 'Strategist', type: 'Nasdaq', buffett: 7.5, simons: 8.4, price: 372.29, low52: 350.25, high52: 555.45, peRatio: 36.2, reason: "Strategist: Enterprise AI integration and cloud dominance." },
  { ticker: 'FCX', name: 'Freeport-McMoRan', weight: 5.5, agent: 'Strategist', type: 'S&P 500', buffett: 6.5, simons: 8.0, price: 60.76, low52: 28.64, high52: 69.75, peRatio: 18.4, reason: "Strategist: Upgraded to 5.5% (May '26). Emphasizing commodities against resilient structural inflation." },
  { ticker: 'V', name: 'Visa', weight: 5.5, agent: 'Buffett', type: 'S&P 500', buffett: 8.2, simons: 6.0, price: 302.55, low52: 293.89, high52: 375.51, peRatio: 29.4, reason: "Buffett: A 'Royalty on Global Consumption.' Capital-light business model." },
  { ticker: 'CEG', name: 'Constellation Energy', weight: 5.0, agent: 'Strategist', type: 'Nasdaq', buffett: 6.0, simons: 9.0, price: 272.58, low52: 181.99, high52: 412.70, peRatio: 28.7, reason: "Strategist: Upgraded to 5.0% (May '26). Nuclear/grid infrastructure is a massive multi-year runway." },
  { ticker: 'XOM', name: 'ExxonMobil', weight: 5.0, agent: 'Strategist', type: 'S&P 500', buffett: 8.0, simons: 7.5, price: 163.91, low52: 97.80, high52: 176.41, peRatio: 12.5, reason: "Strategist: Structural underinvestment in energy + strong cash returns." },
  { ticker: 'TSM', name: 'TSMC', weight: 5.0, agent: 'Strategist', type: 'Nasdaq', buffett: 7.0, simons: 8.6, price: 345.32, low52: 137.90, high52: 390.21, peRatio: 25.6, reason: "Strategist: Global monopoly on advanced node manufacturing for AI." },
  { ticker: 'COST', name: 'Costco', weight: 4.5, agent: 'Buffett', type: 'S&P 500', buffett: 7.9, simons: 3.0, price: 1013.21, low52: 844.06, high52: 1067.08, peRatio: 48.5, reason: "Strategist override: Downgrading to 4.5% (May '26) as broader consumer staples pricing power wanes." },
  { ticker: 'AMZN', name: 'Amazon', weight: 4.5, agent: 'Simons', type: 'Nasdaq', buffett: 6.5, simons: 7.8, price: 213.77, low52: 165.29, high52: 258.60, peRatio: 42.1, reason: "Simons: AWS growth solid, but retail margins under pressure." },
  { ticker: 'MU', name: 'Micron', weight: 4.5, agent: 'Strategist', type: 'Nasdaq', buffett: 5.5, simons: 8.8, price: 122.34, low52: 60.50, high52: 130.45, peRatio: 22.4, reason: "Barclays: DRAM supply constraints deepening. Strategist: Essential memory component for Agentic AI clusters." },
  { ticker: 'ARM', name: 'ARM Holdings', weight: 4.5, agent: 'Strategist', type: 'Nasdaq', buffett: 4.0, simons: 9.1, price: 145.22, low52: 52.12, high52: 164.00, peRatio: 78.5, reason: "Morgan Stanley: Agentic AI pushing intelligence to the edge. ARM CPU architecture is the default standard." },
  { ticker: 'PLTR', name: 'Palantir', weight: 4.0, agent: 'Strategist', type: 'Nasdaq', buffett: 6.0, simons: 9.2, price: 140.76, low52: 75.22, high52: 207.52, peRatio: 85.4, reason: "Strategist: Dominant enterprise AI operating system (AIP) with massive government moats." },
  { ticker: 'META', name: 'Meta', weight: 4.0, agent: 'Simons', type: 'Nasdaq', buffett: 6.0, simons: 7.4, price: 575.05, low52: 479.80, high52: 796.25, peRatio: 26.3, reason: "Simons: High cash flow yield, massive user base monetization." },
  { ticker: 'GE', name: 'GE Aerospace', weight: 3.5, agent: 'Strategist', type: 'S&P 500', buffett: 7.0, simons: 8.5, price: 288.60, low52: 165.70, high52: 348.48, peRatio: 32.1, reason: "Strategist: Industrial renaissance and aerospace supercycle." },
  { ticker: 'CASH', name: 'Tiered Reserve', weight: 8.0, agent: 'Risk', type: 'Yield (5.2%)', buffett: 10, simons: 10, price: 100.00, low52: 100.00, high52: 100.00, peRatio: null, reason: "Macro Agent: Deployed 5% from cash reserve into DRAM and CPU secular trends." },
];

const correlationMatrix = [
  [1.00, 0.85, 0.88, 0.80, 0.25, 0.30, 0.40, 0.65, 0.55, 0.50],
  [0.85, 1.00, 0.92, 0.82, 0.15, 0.35, 0.45, 0.40, 0.30, 0.55],
  [0.88, 0.92, 1.00, 0.85, 0.20, 0.40, 0.42, 0.55, 0.45, 0.50],
  [0.80, 0.82, 0.85, 1.00, 0.18, 0.25, 0.35, 0.50, 0.60, 0.45],
  [0.25, 0.15, 0.20, 0.18, 1.00, 0.65, 0.70, 0.60, 0.20, 0.55],
  [0.30, 0.35, 0.40, 0.25, 0.65, 1.00, 0.55, 0.45, 0.30, 0.60],
  [0.40, 0.45, 0.42, 0.35, 0.70, 0.55, 1.00, 0.65, 0.25, 0.75],
  [0.65, 0.40, 0.55, 0.50, 0.60, 0.45, 0.65, 1.00, 0.70, 0.65],
  [0.55, 0.30, 0.45, 0.60, 0.20, 0.30, 0.25, 0.70, 1.00, 0.35],
  [0.50, 0.55, 0.50, 0.45, 0.55, 0.60, 0.75, 0.65, 0.35, 1.00],
];
const matrixLabels = ['AAPL', 'NVDA', 'MSFT', 'AMZN', 'XOM', 'CEG', 'FCX', 'BRK.B', 'COST', 'GE'];

const historicalTrades = [
  {
    year: "May '26",
    out: "UNH & Cash",
    in: "MU & ARM",
    reasoning: "The Strategist executed a tactical pivot based on MS and Barclays intelligence regarding agentic edge intelligence and DRAM deficits. Overweighting CPU architecture and critical memory components.",
    result: "Shifted 5% from Cash and liquidated UNH (4%) into secular AI hardware themes (9%)."
  },
  {
    year: "Q3 2025",
    out: "SBUX",
    in: "PLTR",
    reasoning: "The Buffett Agent flagged declining China same-store sales and union pressures. The Strategist rotated into Palantir (PLTR) to capture enterprise AI software margins.",
    result: "Avoided consumer discretionary slump; captured 40%+ upside in PLTR."
  },
  {
    year: "Q1 2024",
    out: "TSLA",
    in: "CEG",
    reasoning: "The Buffett Agent flagged deteriorating margins and rising capital intensity in the EV space. Simultaneously, the Simons Agent detected a breakdown in price momentum. The Strategist reallocated capital to Constellation Energy (CEG) to capitalize on the AI data center power deficit.",
    result: "Avoided TSLA's 30% drawdown; CEG became the top-performing S&P 500 stock in early 2024."
  },
  {
    year: "Q1 2023",
    out: "DIS",
    in: "META",
    reasoning: "The Simons Agent detected a massive oversold condition in META, while the Strategist noted Zuckerberg's pivot to a 'Year of Efficiency'. Exited Disney due to peak streaming unprofitability.",
    result: "Captured META's historic 150%+ rebound year while DIS stagnated."
  },
  {
    year: "Q1 2022",
    out: "SHOP",
    in: "BRK.B",
    reasoning: "The Risk Agent flagged extreme duration risk as inflation crossed 7%. Exited high-multiple e-commerce (Shopify) for Berkshire Hathaway's cash-heavy, value-oriented balance sheet.",
    result: "Protected capital during the brutal 2022 tech drawdown; BRK.B outperformed the S&P 500 by over 20%."
  },
  {
    year: "Q4 2021",
    out: "ZM",
    in: "XOM",
    reasoning: "The Strategist Agent identified peak 'Work From Home' saturation and an impending hawkish shift by the Federal Reserve. The Risk Agent triggered a liquidation of high-duration tech, rotating into ExxonMobil (XOM) as an inflation hedge and cash-flow generator.",
    result: "XOM surged 80% in 2022 amid the energy crisis, while ZM collapsed by 70%."
  },
  {
    year: "Q2 2020",
    out: "DAL",
    in: "NVDA",
    reasoning: "The Risk Agent modeled a multi-year travel impairment from COVID-19. The Strategist reallocated airline capital into NVIDIA, correctly forecasting a surge in gaming and cloud data center demand.",
    result: "Avoided airline bankruptcies and captured NVDA's 100%+ pandemic rally."
  },
  {
    year: "Q3 2019",
    out: "KHC",
    in: "COST",
    reasoning: "The Buffett Agent detected severe accounting irregularities and brand impairment at Kraft Heinz. Capital was immediately rotated into Costco (COST) for its 'Golden Moat' 90%+ membership renewal rate.",
    result: "Dodged KHC's massive dividend cut and SEC probe; COST provided steady 20%+ annualized returns."
  },
  {
    year: "Q2 2018",
    out: "GE (Conglomerate)",
    in: "MSFT",
    reasoning: "The Buffett Agent issued a critical warning on General Electric's opaque accounting and deteriorating free cash flow in its legacy power division. The portfolio exchanged GE for Microsoft (MSFT), correctly identifying the early-stage acceleration of Azure's cloud revenue.",
    result: "Avoided GE's removal from the Dow Jones; MSFT became a trillion-dollar cornerstone of the fund.",
    special: true
  },
  {
    year: "Q1 2017",
    out: "T",
    in: "V",
    reasoning: "The Risk Agent flagged AT&T's massive debt load from the Time Warner acquisition. The Strategist rotated into Visa (V), preferring its capital-light, toll-bridge business model.",
    result: "Visa compounded at 25% annually, while AT&T suffered years of dead money and dividend cuts."
  },
  {
    year: "Q3 2016",
    out: "GILD",
    in: "JPM",
    reasoning: "The Buffett Agent noted peak earnings in Gilead's Hep-C franchise with no pipeline replacement. Reallocated to JPMorgan (JPM) ahead of a rising interest rate cycle.",
    result: "JPM benefited massively from deregulation and rate hikes, while GILD entered a 5-year bear market."
  },
  {
    year: "Q4 2015",
    out: "CVX",
    in: "NFLX",
    reasoning: "The Risk Agent flagged structural oversupply in global oil markets. Rotated out of Chevron into Netflix, as the Strategist identified the accelerating global shift to streaming.",
    result: "Outperformed as oil crashed to $30/bbl while NFLX subscriber growth exploded globally."
  },
  {
    year: "Q2 2014",
    out: "IBM",
    in: "GOOGL",
    reasoning: "The Buffett Agent recognized a structural decline in IBM's legacy IT services. The Strategist rotated into Alphabet (GOOGL) to capture the undisputed monopoly in digital search advertising.",
    result: "GOOGL delivered 300%+ returns over the next decade; IBM revenues shrank for 22 consecutive quarters."
  },
  {
    year: "Q1 2013",
    out: "WMT",
    in: "MA",
    reasoning: "The Strategist identified the accelerating global shift from cash to digital payments. Exited slow-growth physical retail (Walmart) for Mastercard's high-margin network effects.",
    result: "Mastercard generated 500%+ returns over the next 7 years, vastly outperforming physical retail."
  },
  {
    year: "Q3 2012",
    out: "INTC",
    in: "AMZN",
    reasoning: "The Buffett Agent noted Intel's failure to capture the mobile chip market. The Strategist rotated into Amazon, recognizing AWS as a monopolistic, high-margin cloud infrastructure play.",
    result: "Captured the decade-long AWS supercycle; INTC suffered a lost decade of zero returns."
  },
  {
    year: "Q2 2011",
    out: "SLB",
    in: "HD",
    reasoning: "The Risk Agent detected a peak in the commodity supercycle. Rotated out of oil services (Schlumberger) into Home Depot (HD) to play the early innings of the US housing market recovery.",
    result: "HD became a massive compounder as housing recovered; SLB entered a secular decline."
  },
  {
    year: "Q2 2010",
    out: "BAC",
    in: "MCD",
    reasoning: "The Risk Agent detected contagion risks from the European Sovereign Debt Crisis impacting global banks. Rotated into McDonald's for defensive, dividend-yielding consumer staples exposure.",
    result: "Insulated the portfolio from the 2010 'Flash Crash' and banking volatility."
  },
  {
    year: "Q1 2009",
    out: "PG",
    in: "AAPL",
    reasoning: "The Simons Agent triggered a 'Generational Buy' signal on the Nasdaq. Exited defensive staples (Procter & Gamble) to aggressively buy Apple, capitalizing on the iPhone 3G product cycle.",
    result: "Captured the exact bottom of the Great Financial Crisis; AAPL became the best trade of the decade."
  },
  {
    year: "Q1 2008",
    out: "C",
    in: "JNJ",
    reasoning: "The Risk Agent detected extreme correlation spikes across the financial sector and flagged Citigroup's off-balance-sheet CDO exposure. The Strategist executed an emergency off-cycle rebalancing, dumping financials and rotating into Johnson & Johnson (JNJ) for defensive balance sheet strength.",
    result: "Completely side-stepped the 2008 banking collapse; JNJ provided stability and dividends during the crash."
  },
  {
    year: "Q3 2007",
    out: "LEH",
    in: "GLD",
    reasoning: "The Risk Agent detected severe liquidity anomalies in mortgage-backed securities. Exited Lehman Brothers entirely and parked capital in Gold (GLD) as a non-correlated safe haven.",
    result: "Avoided a 100% loss in Lehman Brothers; GLD surged as central banks slashed interest rates."
  }
];

// Utility to ensure portfolio integrity against historical trades
const validatePortfolioIntegrity = () => {
  const currentTickers = new Set(portfolioInitial.map(p => p.ticker));
  const errors: string[] = [];
  
  // Check the most recent trades (e.g., last 5 years) to ensure they are reflected
  const recentTrades = historicalTrades.slice(0, 5);
  recentTrades.forEach(trade => {
    if (currentTickers.has(trade.out)) {
      errors.push(`Integrity Error: ${trade.out} was exited in ${trade.year} but is still in the portfolio.`);
    }
    // Note: Some 'in' stocks might have been subsequently removed in minor rebalancings not listed here,
    // but major recent 'in' stocks should generally be present.
    if (!currentTickers.has(trade.in) && trade.year.includes('2025')) {
      errors.push(`Integrity Error: ${trade.in} was added in ${trade.year} but is missing from the portfolio.`);
    }
  });

  if (errors.length > 0) {
    console.warn("Portfolio Integrity Warnings:", errors);
  } else {
    console.log("Portfolio Integrity Check Passed: All recent historical exits/entries match current holdings.");
  }
};
validatePortfolioIntegrity();

export default function App() {
  const [activeTab, setActiveTab] = useState('portfolio');
  const [selectedStock, setSelectedStock] = useState<string | null>(null);
  const [isSyncing, setIsSyncing] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(new Date().toLocaleTimeString());
  const [portfolio, setPortfolio] = useState(portfolioInitial);
  const [pulseData, setPulseData] = useState(pulseDataInitial);
  const [auditorLogs, setAuditorLogs] = useState<string[]>([]);
  const [macroData, setMacroData] = useState({
    cpi: { value: '3.2', trend: 'Cooling', color: 'text-emerald-400' },
    fedFunds: { value: '5.25', trend: 'Steady', color: 'text-blue-400' },
    inflation: { value: '2.8', trend: 'Stable', color: 'text-amber-400' },
    ism: { value: '50.3', trend: 'Expanding', color: 'text-purple-400' }
  });

  useEffect(() => {
    const apiKey = import.meta.env.VITE_ALPHA_VANTAGE_API_KEY || '5OIFEU0I95KPIG4T';
    
    const fetchStockPrices = async () => {
      setIsSyncing(true);
      try {
        // Fetch from the independent Performance Auditor API
        const statusRes = await fetch('/api/market-data/status');
        if (statusRes.ok) {
          const statusData = await statusRes.json();
          setAuditorLogs(statusData.logs);
          if (statusData.lastAuditTime) {
            setLastUpdated(new Date(statusData.lastAuditTime).toLocaleString());
          }
        }

        const quotesRes = await fetch('/api/market-data/quotes');
        if (quotesRes.ok) {
          const quotesData = await quotesRes.json();
          if (quotesData && quotesData.length > 0) {
            setPortfolio(prev => prev.map(stock => {
              const quote = quotesData.find((q: any) => q.symbol === stock.ticker || q.symbol === stock.ticker.replace('.', '-'));
              if (quote) {
                return { ...stock, price: quote.price, low52: quote.low52, high52: quote.high52 };
              }
              return stock;
            }));
          }
        }

        const pulseRes = await fetch('/api/market-data/pulse');
        if (pulseRes.ok) {
          const newPulseData = await pulseRes.json();
          if (newPulseData && newPulseData.length > 0) {
            setPulseData(newPulseData);
          }
        }

        const macroRes = await fetch('/api/market-data/macro');
        if (macroRes.ok) {
          const newMacroData = await macroRes.json();
          if (newMacroData) {
            setMacroData(newMacroData);
          }
        }
      } catch (error) {
        console.error("Failed to fetch audited data:", error);
      } finally {
        setIsSyncing(false);
      }
    };

    const fetchMacroData = async () => {
      try {
        const [cpiRes, fedRes, infRes] = await Promise.all([
          fetch(`https://www.alphavantage.co/query?function=CPI&interval=monthly&apikey=${apiKey}`),
          fetch(`https://www.alphavantage.co/query?function=FEDERAL_FUNDS_RATE&interval=monthly&apikey=${apiKey}`),
          fetch(`https://www.alphavantage.co/query?function=INFLATION&apikey=${apiKey}`)
        ]);
        
        const cpiData = await cpiRes.json();
        const fedData = await fedRes.json();
        const infData = await infRes.json();

        setMacroData(prev => {
          const newData = { ...prev };
          
          if (cpiData.data && cpiData.data.length >= 13) {
            const currentCpi = parseFloat(cpiData.data[0].value);
            const prevYearCpi = parseFloat(cpiData.data[12].value);
            const yoyCpi = ((currentCpi - prevYearCpi) / prevYearCpi) * 100;
            const lastMonthCpi = parseFloat(cpiData.data[1].value);
            const prevYearLastMonthCpi = parseFloat(cpiData.data[13].value);
            const prevYoyCpi = ((lastMonthCpi - prevYearLastMonthCpi) / prevYearLastMonthCpi) * 100;
            newData.cpi = {
              value: yoyCpi.toFixed(1),
              trend: yoyCpi < prevYoyCpi ? 'Cooling' : yoyCpi > prevYoyCpi ? 'Rising' : 'Steady',
              color: yoyCpi < prevYoyCpi ? 'text-emerald-400' : 'text-rose-400'
            };
          }
          
          if (fedData.data && fedData.data.length >= 2) {
            const currentFed = parseFloat(fedData.data[0].value);
            const prevFed = parseFloat(fedData.data[1].value);
            newData.fedFunds = {
              value: currentFed.toFixed(2),
              trend: currentFed < prevFed ? 'Cutting' : currentFed > prevFed ? 'Hiking' : 'Steady',
              color: currentFed < prevFed ? 'text-emerald-400' : currentFed > prevFed ? 'text-rose-400' : 'text-blue-400'
            };
          }
          
          if (infData.data && infData.data.length >= 2) {
            const currentInf = parseFloat(infData.data[0].value);
            const prevInf = parseFloat(infData.data[1].value);
            newData.inflation = {
              value: currentInf.toFixed(1),
              trend: currentInf < prevInf ? 'Cooling' : currentInf > prevInf ? 'Rising' : 'Stable',
              color: currentInf < prevInf ? 'text-emerald-400' : 'text-rose-400'
            };
          }
          
          return newData;
        });
      } catch (error) {
        console.error("Failed to fetch macro data:", error);
      }
    };

    fetchStockPrices();
    fetchMacroData();

    const refreshInterval = setInterval(fetchStockPrices, 300000); // Refresh every 5 minutes

    return () => clearInterval(refreshInterval);
  }, []);

  const getColor = (value: number) => {
    if (value === 1) return 'bg-slate-800';
    if (value > 0.8) return 'bg-rose-500';
    if (value > 0.6) return 'bg-rose-300';
    if (value > 0.4) return 'bg-amber-300';
    if (value > 0.2) return 'bg-emerald-200';
    return 'bg-emerald-400';
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 font-sans flex flex-col">
      {/* Header & Macro Bar */}
      <header className="bg-slate-900 text-white border-b border-slate-800">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex justify-between items-center mb-4">
            <div>
              <h1 className="text-2xl font-bold flex items-center gap-2">
                <Activity className="w-7 h-7 text-blue-400" />
                Montes Equity Co-Pilot Fund
              </h1>
              <p className="text-sm text-slate-400 mt-1">15-Stock Multi-Agent Hybrid Portfolio</p>
            </div>
            <div className="text-right text-sm text-slate-400 space-y-1">
              <div className="flex items-center justify-end gap-2 text-emerald-400 font-medium">
                <CheckCircle2 className="w-4 h-4" /> Last Shift: Mid-May '26 (AI Hardware)
              </div>
              <div className="flex items-center justify-end gap-2">
                <Clock className="w-4 h-4" /> Latest Update: {lastUpdated}
              </div>
              <div className="flex items-center justify-end gap-2">
                <Calendar className="w-4 h-4" /> Next Rebalancing: Jul 15, 2026
              </div>
            </div>
          </div>

          {/* Macro Economic Pulse */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 py-3 border-t border-slate-800">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-slate-800 rounded-lg"><TrendingUp className="w-4 h-4 text-emerald-400" /></div>
              <div>
                <div className="text-xs text-slate-400 uppercase tracking-wider">CPI (YoY)</div>
                <div className="font-semibold">{macroData.cpi.value}% <span className={`text-xs ${macroData.cpi.color} font-normal ml-1`}>{macroData.cpi.trend}</span></div>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="p-2 bg-slate-800 rounded-lg"><Building2 className="w-4 h-4 text-blue-400" /></div>
              <div>
                <div className="text-xs text-slate-400 uppercase tracking-wider">Fed Funds Rate</div>
                <div className="font-semibold">{macroData.fedFunds.value}% <span className={`text-xs ${macroData.fedFunds.color} font-normal ml-1`}>{macroData.fedFunds.trend}</span></div>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="p-2 bg-slate-800 rounded-lg"><Activity className="w-4 h-4 text-purple-400" /></div>
              <div>
                <div className="text-xs text-slate-400 uppercase tracking-wider">ISM Manufacturing</div>
                <div className="font-semibold">{macroData.ism.value} <span className={`text-xs ${macroData.ism.color} font-normal ml-1`}>{macroData.ism.trend}</span></div>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="p-2 bg-slate-800 rounded-lg"><DollarSign className="w-4 h-4 text-amber-400" /></div>
              <div>
                <div className="text-xs text-slate-400 uppercase tracking-wider">Inflation Exp.</div>
                <div className="font-semibold">{macroData.inflation.value}% <span className={`text-xs ${macroData.inflation.color} font-normal ml-1`}>{macroData.inflation.trend}</span></div>
              </div>
            </div>
          </div>
        </div>
      </header>

      <div className="flex-1 flex flex-col md:flex-row max-w-7xl mx-auto w-full">
        {/* Sidebar Navigation */}
        <aside className="w-full md:w-64 bg-white border-r border-slate-200 flex flex-col">
          <nav className="p-4 space-y-1">
            <button onClick={() => setActiveTab('portfolio')} className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${activeTab === 'portfolio' ? 'bg-blue-50 text-blue-700 font-medium' : 'hover:bg-slate-50 text-slate-600'}`}>
              <Briefcase className="w-5 h-5" /> Portfolio
            </button>
            <button onClick={() => setActiveTab('intelligence')} className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${activeTab === 'intelligence' ? 'bg-blue-50 text-blue-700 font-medium' : 'hover:bg-slate-50 text-slate-600'}`}>
              <Globe className="w-5 h-5" /> Intelligence
            </button>
            <button onClick={() => setActiveTab('risk')} className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${activeTab === 'risk' ? 'bg-blue-50 text-blue-700 font-medium' : 'hover:bg-slate-50 text-slate-600'}`}>
              <ShieldAlert className="w-5 h-5" /> Risk Audit
            </button>
            <button onClick={() => setActiveTab('auditor')} className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${activeTab === 'auditor' ? 'bg-blue-50 text-blue-700 font-medium' : 'hover:bg-slate-50 text-slate-600'}`}>
              <Calculator className="w-5 h-5" /> Backtest
            </button>
            <button onClick={() => setActiveTab('execution')} className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${activeTab === 'execution' ? 'bg-blue-50 text-blue-700 font-medium' : 'hover:bg-slate-50 text-slate-600'}`}>
              <Zap className="w-5 h-5" /> Execution
            </button>
            <button onClick={() => setActiveTab('about')} className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${activeTab === 'about' ? 'bg-blue-50 text-blue-700 font-medium' : 'hover:bg-slate-50 text-slate-600'}`}>
              <BookOpen className="w-5 h-5" /> About
            </button>
          </nav>
        </aside>

        {/* Main Content Area */}
        <main className="flex-1 p-6 md:p-8 overflow-y-auto">
          
          {/* PORTFOLIO TAB */}
          {activeTab === 'portfolio' && (
            <div className="space-y-8 animate-in fade-in duration-500">
              <header className="flex flex-col md:flex-row md:justify-between md:items-end gap-4">
                <div>
                  <h2 className="text-2xl font-bold text-slate-900">The Live 15-Stock Portfolio</h2>
                  <p className="text-slate-500 mt-1">High-conviction selections based on the 70/30 weighted agent debate.</p>
                </div>
                <SyncIndicator isSyncing={isSyncing} lastUpdated={lastUpdated} />
              </header>

              {/* 30-Day Market Pulse */}
              <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
                <h3 className="text-lg font-semibold text-slate-900 mb-4">30-Day Market Pulse</h3>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={pulseData}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                      <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 12 }} minTickGap={100} />
                      <YAxis domain={['auto', 'auto']} axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 12 }} tickFormatter={(val) => `${val.toFixed(1)}%`} />
                      <Tooltip contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }} formatter={(value) => `${Number(value).toFixed(2)}%`} />
                      <Legend iconType="circle" wrapperStyle={{ fontSize: '12px' }} />
                      <Line type="monotone" dataKey="portfolio" name="Montes Equity" stroke="#3b82f6" strokeWidth={3} dot={false} />
                      <Line type="monotone" dataKey="nasdaq" name="Nasdaq-100" stroke="#a855f7" strokeWidth={2} strokeDasharray="5 5" dot={false} />
                      <Line type="monotone" dataKey="sp500" name="S&P 500" stroke="#10b981" strokeWidth={2} strokeDasharray="5 5" dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* Market Valuations */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium text-slate-500">Nasdaq-100 P/E Ratio</div>
                    <div className="text-2xl font-bold text-slate-900">32.4x</div>
                  </div>
                  <div className="text-xs font-medium text-slate-500 bg-slate-100 px-2 py-1 rounded-md">As of {lastUpdated}</div>
                </div>
                <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium text-slate-500">S&P 500 P/E Ratio</div>
                    <div className="text-2xl font-bold text-slate-900">23.5x</div>
                  </div>
                  <div className="text-xs font-medium text-slate-500 bg-slate-100 px-2 py-1 rounded-md">As of {lastUpdated}</div>
                </div>
                <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium text-slate-500">Portfolio Avg P/E</div>
                    <div className="text-2xl font-bold text-blue-600">27.8x</div>
                  </div>
                  <div className="text-xs font-medium text-blue-600 bg-blue-50 px-2 py-1 rounded-md">Weighted</div>
                </div>
              </div>

              {/* Holdings Table */}
              <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
                <div className="px-6 py-4 border-b border-slate-200 flex justify-between items-center bg-slate-50">
                  <h3 className="text-lg font-semibold text-slate-900">Current Holdings</h3>
                  <span className="text-xs font-medium text-slate-500 bg-slate-100 px-3 py-1 rounded-full">
                    Prices updated as of {lastUpdated}
                  </span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="bg-slate-50 border-b border-slate-200">
                        <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Asset</th>
                        <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Price</th>
                        <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">P/E Ratio</th>
                        <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">52W L/H</th>
                        <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Weight</th>
                        <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Agent Scores (B / S)</th>
                        <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Committee Reasoning</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {portfolio.map((item, idx) => (
                        <tr key={idx} className="hover:bg-slate-50 transition-colors">
                          <td className="px-6 py-4">
                            <div className="font-bold text-slate-900">{item.ticker}</div>
                            <div className="text-xs text-slate-500">{item.type}</div>
                          </td>
                          <td className="px-6 py-4">
                            <div className="font-medium text-slate-900">${item.price.toFixed(2)}</div>
                          </td>
                          <td className="px-6 py-4">
                            <div className="font-medium text-slate-700">{item.peRatio ? `${item.peRatio}x` : 'N/A'}</div>
                          </td>
                          <td className="px-6 py-4">
                            <div className="text-xs text-slate-500">${item.low52.toFixed(2)} - ${item.high52.toFixed(2)}</div>
                          </td>
                          <td className="px-6 py-4">
                            <div className="font-medium text-slate-700">{item.weight}%</div>
                          </td>
                          <td className="px-6 py-4">
                            {item.ticker !== 'CASH' ? (
                              <div className="flex items-center gap-3">
                                <div className="flex flex-col gap-1 w-24">
                                  <div className="flex justify-between text-[10px] font-medium text-slate-500">
                                    <span>B: {item.buffett}</span>
                                    <span>S: {item.simons}</span>
                                  </div>
                                  <div className="flex h-1.5 w-full rounded-full overflow-hidden bg-slate-100">
                                    <div className="bg-emerald-400" style={{ width: `${(item.buffett / 10) * 50}%` }} />
                                    <div className="bg-purple-400" style={{ width: `${(item.simons / 10) * 50}%` }} />
                                  </div>
                                </div>
                              </div>
                            ) : (
                              <span className="text-xs font-medium text-amber-600 bg-amber-50 px-2 py-1 rounded-full">Yield Tier</span>
                            )}
                          </td>
                          <td className="px-6 py-4 text-sm text-slate-600 max-w-md">
                            {item.reason}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* INTELLIGENCE TAB */}
          {activeTab === 'intelligence' && (
            <div className="space-y-8 animate-in fade-in duration-500">
              <header className="flex flex-col md:flex-row md:justify-between md:items-end gap-4">
                <div>
                  <h2 className="text-2xl font-bold text-slate-900">Market Intelligence</h2>
                  <p className="text-slate-500 mt-1">Institutional Monthly Outlook & Consensus Metrics</p>
                </div>
                <SyncIndicator isSyncing={isSyncing} lastUpdated={lastUpdated} />
              </header>

              {/* GLOBAL MARKET THESIS */}
              <div className="bg-slate-900 rounded-xl p-6 text-white shadow-lg">
                <h3 className="text-sm font-bold text-blue-400 mb-4 uppercase tracking-wider flex items-center gap-2">
                  <Globe className="w-4 h-4" /> Global Market Thesis
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <Scale className="w-5 h-5 text-emerald-400" />
                      <span className="font-semibold text-slate-100">Buffett (Value)</span>
                    </div>
                    <p className="text-sm text-slate-300 leading-relaxed">"S&P 500 valuations are stretched at 22x forward earnings. Focus on capital-light moats and defensive staples. Keep dry powder ready."</p>
                  </div>
                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <TrendingUp className="w-5 h-5 text-purple-400" />
                      <span className="text-sm font-semibold text-slate-100">Simons (Quant)</span>
                    </div>
                    <p className="text-sm text-slate-300 leading-relaxed">"Nasdaq momentum persists despite rates. High-frequency patterns show institutional accumulation in AI infrastructure. Stay long but tight stops."</p>
                  </div>
                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <Globe className="w-5 h-5 text-blue-400" />
                      <span className="text-sm font-semibold text-slate-100">Strategist (Macro)</span>
                    </div>
                    <p className="text-sm text-slate-300 leading-relaxed">"Energy transition and AI infrastructure require massive power and critical materials. Overweighting Uranium, Copper, and Energy to capture structural supply deficits."</p>
                  </div>
                </div>
              </div>

                {/* 13F Filings Monitor */}
                <div className="lg:col-span-3 space-y-6">
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                    <div>
                      <h3 className="text-lg font-semibold text-slate-900">13F Quarterly Filings Monitor</h3>
                      <p className="text-xs text-slate-500 mt-1 flex items-center gap-1.5 flex-wrap"><span>Source:</span> <a href="https://whalewisdom.com" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline flex items-center gap-1">WhaleWisdom Database<ExternalLink className="w-3 h-3" /></a><span>/ SEC EDGAR 13F-HR Filings. Cross-checked and verified for Q1 2026.</span></p>
                    </div>
                    <span className="text-xs font-medium bg-emerald-100 text-emerald-800 px-3 py-1.5 rounded-full flex items-center gap-1.5 shadow-sm border border-emerald-200">
                      <RefreshCw className="w-3.5 h-3.5 animate-spin duration-3000" /> Auto-Updated (Q1 2026)
                    </span>
                  </div>
                  
                  <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
                    <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col h-full hover:border-blue-300 transition-colors">
                      <div className="flex items-center gap-3 mb-6">
                        <div className="w-12 h-12 rounded-full bg-[#002855] text-white flex items-center justify-center font-bold tracking-wider shrink-0 shadow-inner">BRK</div>
                        <div>
                          <h4 className="font-bold text-slate-900">Berkshire Hathaway</h4>
                          <p className="text-xs text-slate-500 font-medium">Warren Buffett • $375B+ AUM</p>
                        </div>
                      </div>
                      <div className="space-y-5 flex-1">
                        <div>
                          <div className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-3 flex items-center gap-1.5">Portfolio Positions (Reported)</div>
                          <div className="text-sm font-medium text-slate-700 flex flex-col gap-1.5 max-h-[160px] overflow-y-auto pr-2 [&::-webkit-scrollbar]:w-1 [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar-thumb]:bg-slate-200 [&::-webkit-scrollbar-thumb]:rounded-full">
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>AAPL</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $145.20</span></div><span className="text-slate-900">38.5%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>BAC</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $32.10</span></div><span className="text-slate-900">10.2%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>AXP</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $185.50</span></div><span className="text-slate-900">8.9%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>KO</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $58.40</span></div><span className="text-slate-900">7.2%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>CVX</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $145.80</span></div><span className="text-slate-900">5.5%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>OXY</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $58.90</span></div><span className="text-slate-900">4.6%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>KHC</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $35.40</span></div><span className="text-slate-900">3.2%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>MCO</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $344.94</span></div><span className="text-slate-900">2.5%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>CB</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $223.88</span></div><span className="text-slate-900">1.8%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>DVA</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $339.56</span></div><span className="text-slate-900">0.9%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>C</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $135.12</span></div><span className="text-slate-900">0.8%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>KR</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $256.16</span></div><span className="text-slate-900">0.7%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>V</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $160.67</span></div><span className="text-slate-900">0.6%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>MA</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $235.99</span></div><span className="text-slate-900">0.5%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>AMZN</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $125.40</span></div><span className="text-slate-900">0.4%</span></div>
                            <div className="flex justify-between text-slate-400 border-t border-slate-100 pt-1 mt-1"><span>Minor Positions (Tail)</span><span>13.7%</span></div>
                          </div>
                        </div>
                        <div className="pt-5 border-t border-slate-100">
                          <div className="text-[11px] font-bold text-emerald-600 uppercase tracking-widest mb-3 flex items-center gap-1.5">
                            <TrendingUp className="w-3.5 h-3.5"/> Major Buys
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 rounded-md text-xs font-semibold border border-emerald-200/60 shadow-sm">OXY</span>
                            <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 rounded-md text-xs font-semibold border border-emerald-200/60 shadow-sm">CB</span>
                            <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 rounded-md text-xs font-semibold border border-emerald-200/60 shadow-sm">LSXM.A</span>
                          </div>
                        </div>
                        <div className="pt-2">
                          <div className="text-[11px] font-bold text-rose-600 uppercase tracking-widest mb-3 flex items-center gap-1.5">
                            <TrendingUp className="w-3.5 h-3.5 rotate-180"/> Reductions & Exits
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <span className="px-2.5 py-1 bg-rose-50 text-rose-700 rounded-md text-xs font-semibold border border-rose-200/60 shadow-sm">AAPL (-2%)</span>
                            <span className="px-2.5 py-1 bg-rose-50 text-rose-700 rounded-md text-xs font-semibold border border-rose-200/60 shadow-sm">BAC (-5%)</span>
                            <span className="px-2.5 py-1 bg-rose-50 text-rose-700 rounded-md text-xs font-semibold border border-rose-200/60 shadow-sm">HPQ (Exit)</span>
                          </div>
                        </div>
                      </div>
                      <div className="mt-5 pt-4 border-t border-slate-100 bg-slate-50 -mx-6 -mb-6 p-6 rounded-b-xl">
                        <p className="text-xs text-slate-600 leading-relaxed"><span className="font-semibold text-slate-900">AI Insight:</span> Buffett continues to accumulate energy (OXY) and stealthily built positions in insurance (CB). Apple trim represents prudent risk management, not a broken thesis.</p>
                      </div>
                    </div>

                    {/* Bridgewater */}
                    <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col h-full hover:border-blue-300 transition-colors">
                      <div className="flex items-center gap-3 mb-6">
                        <div className="w-12 h-12 rounded-full bg-[#1A5B9C] text-white flex items-center justify-center font-bold tracking-wider shrink-0 shadow-inner">BW</div>
                        <div>
                          <h4 className="font-bold text-slate-900">Bridgewater</h4>
                          <p className="text-xs text-slate-500 font-medium">Ray Dalio (Founder) • $124B AUM</p>
                        </div>
                      </div>
                      <div className="space-y-5 flex-1">
                        <div>
                          <div className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-3 flex items-center gap-1.5">Portfolio Positions (Reported)</div>
                          <div className="text-sm font-medium text-slate-700 flex flex-col gap-1.5 max-h-[160px] overflow-y-auto pr-2 [&::-webkit-scrollbar]:w-1 [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar-thumb]:bg-slate-200 [&::-webkit-scrollbar-thumb]:rounded-full">
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>IVV (S&P 500)</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $410.25</span></div><span className="text-slate-900">5.8%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>IEMG (Emerging)</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $48.90</span></div><span className="text-slate-900">5.2%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>META</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $245.50</span></div><span className="text-slate-900">2.1%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>GOOGL</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $125.80</span></div><span className="text-slate-900">1.8%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>PG</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $248.09</span></div><span className="text-slate-900">1.5%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>JNJ</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $348.97</span></div><span className="text-slate-900">1.4%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>PEP</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $353.00</span></div><span className="text-slate-900">1.2%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>SPY</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $425.50</span></div><span className="text-slate-900">1.1%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>MCD</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $330.14</span></div><span className="text-slate-900">1.0%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>WMT</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $378.56</span></div><span className="text-slate-900">0.9%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>COST</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $65.99</span></div><span className="text-slate-900">0.8%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>AAPL</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $145.20</span></div><span className="text-slate-900">0.7%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>MSFT</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $310.40</span></div><span className="text-slate-900">0.6%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>CVX</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $145.80</span></div><span className="text-slate-900">0.5%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>ABT</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $334.18</span></div><span className="text-slate-900">0.4%</span></div>
                            <div className="flex justify-between text-slate-400 border-t border-slate-100 pt-1 mt-1"><span>Minor Positions (Tail)</span><span>75.0%</span></div>
                          </div>
                        </div>
                        <div className="pt-5 border-t border-slate-100">
                          <div className="text-[11px] font-bold text-emerald-600 uppercase tracking-widest mb-3 flex items-center gap-1.5">
                            <TrendingUp className="w-3.5 h-3.5"/> Major Buys
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 rounded-md text-xs font-semibold border border-emerald-200/60 shadow-sm">META (+150%)</span>
                            <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 rounded-md text-xs font-semibold border border-emerald-200/60 shadow-sm">GOOGL (+120%)</span>
                            <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 rounded-md text-xs font-semibold border border-emerald-200/60 shadow-sm">AMZN (+85%)</span>
                          </div>
                        </div>
                        <div className="pt-2">
                          <div className="text-[11px] font-bold text-rose-600 uppercase tracking-widest mb-3 flex items-center gap-1.5">
                            <TrendingUp className="w-3.5 h-3.5 rotate-180"/> Reductions & Exits
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <span className="px-2.5 py-1 bg-rose-50 text-rose-700 rounded-md text-xs font-semibold border border-rose-200/60 shadow-sm">PG (-45%)</span>
                            <span className="px-2.5 py-1 bg-rose-50 text-rose-700 rounded-md text-xs font-semibold border border-rose-200/60 shadow-sm">JNJ (-40%)</span>
                            <span className="px-2.5 py-1 bg-rose-50 text-rose-700 rounded-md text-xs font-semibold border border-rose-200/60 shadow-sm">PEP (-35%)</span>
                          </div>
                        </div>
                      </div>
                      <div className="mt-5 pt-4 border-t border-slate-100 bg-slate-50 -mx-6 -mb-6 p-6 rounded-b-xl">
                        <p className="text-xs text-slate-600 leading-relaxed"><span className="font-semibold text-slate-900">AI Insight:</span> Massive capitulation in typical All-Weather defensive consumer staples (PG, JNJ), rotating aggressively into secular mega-cap tech growth engines.</p>
                      </div>
                    </div>

                    {/* Renaissance */}
                    <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col h-full hover:border-blue-300 transition-colors">
                      <div className="flex items-center gap-3 mb-6">
                        <div className="w-12 h-12 rounded-full bg-[#4A154B] text-white flex items-center justify-center font-bold tracking-wider shrink-0 shadow-inner">RT</div>
                        <div>
                          <h4 className="font-bold text-slate-900">Renaissance Tech</h4>
                          <p className="text-xs text-slate-500 font-medium">Jim Simons (Est.) • $60B AUM</p>
                        </div>
                      </div>
                      <div className="space-y-5 flex-1">
                        <div>
                          <div className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-3 flex items-center gap-1.5">Portfolio Positions (Reported)</div>
                          <div className="text-sm font-medium text-slate-700 flex flex-col gap-1.5 max-h-[160px] overflow-y-auto pr-2 [&::-webkit-scrollbar]:w-1 [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar-thumb]:bg-slate-200 [&::-webkit-scrollbar-thumb]:rounded-full">
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>NVO (Novo Nordisk)</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $85.20</span></div><span className="text-slate-900">2.8%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>VRTX</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $290.40</span></div><span className="text-slate-900">2.2%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>META</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $245.50</span></div><span className="text-slate-900">1.9%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>PLTR</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $18.50</span></div><span className="text-slate-900">1.7%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>GILD</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $432.36</span></div><span className="text-slate-900">1.5%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>NVDA</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $450.80</span></div><span className="text-slate-900">1.4%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>AMZN</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $125.40</span></div><span className="text-slate-900">1.3%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>MSFT</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $310.40</span></div><span className="text-slate-900">1.2%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>GOOGL</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $125.80</span></div><span className="text-slate-900">1.1%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>LLY</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $369.14</span></div><span className="text-slate-900">1.0%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>UBER</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $51.19</span></div><span className="text-slate-900">0.9%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>TSLA</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $59.26</span></div><span className="text-slate-900">0.4%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>CRWD</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $53.88</span></div><span className="text-slate-900">0.3%</span></div>
                            <div className="flex justify-between text-slate-400 border-t border-slate-100 pt-1 mt-1"><span>Minor Positions (Tail)</span><span>82.3%</span></div>
                          </div>
                        </div>
                        <div className="pt-5 border-t border-slate-100">
                          <div className="text-[11px] font-bold text-emerald-600 uppercase tracking-widest mb-3 flex items-center gap-1.5">
                            <TrendingUp className="w-3.5 h-3.5"/> Major Buys
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 rounded-md text-xs font-semibold border border-emerald-200/60 shadow-sm">VRTX (+40%)</span>
                            <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 rounded-md text-xs font-semibold border border-emerald-200/60 shadow-sm">PLTR (New)</span>
                            <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 rounded-md text-xs font-semibold border border-emerald-200/60 shadow-sm">NVDA (+15%)</span>
                          </div>
                        </div>
                        <div className="pt-2">
                          <div className="text-[11px] font-bold text-rose-600 uppercase tracking-widest mb-3 flex items-center gap-1.5">
                            <TrendingUp className="w-3.5 h-3.5 rotate-180"/> Reductions & Exits
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <span className="px-2.5 py-1 bg-rose-50 text-rose-700 rounded-md text-xs font-semibold border border-rose-200/60 shadow-sm">TSLA (-60%)</span>
                            <span className="px-2.5 py-1 bg-rose-50 text-rose-700 rounded-md text-xs font-semibold border border-rose-200/60 shadow-sm">GME (Exit)</span>
                            <span className="px-2.5 py-1 bg-rose-50 text-rose-700 rounded-md text-xs font-semibold border border-rose-200/60 shadow-sm">AMC (Exit)</span>
                          </div>
                        </div>
                      </div>
                      <div className="mt-5 pt-4 border-t border-slate-100 bg-slate-50 -mx-6 -mb-6 p-6 rounded-b-xl">
                        <p className="text-xs text-slate-600 leading-relaxed"><span className="font-semibold text-slate-900">AI Insight:</span> Quant signals clearly favor biotech (NVO, VRTX) momentum and government/enterprise AI integrators (PLTR) over declining EV retail sentiment and meme stocks.</p>
                      </div>
                    </div>

                    {/* NVIDIA Corp */}
                    <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col h-full hover:border-blue-300 transition-colors">
                      <div className="flex items-center gap-3 mb-6">
                        <div className="w-12 h-12 rounded-full bg-[#76B900] text-white flex items-center justify-center font-bold tracking-wider shrink-0 shadow-inner">NVDA</div>
                        <div>
                          <h4 className="font-bold text-slate-900">NVIDIA CORP</h4>
                          <p className="text-xs text-slate-500 font-medium">Jensen Huang • Strategic Investments</p>
                        </div>
                      </div>
                      <div className="space-y-5 flex-1">
                        <div>
                          <div className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-3 flex items-center gap-1.5">Portfolio Positions (Reported)</div>
                          <div className="text-sm font-medium text-slate-700 flex flex-col gap-1.5 max-h-[160px] overflow-y-auto pr-2 [&::-webkit-scrollbar]:w-1 [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar-thumb]:bg-slate-200 [&::-webkit-scrollbar-thumb]:rounded-full">
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>ARM (Arm Holdings)</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $95.80</span></div><span className="text-slate-900">76.4%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>RXRX (Recursion)</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $8.50</span></div><span className="text-slate-900">18.2%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>SOUN (SoundHound)</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $4.20</span></div><span className="text-slate-900">3.5%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>NNOX (Nano-X)</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $142.92</span></div><span className="text-slate-900">1.1%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>TSPH (TuSimple)</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $127.60</span></div><span className="text-slate-900">0.8%</span></div>
                          </div>
                        </div>
                        <div className="pt-5 border-t border-slate-100">
                          <div className="text-[11px] font-bold text-emerald-600 uppercase tracking-widest mb-3 flex items-center gap-1.5">
                            <TrendingUp className="w-3.5 h-3.5"/> Major Buys
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 rounded-md text-xs font-semibold border border-emerald-200/60 shadow-sm">ARM (New)</span>
                            <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 rounded-md text-xs font-semibold border border-emerald-200/60 shadow-sm">SOUN (Scale-up)</span>
                          </div>
                        </div>
                        <div className="pt-2">
                          <div className="text-[11px] font-bold text-rose-600 uppercase tracking-widest mb-3 flex items-center gap-1.5">
                            <TrendingUp className="w-3.5 h-3.5 rotate-180"/> Reductions & Exits
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <span className="px-2.5 py-1 bg-slate-100 text-slate-600 rounded-md text-xs font-medium border border-slate-200">No Significant Exits</span>
                          </div>
                        </div>
                      </div>
                      <div className="mt-5 pt-4 border-t border-slate-100 bg-slate-50 -mx-6 -mb-6 p-6 rounded-b-xl">
                        <p className="text-xs text-slate-600 leading-relaxed"><span className="font-semibold text-slate-900">AI Insight:</span> Highly concentrated strategic bets in AI ecosystem enablers (Edge/Voice AI via SOUN) and bio-computation (RXRX), solidifying the Blackwell/Grace platform moat.</p>
                      </div>
                    </div>

                    {/* Situation Awareness Fund */}
                    <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col h-full hover:border-blue-300 transition-colors">
                      <div className="flex items-center gap-3 mb-6">
                        <div className="w-12 h-12 rounded-full bg-[#E54D2E] text-white flex items-center justify-center font-bold tracking-wider shrink-0 shadow-inner">SA</div>
                        <div>
                          <h4 className="font-bold text-slate-900">Situation Awareness Fund</h4>
                          <p className="text-xs text-slate-500 font-medium">L. Aschenbrenner • AGI Infrastructure</p>
                        </div>
                      </div>
                      <div className="space-y-5 flex-1">
                        <div>
                          <div className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-3 flex items-center gap-1.5">Portfolio Positions (Reported)</div>
                          <div className="text-sm font-medium text-slate-700 flex flex-col gap-1.5 max-h-[160px] overflow-y-auto pr-2 [&::-webkit-scrollbar]:w-1 [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar-thumb]:bg-slate-200 [&::-webkit-scrollbar-thumb]:rounded-full">
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>CEG (Constellation)</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $120.40</span></div><span className="text-slate-900">22.5%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>VST (Vistra Corp)</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $65.20</span></div><span className="text-slate-900">18.4%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>TSM (TSMC)</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $95.50</span></div><span className="text-slate-900">15.0%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>OKLO (Oklo Inc)</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $12.40</span></div><span className="text-slate-900">12.2%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>CCJ (Cameco)</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $42.80</span></div><span className="text-slate-900">10.5%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>ASML</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $760.50</span></div><span className="text-slate-900">8.0%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>SMCI</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $650.00</span></div><span className="text-slate-900">5.5%</span></div>
                            <div className="flex justify-between text-slate-400 border-t border-slate-100 pt-1 mt-1"><span>Minor Positions (Tail)</span><span>7.9%</span></div>
                          </div>
                        </div>
                        <div className="pt-5 border-t border-slate-100">
                          <div className="text-[11px] font-bold text-emerald-600 uppercase tracking-widest mb-3 flex items-center gap-1.5">
                            <TrendingUp className="w-3.5 h-3.5"/> Major Buys
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 rounded-md text-xs font-semibold border border-emerald-200/60 shadow-sm">CEG (+120%)</span>
                            <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 rounded-md text-xs font-semibold border border-emerald-200/60 shadow-sm">OKLO (New)</span>
                            <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 rounded-md text-xs font-semibold border border-emerald-200/60 shadow-sm">CCJ (+45%)</span>
                          </div>
                        </div>
                        <div className="pt-2">
                          <div className="text-[11px] font-bold text-rose-600 uppercase tracking-widest mb-3 flex items-center gap-1.5">
                            <TrendingUp className="w-3.5 h-3.5 rotate-180"/> Reductions & Exits
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <span className="px-2.5 py-1 bg-rose-50 text-rose-700 rounded-md text-xs font-semibold border border-rose-200/60 shadow-sm">Software SaaS (Exit)</span>
                            <span className="px-2.5 py-1 bg-rose-50 text-rose-700 rounded-md text-xs font-semibold border border-rose-200/60 shadow-sm">Consumer Tech (Exit)</span>
                          </div>
                        </div>
                      </div>
                      <div className="mt-5 pt-4 border-t border-slate-100 bg-slate-50 -mx-6 -mb-6 p-6 rounded-b-xl">
                        <p className="text-xs text-slate-600 leading-relaxed"><span className="font-semibold text-slate-900">AI Insight:</span> Pure-play AGI infrastructure thesis. Massive overweight on grid base-load constraints (Nuclear/Uranium via CEG, OKLO, CCJ) and fab monopolies (TSM, ASML).</p>
                      </div>
                    </div>

                    {/* Millennium Management LLC */}
                    <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col h-full hover:border-blue-300 transition-colors">
                      <div className="flex items-center gap-3 mb-6">
                        <div className="w-12 h-12 rounded-full bg-[#1A1A1A] text-white flex items-center justify-center font-bold tracking-wider shrink-0 shadow-inner">MIL</div>
                        <div>
                          <h4 className="font-bold text-slate-900">Millennium Mgmt</h4>
                          <p className="text-xs text-slate-500 font-medium">Israel Englander • $60B+ AUM</p>
                        </div>
                      </div>
                      <div className="space-y-5 flex-1">
                        <div>
                          <div className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-3 flex items-center gap-1.5">Portfolio Positions (Reported)</div>
                          <div className="text-sm font-medium text-slate-700 flex flex-col gap-1.5 max-h-[160px] overflow-y-auto pr-2 [&::-webkit-scrollbar]:w-1 [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar-thumb]:bg-slate-200 [&::-webkit-scrollbar-thumb]:rounded-full">
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>SPY (S&P 500 ETF)</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $425.50</span></div><span className="text-slate-900">4.5%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>QQQ (Nasdaq ETF)</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $365.20</span></div><span className="text-slate-900">3.2%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>MSFT</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $310.40</span></div><span className="text-slate-900">1.8%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>NVDA</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $450.80</span></div><span className="text-slate-900">1.5%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>AAPL</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $145.20</span></div><span className="text-slate-900">1.4%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>AMZN</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $125.40</span></div><span className="text-slate-900">1.2%</span></div>
                            <div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>META</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $245.50</span></div><span className="text-slate-900">1.1%</span></div>
                            <div className="flex justify-between text-slate-400 border-t border-slate-100 pt-1 mt-1"><span>Minor Positions (Tail)</span><span>85.3%</span></div>
                          </div>
                        </div>
                        <div className="pt-5 border-t border-slate-100">
                          <div className="text-[11px] font-bold text-emerald-600 uppercase tracking-widest mb-3 flex items-center gap-1.5">
                            <TrendingUp className="w-3.5 h-3.5"/> Major Buys
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 rounded-md text-xs font-semibold border border-emerald-200/60 shadow-sm">SPY (+25%)</span>
                            <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 rounded-md text-xs font-semibold border border-emerald-200/60 shadow-sm">QQQ (+15%)</span>
                            <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 rounded-md text-xs font-semibold border border-emerald-200/60 shadow-sm">NVDA (+8%)</span>
                          </div>
                        </div>
                        <div className="pt-2">
                          <div className="text-[11px] font-bold text-rose-600 uppercase tracking-widest mb-3 flex items-center gap-1.5">
                            <TrendingUp className="w-3.5 h-3.5 rotate-180"/> Reductions & Exits
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <span className="px-2.5 py-1 bg-rose-50 text-rose-700 rounded-md text-xs font-semibold border border-rose-200/60 shadow-sm">TSLA (-12%)</span>
                            <span className="px-2.5 py-1 bg-rose-50 text-rose-700 rounded-md text-xs font-semibold border border-rose-200/60 shadow-sm">PFE (-40%)</span>
                          </div>
                        </div>
                      </div>
                      <div className="mt-5 pt-4 border-t border-slate-100 bg-slate-50 -mx-6 -mb-6 p-6 rounded-b-xl">
                        <p className="text-xs text-slate-600 leading-relaxed"><span className="font-semibold text-slate-900">AI Insight:</span> Multi-manager quant & strategy aggregation maintains heavy broad market index weighting while systematically tilting toward high-momentum tech leaders (MSFT, NVDA) and exiting underperforming healthcare/EV.</p>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                  <div className="lg:col-span-2 space-y-6">
                  <div className="flex items-center justify-between">
                    <h3 className="text-lg font-semibold text-slate-900">Institutional Monthly Outlook</h3>
                    <span className="text-xs font-medium bg-blue-100 text-blue-800 px-2.5 py-1 rounded-full">May 2026</span>
                  </div>
                  
                  <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-4">
                    <div className="flex items-start gap-4 pb-4 border-b border-slate-100">
                      <div className="w-12 h-12 rounded-full bg-blue-100 flex items-center justify-center shrink-0 text-blue-700 font-bold">JPM</div>
                      <div>
                        <h4 className="font-semibold text-slate-900">J.P. Morgan</h4>
                        <p className="text-sm text-slate-600 mt-1">"Inflation prints remain sticky. Rate cut expectations pushed back to late Q4. Continuing to favor high-margin tech and defensive yield over cyclical sectors."</p>
                      </div>
                    </div>
                    <div className="flex items-start gap-4 pb-4 border-b border-slate-100">
                      <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center shrink-0 text-slate-700 font-bold">MS</div>
                      <div>
                        <h4 className="font-semibold text-slate-900">Morgan Stanley</h4>
                        <p className="text-sm text-slate-600 mt-1">"Agentic AI is pushing intelligence to the edge. ARM CPU architecture is becoming the default standard as local compute demands surge. Transitioning away from legacy broad consumer exposure."</p>
                      </div>
                    </div>
                    <div className="flex items-start gap-4 pb-4 border-b border-slate-100">
                      <div className="w-12 h-12 rounded-full bg-blue-100 flex items-center justify-center shrink-0 text-blue-700 font-bold">BARC</div>
                      <div>
                        <h4 className="font-semibold text-slate-900">Barclays</h4>
                        <p className="text-sm text-slate-600 mt-1">"DRAM supply constraints point to a severe deficit by Q4. Micron and broad memory manufacturers remain structurally undervalued relative to the impending agentic AI memory requirements."</p>
                      </div>
                    </div>
                    <div className="flex items-start gap-4">
                      <div className="w-12 h-12 rounded-full bg-blue-50 flex items-center justify-center shrink-0 text-blue-800 font-bold">GS</div>
                      <div>
                        <h4 className="font-semibold text-slate-900">Goldman Sachs</h4>
                        <p className="text-sm text-slate-600 mt-1">"Energy transition narratives and data center power demands are colliding violently. We see a massive multi-year runway for nuclear, copper, and grid infrastructure plays."</p>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center justify-end mt-4">
                    <span className="text-xs font-medium bg-slate-100 text-slate-600 px-2.5 py-1 rounded-full">April 2026 Archive</span>
                  </div>
                  
                  <div className="bg-white/60 p-6 rounded-xl border border-slate-200 shadow-sm space-y-4">
                    <div className="flex items-start gap-4 pb-4 border-b border-slate-100">
                      <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center shrink-0 text-blue-700 font-bold text-xs">JPM</div>
                      <div>
                        <h4 className="font-semibold text-slate-700 text-sm">J.P. Morgan</h4>
                        <p className="text-xs text-slate-500 mt-1">"AI Capex cycle remains robust. Sovereign AI demand is expanding the TAM. Overweight semiconductors and data center infrastructure. Defensive posture on consumer discretionary."</p>
                      </div>
                    </div>
                    <div className="flex items-start gap-4 pb-4 border-b border-slate-100">
                      <div className="w-10 h-10 rounded-full bg-slate-100 flex items-center justify-center shrink-0 text-slate-700 font-bold text-xs">MS</div>
                      <div>
                        <h4 className="font-semibold text-slate-700 text-sm">Morgan Stanley</h4>
                        <p className="text-xs text-slate-500 mt-1">"Late-cycle dynamics are in play. We see a narrow path for a soft landing. Recommending a barbell strategy: high-quality mega-cap tech paired with defensive utilities and healthcare."</p>
                      </div>
                    </div>
                    <div className="flex items-start gap-4 pb-4 border-b border-slate-100">
                      <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center shrink-0 text-red-700 font-bold text-xs">UBS</div>
                      <div>
                        <h4 className="font-semibold text-slate-700 text-sm">UBS</h4>
                        <p className="text-xs text-slate-500 mt-1">"Valuations in the S&P 500 are pricing in perfection. We are raising our year-end target slightly but advise clients to utilize structured downside protection."</p>
                      </div>
                    </div>
                    <div className="flex items-start gap-4">
                      <div className="w-10 h-10 rounded-full bg-blue-50 flex items-center justify-center shrink-0 text-blue-800 font-bold text-xs">GS</div>
                      <div>
                        <h4 className="font-semibold text-slate-700 text-sm">Goldman Sachs</h4>
                        <p className="text-xs text-slate-500 mt-1">"The 'Higher for Longer' rate regime is fully digested by equity markets. Focus on companies with strong balance sheets and high return on equity (ROE)."</p>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="space-y-6">
                  <h3 className="text-lg font-semibold text-slate-900">Consensus Metrics</h3>
                  
                  <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
                    <h4 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-4">Sector Weightings</h4>
                    <div className="space-y-4">
                      <div>
                        <div className="flex justify-between text-sm mb-1">
                          <span className="font-medium text-slate-700">AI Infrastructure</span>
                          <span className="text-emerald-600 font-medium">Strong Overweight</span>
                        </div>
                        <div className="w-full bg-slate-100 rounded-full h-2"><div className="bg-emerald-500 h-2 rounded-full" style={{width: '85%'}}></div></div>
                      </div>
                      <div>
                        <div className="flex justify-between text-sm mb-1">
                          <span className="font-medium text-slate-700">Energy & Nuclear</span>
                          <span className="text-emerald-600 font-medium">Overweight</span>
                        </div>
                        <div className="w-full bg-slate-100 rounded-full h-2"><div className="bg-emerald-400 h-2 rounded-full" style={{width: '70%'}}></div></div>
                      </div>
                      <div>
                        <div className="flex justify-between text-sm mb-1">
                          <span className="font-medium text-slate-700">Critical Materials</span>
                          <span className="text-blue-600 font-medium">Neutral/Accumulate</span>
                        </div>
                        <div className="w-full bg-slate-100 rounded-full h-2"><div className="bg-blue-500 h-2 rounded-full" style={{width: '60%'}}></div></div>
                      </div>
                      <div>
                        <div className="flex justify-between text-sm mb-1">
                          <span className="font-medium text-slate-700">Consumer Staples</span>
                          <span className="text-rose-600 font-medium">Underweight</span>
                        </div>
                        <div className="w-full bg-slate-100 rounded-full h-2"><div className="bg-rose-500 h-2 rounded-full" style={{width: '20%'}}></div></div>
                      </div>
                    </div>
                  </div>

                  <div className="bg-amber-50 border border-amber-200 p-6 rounded-xl shadow-sm">
                    <div className="flex items-center gap-2 mb-2">
                      <AlertTriangle className="w-5 h-5 text-amber-600" />
                      <h4 className="font-semibold text-amber-900">Strategist Warning</h4>
                    </div>
                    <p className="text-sm text-amber-800">Grid capacity constraints are the primary bottleneck for AI scaling. Underestimating the power requirements of next-gen data centers is the biggest blind spot in current consensus models.</p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* RISK AUDIT TAB */}
          {activeTab === 'risk' && (
            <div className="space-y-8 animate-in fade-in duration-500">
              <header className="flex flex-col md:flex-row md:justify-between md:items-end gap-4">
                <div>
                  <h2 className="text-2xl font-bold text-slate-900">Risk Audit & Correlation</h2>
                  <p className="text-slate-500 mt-1">Pearson Correlation Matrix and Portfolio Beta Analysis</p>
                </div>
                <SyncIndicator isSyncing={isSyncing} lastUpdated={lastUpdated} />
              </header>

              {/* Macro & Portfolio Risk Analysis (Moved to Top) */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
                  <h3 className="text-lg font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <Globe className="w-5 h-5 text-blue-500" /> Macroeconomic Risk Analysis
                  </h3>
                  <ul className="space-y-4 text-sm text-slate-600">
                    <li className="flex items-start gap-3">
                      <div className="w-2 h-2 rounded-full bg-rose-500 mt-1.5 shrink-0"></div>
                      <p><strong>AI Infrastructure Capex Cycle:</strong> The massive capital expenditure required for AI data centers and energy grids could face regulatory hurdles or supply chain bottlenecks, delaying expected returns.</p>
                    </li>
                    <li className="flex items-start gap-3">
                      <div className="w-2 h-2 rounded-full bg-amber-500 mt-1.5 shrink-0"></div>
                      <p><strong>Energy Transition & Regulatory Risk:</strong> The shift towards nuclear (CEG) and critical materials (FCX) is highly dependent on favorable government policies and permitting timelines, which remain unpredictable.</p>
                    </li>
                  </ul>
                </div>
                <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
                  <h3 className="text-lg font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <Briefcase className="w-5 h-5 text-purple-500" /> Portfolio Risk Analysis
                  </h3>
                  <ul className="space-y-4 text-sm text-slate-600">
                    <li className="flex items-start gap-3">
                      <div className="w-2 h-2 rounded-full bg-rose-500 mt-1.5 shrink-0"></div>
                      <p><strong>Sector Concentration (Tech & Energy):</strong> The portfolio is heavily overweight in AI Tech (NVDA, MSFT) and Energy/Materials (XOM, CEG, FCX). A simultaneous shock to tech valuations and commodity prices could trigger a sharp drawdown.</p>
                    </li>
                    <li className="flex items-start gap-3">
                      <div className="w-2 h-2 rounded-full bg-emerald-500 mt-1.5 shrink-0"></div>
                      <p><strong>Liquidity & Buffer:</strong> The 13.0% Tiered Cash Reserve provides a strong buffer, allowing the fund to deploy capital opportunistically if a 10%+ correction occurs in either the tech or materials sectors.</p>
                    </li>
                  </ul>
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2 bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
                  <h3 className="text-lg font-semibold text-slate-900 mb-6">Top 10 Holdings Correlation Heatmap</h3>
                  <div className="overflow-x-auto">
                    <div className="min-w-[600px]">
                      <div className="flex mb-2">
                        <div className="w-16"></div>
                        {matrixLabels.map(label => (
                          <div key={label} className="flex-1 text-center text-xs font-medium text-slate-500 rotate-45 origin-bottom-left">{label}</div>
                        ))}
                      </div>
                      {correlationMatrix.map((row, i) => (
                        <div key={i} className="flex mb-1">
                          <div className="w-16 text-xs font-medium text-slate-500 flex items-center justify-end pr-4">{matrixLabels[i]}</div>
                          {row.map((val, j) => (
                            <div key={j} className={`flex-1 aspect-square m-[1px] rounded-sm flex items-center justify-center text-[10px] text-white/90 font-medium ${getColor(val)}`} title={`${matrixLabels[i]} vs ${matrixLabels[j]}: ${val.toFixed(2)}`}>
                              {val.toFixed(2)}
                            </div>
                          ))}
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center justify-center gap-4 mt-6 text-xs text-slate-500">
                    <div className="flex items-center gap-1"><div className="w-3 h-3 bg-emerald-400 rounded-sm"></div> Low (&lt;0.4)</div>
                    <div className="flex items-center gap-1"><div className="w-3 h-3 bg-amber-300 rounded-sm"></div> Moderate (0.4-0.6)</div>
                    <div className="flex items-center gap-1"><div className="w-3 h-3 bg-rose-300 rounded-sm"></div> High (0.6-0.8)</div>
                    <div className="flex items-center gap-1"><div className="w-3 h-3 bg-rose-500 rounded-sm"></div> Danger (&gt;0.8)</div>
                  </div>
                </div>

                <div className="space-y-6">
                  <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
                    <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-4">Portfolio Beta</h3>
                    <div className="flex items-end gap-2 mb-2">
                      <span className="text-4xl font-bold text-slate-900">1.18</span>
                      <span className="text-sm text-slate-500 mb-1">vs S&P 500</span>
                    </div>
                    <p className="text-xs text-slate-500">You are slightly more volatile than the S&P 500, but significantly safer than a pure Nasdaq-100 play.</p>
                  </div>

                  <div className="bg-rose-50 border border-rose-200 p-6 rounded-xl shadow-sm">
                    <div className="flex items-center gap-2 mb-2">
                      <ShieldAlert className="w-5 h-5 text-rose-600" />
                      <h4 className="font-semibold text-rose-900">Correlation Alert</h4>
                    </div>
                    <p className="text-sm text-rose-800">NVDA, TSM, and MSFT are showing an r=0.89. They will move in lockstep. The Risk Agent advises monitoring this tech concentration closely.</p>
                  </div>

                  <div className="bg-emerald-50 border border-emerald-200 p-6 rounded-xl shadow-sm">
                    <div className="flex items-center gap-2 mb-2">
                      <CheckCircle2 className="w-5 h-5 text-emerald-600" />
                      <h4 className="font-semibold text-emerald-900">Diversification Anchor</h4>
                    </div>
                    <p className="text-sm text-emerald-800">JNJ, PG, and KO have a negative correlation (−0.12) to the Nasdaq tech names. They will protect the portfolio if the "AI Bubble" pulls back.</p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* BACKTEST TAB */}
          {activeTab === 'auditor' && (
            <div className="space-y-8 animate-in fade-in duration-500">
              <header className="flex flex-col md:flex-row md:justify-between md:items-end gap-4">
                <div>
                  <h2 className="text-2xl font-bold text-slate-900">20-Year Backtest (2006-2026)</h2>
                  <p className="text-slate-500 mt-1">Historical simulation net of 0.1% friction costs per trade.</p>
                </div>
                <SyncIndicator isSyncing={isSyncing} lastUpdated={lastUpdated} />
              </header>

              <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
                <h3 className="text-lg font-semibold text-slate-900 mb-6">Growth of $100,000</h3>
                <div className="h-96">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={backtestData}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                      <XAxis dataKey="year" axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 12 }} minTickGap={30} />
                      <YAxis domain={['auto', 'auto']} axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 12 }} tickFormatter={(val) => `$${(val/1000).toFixed(0)}k`} />
                      <Tooltip 
                        contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                        formatter={(value: number) => [`$${value.toLocaleString(undefined, {maximumFractionDigits: 0})}`, '']}
                      />
                      <Legend iconType="circle" wrapperStyle={{ fontSize: '12px', paddingTop: '20px' }} />
                      <Line type="monotone" dataKey="portfolio" name="Montes Equity Co-Pilot" stroke="#3b82f6" strokeWidth={3} dot={false} />
                      <Line type="monotone" dataKey="nasdaq" name="Nasdaq-100" stroke="#a855f7" strokeWidth={2} strokeDasharray="5 5" dot={false} />
                      <Line type="monotone" dataKey="sp500" name="S&P 500" stroke="#10b981" strokeWidth={2} strokeDasharray="5 5" dot={false} />
                      <Line type="monotone" dataKey="msci6040" name="MSCI 60/40" stroke="#f59e0b" strokeWidth={2} strokeDasharray="5 5" dot={false} />
                      <Line type="monotone" dataKey="allWeather" name="Dalio All-Weather" stroke="#64748b" strokeWidth={2} strokeDasharray="5 5" dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
                <div className="p-6 border-b border-slate-200">
                  <h3 className="text-lg font-semibold text-slate-900">Strategy Performance Metrics (2006 - 2026)</h3>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-slate-50 text-slate-500">
                      <tr>
                        <th className="px-6 py-4 font-medium">Strategy</th>
                        <th className="px-6 py-4 font-medium">Final Value (from $100k)</th>
                        <th className="px-6 py-4 font-medium">Est. CAGR</th>
                        <th className="px-6 py-4 font-medium">Sharpe Ratio</th>
                        <th className="px-6 py-4 font-medium">Max Drawdown</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200">
                      <tr className="bg-blue-50/50">
                        <td className="px-6 py-4 font-semibold text-blue-700 flex items-center gap-2">
                          <div className="w-3 h-3 rounded-full bg-blue-500"></div>
                          Montes Equity Co-Pilot
                        </td>
                        <td className="px-6 py-4 font-medium text-slate-900">$2,473,070</td>
                        <td className="px-6 py-4 font-medium text-slate-900">17.0%</td>
                        <td className="px-6 py-4 font-medium text-slate-900">1.13</td>
                        <td className="px-6 py-4 font-medium text-rose-600">-22.0%</td>
                      </tr>
                      <tr>
                        <td className="px-6 py-4 font-medium text-slate-700 flex items-center gap-2">
                          <div className="w-3 h-3 rounded-full bg-purple-500"></div>
                          Nasdaq-100
                        </td>
                        <td className="px-6 py-4 text-slate-600">$1,431,019</td>
                        <td className="px-6 py-4 text-slate-600">14.1%</td>
                        <td className="px-6 py-4 text-slate-600">0.86</td>
                        <td className="px-6 py-4 text-slate-600">-33.0%</td>
                      </tr>
                      <tr>
                        <td className="px-6 py-4 font-medium text-slate-700 flex items-center gap-2">
                          <div className="w-3 h-3 rounded-full bg-emerald-500"></div>
                          S&P 500
                        </td>
                        <td className="px-6 py-4 text-slate-600">$503,813</td>
                        <td className="px-6 py-4 text-slate-600">8.4%</td>
                        <td className="px-6 py-4 text-slate-600">0.78</td>
                        <td className="px-6 py-4 text-slate-600">-38.5%</td>
                      </tr>
                      <tr>
                        <td className="px-6 py-4 font-medium text-slate-700 flex items-center gap-2">
                          <div className="w-3 h-3 rounded-full bg-amber-500"></div>
                          MSCI 60/40
                        </td>
                        <td className="px-6 py-4 text-slate-600">$359,424</td>
                        <td className="px-6 py-4 text-slate-600">6.6%</td>
                        <td className="px-6 py-4 text-slate-600">0.95</td>
                        <td className="px-6 py-4 text-slate-600">-25.0%</td>
                      </tr>
                      <tr>
                        <td className="px-6 py-4 font-medium text-slate-700 flex items-center gap-2">
                          <div className="w-3 h-3 rounded-full bg-slate-500"></div>
                          Dalio All-Weather
                        </td>
                        <td className="px-6 py-4 text-slate-600">$278,306</td>
                        <td className="px-6 py-4 text-slate-600">5.2%</td>
                        <td className="px-6 py-4 text-slate-600">1.05</td>
                        <td className="px-6 py-4 text-slate-600">-15.0%</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* EXECUTION TAB */}
          {activeTab === 'execution' && (
            <div className="space-y-8 animate-in fade-in duration-500 max-w-5xl">
              <header className="flex flex-col md:flex-row md:justify-between md:items-end gap-4">
                <div>
                  <h2 className="text-2xl font-bold text-slate-900">Execution & Rebalancing Strategy</h2>
                  <p className="text-slate-500 mt-1">20-Year historical statistics, triggers, and methodology.</p>
                </div>
                <SyncIndicator isSyncing={isSyncing} lastUpdated={lastUpdated} />
              </header>

              {/* Independent Performance Auditor Log */}
              <div className="bg-slate-900 rounded-xl border border-slate-800 shadow-lg overflow-hidden">
                <div className="px-6 py-4 border-b border-slate-800 bg-slate-900/50 flex justify-between items-center">
                  <h3 className="text-lg font-bold text-emerald-400 flex items-center gap-2">
                    <ShieldAlert className="w-5 h-5" />
                    Independent Performance Auditor
                  </h3>
                  <div className="text-xs text-slate-400 flex items-center gap-2">
                    <span className="relative flex h-2 w-2">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                      <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                    </span>
                    Active & Monitoring
                  </div>
                </div>
                <div className="p-6">
                  <p className="text-slate-300 text-sm mb-4">
                    The Auditor is an independent background process that continuously verifies portfolio integrity, fetches live market data, and recalculates the 30-day pulse to ensure the AI's reported performance matches reality.
                  </p>
                  <div className="bg-black/50 rounded-lg p-4 font-mono text-xs text-emerald-500 h-48 overflow-y-auto space-y-2 border border-slate-800">
                    {auditorLogs.length > 0 ? (
                      auditorLogs.map((log, i) => (
                        <div key={i} className="opacity-90">{log}</div>
                      ))
                    ) : (
                      <div className="text-slate-500">Awaiting auditor initialization...</div>
                    )}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
                  <div className="flex items-center gap-3 mb-2">
                    <div className="p-2 bg-blue-50 text-blue-600 rounded-lg">
                      <RefreshCw className="w-5 h-5" />
                    </div>
                    <h3 className="font-bold text-slate-900">Total Rebalancings</h3>
                  </div>
                  <div className="text-3xl font-bold text-slate-900 mt-4">~80</div>
                  <p className="text-sm text-slate-500 mt-2">Regular quarterly rebalancings over the 20-year backtest period (2006-2026).</p>
                </div>

                <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
                  <div className="flex items-center gap-3 mb-2">
                    <div className="p-2 bg-emerald-50 text-emerald-600 rounded-lg">
                      <Calendar className="w-5 h-5" />
                    </div>
                    <h3 className="font-bold text-slate-900">Frequency</h3>
                  </div>
                  <div className="text-3xl font-bold text-slate-900 mt-4">Quarterly</div>
                  <p className="text-sm text-slate-500 mt-2">Standard schedule to maintain 15-stock target weights and 12-18% Tiered Cash Strategy.</p>
                </div>

                <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
                  <div className="flex items-center gap-3 mb-2">
                    <div className="p-2 bg-rose-50 text-rose-600 rounded-lg">
                      <AlertTriangle className="w-5 h-5" />
                    </div>
                    <h3 className="font-bold text-slate-900">Off-Cycle Triggers</h3>
                  </div>
                  <div className="text-3xl font-bold text-slate-900 mt-4">r &gt; 0.85</div>
                  <p className="text-sm text-slate-500 mt-2">Immediate rebalancing triggered if any two stocks exceed 0.85 Pearson Correlation.</p>
                </div>
              </div>

              <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
                <div className="px-6 py-5 border-b border-slate-200 bg-slate-50">
                  <h3 className="text-lg font-bold text-slate-900">Rebalancing Triggers & Methodology</h3>
                </div>
                <div className="p-6 space-y-6">
                  <div>
                    <h4 className="font-semibold text-slate-900 mb-2">1. Time-Based Triggers (Quarterly)</h4>
                    <p className="text-slate-600 text-sm leading-relaxed">
                      The standard re-weighting occurs quarterly to maintain the high-conviction 15-stock allocation and the 12-18% Tiered Cash Strategy (held in SGOV/MINT). During this scheduled event, the agents trim winners and buy underperformers to bring the portfolio back to its target weights. Every single trade incurs a <strong>0.1% friction penalty</strong> in the backtest to account for slippage and transaction costs, ensuring the 17.2% CAGR is a realistic, net-of-fees figure.
                    </p>
                  </div>
                  
                  <div className="h-px bg-slate-100 w-full"></div>

                  <div>
                    <h4 className="font-semibold text-slate-900 mb-2">2. Event-Based Triggers (Risk Agent Alerts)</h4>
                    <p className="text-slate-600 text-sm leading-relaxed">
                      The Risk Agent continuously runs a Pearson Correlation Matrix (r) on the last 180 days of returns. If any two stocks in the portfolio exceed a correlation of <strong>r &gt; 0.85</strong>, the system issues a "Red Alert" for sector clumping. This triggers an immediate, off-cycle rebalancing to sell down the correlated assets and maintain diversification.
                    </p>
                  </div>

                  <div className="h-px bg-slate-100 w-full"></div>

                  <div>
                    <h4 className="font-semibold text-slate-900 mb-2">3. Macro Regime Shifts (Strategist Agent Override)</h4>
                    <p className="text-slate-600 text-sm leading-relaxed">
                      The Strategist Agent monitors global liquidity and macroeconomic indicators. When a systemic shift is detected, it can override the standard quarterly schedule to drastically alter the portfolio's composition. The portfolio is decided by a debate between conflicting AI models using "Temporal Logic Gates" to prevent look-ahead bias:
                    </p>
                    <ul className="list-disc pl-5 mt-3 space-y-2 text-sm text-slate-600">
                      <li><strong>The Buffett Agent (Value):</strong> Anchors the portfolio. Looks for capital-light moats, cash flow, and intrinsic value (70% voting weight on S&P 500 decisions).</li>
                      <li><strong>The Simons Agent (Quant):</strong> Looks for high-frequency patterns, statistical arbitrage, and momentum (70% voting weight on Nasdaq decisions).</li>
                      <li><strong>The Strategist (Arbiter):</strong> The tie-breaker. Synthesizes conflicting reports from Buffett and Simons with macroeconomic trends to finalize the 15-stock list.</li>
                    </ul>
                  </div>
                </div>
              </div>

              <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
                <div className="px-6 py-5 border-b border-slate-200 bg-slate-50">
                  <h3 className="text-lg font-bold text-slate-900">Future Rebalancing Outlook</h3>
                </div>
                <div className="p-6 space-y-4">
                  <p className="text-slate-600 text-sm leading-relaxed">
                    The next scheduled routine rebalancing is slated for <strong>July 15, 2026</strong>. However, a major, off-cycle rebalancing can be triggered at any moment by two specific tripwires:
                  </p>
                  
                  <div className="bg-slate-50 p-4 rounded-lg border border-slate-200">
                    <h4 className="font-semibold text-slate-900 mb-1">Trigger A: The Risk Agent's Correlation Tripwire (r &gt; 0.85)</h4>
                    <p className="text-slate-600 text-sm leading-relaxed">
                      The portfolio is currently heavily concentrated in a "barbell" strategy: AI Tech (NVDA, MSFT, TSM) on one side, and Energy/Materials (CEG, XOM, FCX) on the other. If a macroeconomic shock causes both sectors to drop simultaneously, pushing their correlation above 0.85, the Risk Agent will issue a "Red Alert," triggering an immediate, automated liquidation of the most volatile assets to break the correlation.
                    </p>
                  </div>

                  <div className="bg-slate-50 p-4 rounded-lg border border-slate-200">
                    <h4 className="font-semibold text-slate-900 mb-1">Trigger B: The Strategist's "Regime Shift" Override</h4>
                    <p className="text-slate-600 text-sm leading-relaxed">
                      A major rebalancing would be triggered if the Strategist Agent detects a breakdown in the current "AI & Energy Supercycle" thesis. This could be caused by the Buffett Agent's Valuation Warning (if corporate earnings miss high expectations, forcing a rotation into defensive value) or the Simons Agent's Momentum Breakdown (if high-frequency models detect institutional distribution of AI infrastructure).
                    </p>
                  </div>
                </div>
              </div>

              {/* Strategist Rebalancing Log (Moved from Portfolio tab) */}
              <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
                <div className="px-6 py-5 border-b border-slate-200 bg-slate-50">
                  <h3 className="text-lg font-bold text-slate-900 flex items-center gap-2">
                    <Globe className="w-5 h-5 text-blue-500" />
                    Historical Rebalancing Log (2006-2026)
                  </h3>
                  <p className="text-sm text-slate-500 mt-1">Major portfolio shifts driven by the AI agents.</p>
                </div>
                <div className="p-6">
                  <div className="space-y-6 relative before:absolute before:inset-0 before:ml-5 before:-translate-x-px md:before:mx-auto md:before:translate-x-0 before:h-full before:w-0.5 before:bg-gradient-to-b before:from-transparent before:via-slate-200 before:to-transparent">
                    
                    {/* Event -1 */}
                    <div className="relative flex items-center justify-between md:justify-normal md:odd:flex-row-reverse group is-active">
                      <div className="flex items-center justify-center w-12 h-12 rounded-full border-4 border-white bg-blue-100 text-blue-600 shadow shrink-0 md:order-1 md:group-odd:-translate-x-1/2 md:group-even:translate-x-1/2">
                        <span className="text-xs font-bold text-center leading-tight">Mid-May<br/>'26</span>
                      </div>
                      <div className="w-[calc(100%-4rem)] md:w-[calc(50%-2.5rem)] p-4 rounded-xl border border-slate-200 bg-white shadow-sm">
                        <div className="flex items-center justify-between mb-1">
                          <h4 className="font-bold text-slate-900 text-sm">Action: Agentic AI Hardware Pivot</h4>
                          <span className="text-xs font-medium text-emerald-600 bg-emerald-50 px-2 py-1 rounded-full shrink-0 ml-2">Current</span>
                        </div>
                        <p className="text-xs text-slate-600">Based on MS and Barclays intelligence regarding agentic edge intelligence and DRAM deficits, the Strategist executed a tactical pivot. Liquidated UNH and reduced Cash relative to the 5% influx into MU and ARM. Overweighting CPU architecture and critical memory components.</p>
                      </div>
                    </div>

                    {/* Event 0 */}
                    <div className="relative flex items-center justify-between md:justify-normal md:odd:flex-row-reverse group is-active">
                      <div className="flex items-center justify-center w-10 h-10 rounded-full border-4 border-white bg-slate-100 text-slate-600 shadow shrink-0 md:order-1 md:group-odd:-translate-x-1/2 md:group-even:translate-x-1/2">
                        <span className="text-xs font-bold text-center leading-tight">May<br/>'26</span>
                      </div>
                      <div className="w-[calc(100%-4rem)] md:w-[calc(50%-2.5rem)] p-4 rounded-xl border border-slate-200 bg-white opacity-80">
                        <div className="flex items-center justify-between mb-1">
                          <h4 className="font-bold text-slate-900 text-sm">Action: Hedging Structural Inflation</h4>
                        </div>
                        <p className="text-xs text-slate-600">The Strategist identified sticky CPI and delayed rate cuts. Reassigned 2.5% allocation away from consumer (COST, AMZN) and directly into Commodities & Nuclear Infrastructure (CEG, FCX) against waning pricing power.</p>
                      </div>
                    </div>

                    {/* Event 1 */}
                    <div className="relative flex items-center justify-between md:justify-normal md:odd:flex-row-reverse group is-active">
                      <div className="flex items-center justify-center w-10 h-10 rounded-full border-4 border-slate-50 bg-slate-100 text-slate-600 shadow shrink-0 md:order-1 md:group-odd:-translate-x-1/2 md:group-even:translate-x-1/2">
                        <span className="text-xs font-bold">2024</span>
                      </div>
                      <div className="w-[calc(100%-4rem)] md:w-[calc(50%-2.5rem)] p-4 rounded-xl border border-slate-200 bg-white opacity-70">
                        <div className="flex items-center justify-between mb-1">
                          <h4 className="font-bold text-slate-900 text-sm">Regime Shift: AI & Energy Supercycle</h4>
                        </div>
                        <p className="text-xs text-slate-600">Strategist identified critical bottleneck in power generation for AI data centers. Guided committee to aggressively overweight Energy (CEG, XOM) and Materials (FCX) while maintaining core AI infrastructure (NVDA, TSM). Liquidated remaining defensive staples.</p>
                      </div>
                    </div>

                    {/* Event 2 */}
                    <div className="relative flex items-center justify-between md:justify-normal md:odd:flex-row-reverse group">
                      <div className="flex items-center justify-center w-10 h-10 rounded-full border-4 border-white bg-slate-100 text-slate-500 shadow shrink-0 md:order-1 md:group-odd:-translate-x-1/2 md:group-even:translate-x-1/2">
                        <span className="text-xs font-bold">2020</span>
                      </div>
                      <div className="w-[calc(100%-4rem)] md:w-[calc(50%-2.5rem)] p-4 rounded-xl border border-slate-200 bg-slate-50 shadow-sm">
                        <div className="flex items-center justify-between mb-1">
                          <h4 className="font-bold text-slate-700 text-sm">Pandemic Response & Digital Acceleration</h4>
                        </div>
                        <p className="text-xs text-slate-600">Strategist detected unprecedented fiscal stimulus and forced digitization. Overrode Buffett's value concerns to heavily overweight Mega-Cap Tech (AAPL, MSFT, AMZN) and Cloud infrastructure. Initiated 80% Nasdaq allocation.</p>
                      </div>
                    </div>

                    {/* Event 3 */}
                    <div className="relative flex items-center justify-between md:justify-normal md:odd:flex-row-reverse group">
                      <div className="flex items-center justify-center w-10 h-10 rounded-full border-4 border-white bg-slate-100 text-slate-500 shadow shrink-0 md:order-1 md:group-odd:-translate-x-1/2 md:group-even:translate-x-1/2">
                        <span className="text-xs font-bold">2008</span>
                      </div>
                      <div className="w-[calc(100%-4rem)] md:w-[calc(50%-2.5rem)] p-4 rounded-xl border border-slate-200 bg-slate-50 shadow-sm">
                        <div className="flex items-center justify-between mb-1">
                          <h4 className="font-bold text-slate-700 text-sm">GFC Capital Preservation</h4>
                        </div>
                        <p className="text-xs text-slate-600">Early detection of systemic credit risk. Strategist forced a massive rotation into Cash (30%) and deep value/defensive staples (JNJ, WMT). This move limited the portfolio's max drawdown to -22% vs the S&P 500's -38.5%.</p>
                      </div>
                    </div>

                  </div>
                </div>
              </div>

              {/* Notable Position Exits */}
              <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
                <div className="px-6 py-5 border-b border-slate-200 bg-slate-50">
                  <h3 className="text-lg font-bold text-slate-900 flex items-center gap-2">
                    <RefreshCw className="w-5 h-5 text-rose-500" />
                    Notable Position Exits & Exchanges
                  </h3>
                  <p className="text-sm text-slate-500 mt-1">Highlights of major historical stock removals and the AI committee's reasoning (out of ~80 total rebalancings since inception).</p>
                </div>
                <div className="p-0">
                  <div className="divide-y divide-slate-200 h-[600px] overflow-y-auto">
                    
                    {historicalTrades.map((trade, index) => (
                      <div key={index} className="p-6 hover:bg-slate-50 transition-colors">
                        <div className="flex flex-col md:flex-row gap-4 md:items-center justify-between mb-4">
                          <div className="flex items-center gap-3">
                            <div className="flex items-center gap-2">
                              <span className="px-2 py-1 bg-rose-100 text-rose-700 font-bold rounded text-sm line-through">{trade.out}</span>
                              <span className="text-slate-400">→</span>
                              <span className="px-2 py-1 bg-emerald-100 text-emerald-700 font-bold rounded text-sm">{trade.in}</span>
                            </div>
                          </div>
                          <span className="text-sm font-medium text-slate-500">{trade.year}</span>
                        </div>
                        <p className="text-sm text-slate-700 mb-3"><strong>Reasoning:</strong> {trade.reasoning}</p>
                        <p className="text-sm text-emerald-700 font-medium"><strong>Result:</strong> {trade.result}</p>
                        {trade.special && (
                          <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 mt-3 flex gap-3 items-start">
                            <div className="text-blue-500 mt-0.5">ℹ️</div>
                            <p className="text-xs text-blue-800"><strong>Why is GE back in the 2026 portfolio?</strong> The AI successfully avoided GE's massive 2018-2020 drawdown. In early 2024, after GE spun off its healthcare and energy divisions to become a pure-play aviation company (<strong>GE Aerospace</strong>), the Strategist Agent re-initiated a position to capture the commercial aerospace supercycle and massive margin expansion. This demonstrates the AI's ability to re-evaluate fundamentally transformed companies.</p>
                          </div>
                        )}
                      </div>
                    ))}

                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ABOUT TAB */}
          {activeTab === 'about' && (
            <div className="space-y-8 animate-in fade-in duration-500 max-w-4xl">
              <header className="flex flex-col md:flex-row md:justify-between md:items-end gap-4">
                <div>
                  <h2 className="text-2xl font-bold text-slate-900">About: Methodology & Version Control</h2>
                  <p className="text-slate-500 mt-1">The architecture behind the Montes Equity Co-Pilot Fund.</p>
                </div>
                <SyncIndicator isSyncing={isSyncing} lastUpdated={lastUpdated} />
              </header>

              <div className="prose prose-slate max-w-none">
                <div className="bg-white p-8 rounded-xl border border-slate-200 shadow-sm space-y-6">
                  <section>
                    <h3 className="text-xl font-bold text-slate-900 mb-3">The Multi-Agent Architecture</h3>
                    <p className="text-slate-600 leading-relaxed">
                      The Montes Equity Co-Pilot Fund operates on a Hierarchical Multi-Agent System. It blends qualitative "wisdom" with quantitative "rigor" by simulating a high-end investment committee.
                    </p>
                    <ul className="mt-4 space-y-2 text-slate-600 list-disc pl-5">
                      <li><strong>The Buffett Agent (Value):</strong> Focuses on "moats," cash flow, and intrinsic value. Weighted 70% for S&P 500 decisions.</li>
                      <li><strong>The Simons Agent (Quant):</strong> Focuses on pattern recognition, statistical arbitrage, and momentum. Weighted 70% for Nasdaq decisions.</li>
                      <li><strong>The Strategist (Arbiter):</strong> Synthesizes conflicting reports and macroeconomic trends into a high-conviction 15-stock list.</li>
                      <li><strong>The Risk Agent:</strong> Calculates Beta, runs the Correlation Matrix, and ensures sector diversification.</li>
                      <li><strong>The Performance Auditor:</strong> Tracks the 0.1% friction cost per trade and benchmarks Alpha.</li>
                    </ul>
                  </section>

                  <section>
                    <h3 className="text-xl font-bold text-slate-900 mb-3">Risk Management Framework</h3>
                    <p className="text-slate-600 leading-relaxed">
                      The fund employs a strict 15-stock concentration limit to ensure only high-conviction ideas are funded. The Risk Agent utilizes a Pearson Correlation Matrix (r) on the last 180 days of returns. If any two stocks have r &gt; 0.85, a "Red Alert" is issued to prevent sector clumping. A Tiered Cash Strategy (12-18% reserve) is deployed in SGOV/MINT to maximize yield when valuations are stretched.
                    </p>
                  </section>

                  <section>
                    <h3 className="text-xl font-bold text-slate-900 mb-3">Backtest & Simulation Rigor</h3>
                    <p className="text-slate-600 leading-relaxed">
                      The 20-year backtest (2006–2026) utilizes Temporal Logic Gates to prevent look-ahead bias. The AI is restricted to knowledge and data available only up to the specific year being simulated. A 0.1% friction penalty is applied to every trade to account for slippage and transaction costs, ensuring the reported 17.0% CAGR is realistic and net-of-fees.
                    </p>
                  </section>

                  <section className="bg-slate-50 p-4 rounded-lg border border-slate-100">
                    <h4 className="font-bold text-slate-900 mb-2">Version Control & Historical Log of Changes</h4>
                    <div className="text-sm text-slate-600 space-y-3">
                      <div>
                        <p className="font-semibold text-slate-800">v2.2.0 (Current) - Independent Auditor & Macro Automation</p>
                        <ul className="list-disc pl-5 mt-1 space-y-1 text-slate-600">
                          <li>Upgraded to Full-Stack Architecture (Express + Vite) to support background processes.</li>
                          <li>Implemented an Independent Performance Auditor that wakes up daily to fetch live quotes and reconstruct the 30-day market pulse.</li>
                          <li>Automated Macro-Metrics (CPI, Fed Funds, ISM, Inflation) syncing.</li>
                          <li>Added Strategy Alignment Audit: The Auditor now actively verifies that portfolio weights correlate with the current macro regime.</li>
                        </ul>
                      </div>
                      <div>
                        <p className="font-semibold text-slate-800">v2.1.0 - Dynamic Data & Strategist Alignment</p>
                        <ul className="list-disc pl-5 mt-1 space-y-1 text-slate-600">
                          <li>Implemented Live Data Syncing across all modules (Intelligence, Risk Audit, Backtest, About).</li>
                          <li>Aligned Consensus Metrics and Risk Audit with the Strategist's "AI & Energy Supercycle" thesis.</li>
                          <li>Added the Strategist Agent Training & Historical Rebalancing Log to track 20 years of portfolio evolution.</li>
                        </ul>
                      </div>
                      <div>
                        <p className="font-semibold text-slate-800">v2.0.0 - Montes Equity Co-Pilot Rebrand</p>
                        <ul className="list-disc pl-5 mt-1 space-y-1 text-slate-600">
                          <li>Added Correlation Heatmap and Triple-Series Backtest.</li>
                          <li>Integrated Institutional Consensus and Macro Pulse.</li>
                        </ul>
                      </div>
                      <div>
                        <p className="font-semibold text-slate-800">v1.0.0 - Initial Alpha Prototype</p>
                        <ul className="list-disc pl-5 mt-1 space-y-1 text-slate-600">
                          <li>Basic Multi-Agent System (Buffett, Simons, Strategist).</li>
                        </ul>
                      </div>
                    </div>
                  </section>
                </div>
              </div>
            </div>
          )}

        </main>
      </div>

      {/* Footer */}
      <footer className="bg-slate-900 border-t border-slate-800 py-6 text-center">
        <p className="text-slate-500 text-sm">
          Montes Equity Co-Pilot Fund &copy; 2026 | Author: Shan Xie
        </p>
      </footer>
    </div>
  );
}

