import YahooFinance from 'yahoo-finance2';
import fs from 'fs';

const yahooFinance = new YahooFinance();

async function run() {
  const symbols = ['AAPL', 'BRK-B', 'NVDA', 'GOOGL', 'COST', 'MSFT', 'V', 'AMZN', 'TSM', 'META', 'UNH', 'XOM', 'FCX', 'GE', 'CEG', 'PLTR'];
  const quotes = [];
  for (const symbol of symbols) {
    try {
      const quote = await yahooFinance.quote(symbol);
      quotes.push({ symbol, price: quote.regularMarketPrice, low52: quote.fiftyTwoWeekLow, high52: quote.fiftyTwoWeekHigh });
    } catch (e) { console.error(e); }
  }
  fs.writeFileSync('new_quotes.json', JSON.stringify(quotes, null, 2));
  console.log("New quotes fetched.");
}
run();
