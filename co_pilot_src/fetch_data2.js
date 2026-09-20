import YahooFinance from 'yahoo-finance2';
import fs from 'fs';

const yahooFinance = new YahooFinance();

async function run() {
  try {
    const symbols = ['AAPL', 'BRK-B', 'NVDA', 'KO', 'GOOGL', 'COST', 'MSFT', 'V', 'AMZN', 'JNJ', 'TSM', 'PG', 'META', 'UNH', 'PEP', '^GSPC', '^NDX'];
    const quotes = [];
    
    for (const symbol of symbols) {
      try {
        const quote = await yahooFinance.quote(symbol);
        quotes.push({
          symbol: symbol,
          price: quote.regularMarketPrice,
          low52: quote.fiftyTwoWeekLow,
          high52: quote.fiftyTwoWeekHigh
        });
      } catch (e) {
        console.error(`Error fetching quote for ${symbol}:`, e.message);
      }
    }

    const queryOptions = { period1: '2026-03-08', period2: '2026-04-08', interval: '1d' };
    const sp500Hist = await yahooFinance.historical('^GSPC', queryOptions);
    const ndxHist = await yahooFinance.historical('^NDX', queryOptions);

    const queryOptionsYearly = { period1: '2006-01-01', period2: '2026-04-08', interval: '1mo' };
    const sp500Yearly = await yahooFinance.historical('^GSPC', queryOptionsYearly);
    const ndxYearly = await yahooFinance.historical('^NDX', queryOptionsYearly);

    fs.writeFileSync('market_data.json', JSON.stringify({ quotes, sp500Hist, ndxHist, sp500Yearly, ndxYearly }, null, 2));
    console.log("Data written to market_data.json");
  } catch (e) {
    console.error(e);
  }
}
run();
