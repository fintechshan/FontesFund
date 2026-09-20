import YahooFinance from 'yahoo-finance2';
import fs from 'fs';

const yahooFinance = new YahooFinance();

const portfolioWeights = {
  'AAPL': 8.5, 'BRK-B': 8.0, 'NVDA': 7.5, 'GOOGL': 6.5, 'COST': 6.0,
  'MSFT': 6.0, 'V': 5.5, 'AMZN': 5.5, 'XOM': 5.0, 'TSM': 5.0,
  'PLTR': 4.0, 'FCX': 4.5, 'META': 4.0, 'UNH': 4.0, 'GE': 3.5, 'CEG': 3.5
};
const cashWeight = 13.0;

async function run() {
  try {
    const endDate = new Date();
    const startDate = new Date();
    startDate.setDate(endDate.getDate() - 45); // Fetch 45 days to ensure we get 30 trading days

    const queryOptions = { period1: startDate.toISOString().split('T')[0], period2: endDate.toISOString().split('T')[0], interval: '1d' };
    
    const sp500Hist = await yahooFinance.historical('^GSPC', queryOptions);
    const ndxHist = await yahooFinance.historical('^NDX', queryOptions);
    
    const stockHists = {};
    for (const symbol of Object.keys(portfolioWeights)) {
      try {
        stockHists[symbol] = await yahooFinance.historical(symbol, queryOptions);
      } catch (e) {
        console.error(`Error fetching ${symbol}:`, e.message);
      }
    }

    // Align dates
    const dates = sp500Hist.map(d => d.date.toISOString().split('T')[0]).slice(-21); // Last 21 trading days (~30 calendar days)
    
    const pulseData = [];
    
    const baseSp500 = sp500Hist.find(d => d.date.toISOString().split('T')[0] === dates[0]).close;
    const baseNdx = ndxHist.find(d => d.date.toISOString().split('T')[0] === dates[0]).close;
    
    const basePrices = {};
    for (const symbol of Object.keys(portfolioWeights)) {
      const hist = stockHists[symbol];
      if (hist) {
        const baseDay = hist.find(d => d.date.toISOString().split('T')[0] === dates[0]);
        if (baseDay) basePrices[symbol] = baseDay.close;
      }
    }

    for (const dateStr of dates) {
      const sp500Day = sp500Hist.find(d => d.date.toISOString().split('T')[0] === dateStr);
      const ndxDay = ndxHist.find(d => d.date.toISOString().split('T')[0] === dateStr);
      
      let portfolioReturn = 0;
      let totalWeight = 0;
      
      for (const symbol of Object.keys(portfolioWeights)) {
        const hist = stockHists[symbol];
        if (hist && basePrices[symbol]) {
          const day = hist.find(d => d.date.toISOString().split('T')[0] === dateStr);
          if (day) {
            const ret = (day.close - basePrices[symbol]) / basePrices[symbol];
            portfolioReturn += ret * portfolioWeights[symbol];
            totalWeight += portfolioWeights[symbol];
          }
        }
      }
      
      // Add cash return (assuming 0% for 30 days for simplicity, or slightly positive)
      totalWeight += cashWeight;
      portfolioReturn = portfolioReturn / totalWeight; // Should be 100
      
      const dateObj = new Date(dateStr);
      const formattedDate = dateObj.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      
      pulseData.push({
        date: formattedDate,
        portfolio: Number((portfolioReturn * 100).toFixed(2)),
        sp500: Number((((sp500Day.close - baseSp500) / baseSp500) * 100).toFixed(2)),
        nasdaq: Number((((ndxDay.close - baseNdx) / baseNdx) * 100).toFixed(2))
      });
    }

    fs.writeFileSync('public/pulse_data.json', JSON.stringify(pulseData, null, 2));
    console.log("Data written to public/pulse_data.json");
  } catch (e) {
    console.error(e);
  }
}
run();
