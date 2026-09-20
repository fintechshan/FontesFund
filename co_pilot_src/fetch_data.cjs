const https = require('https');

function fetchUrl(url) {
  return new Promise((resolve, reject) => {
    https.get(url, { headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36' } }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          resolve({ error: 'Failed to parse JSON', data: data.substring(0, 200) });
        }
      });
    }).on('error', reject);
  });
}

async function run() {
  try {
    const symbols = 'AAPL,BRK-B,NVDA,KO,GOOGL,COST,MSFT,V,AMZN,JNJ,TSM,PG,META,UNH,PEP,^GSPC,^NDX';
    const quoteUrl = `https://query1.finance.yahoo.com/v7/finance/quote?symbols=${symbols}`;
    const quoteData = await fetchUrl(quoteUrl);
    
    let quotes = [];
    if (quoteData.quoteResponse && quoteData.quoteResponse.result) {
      quotes = quoteData.quoteResponse.result.map(q => ({
        symbol: q.symbol,
        price: q.regularMarketPrice,
        low52: q.fiftyTwoWeekLow,
        high52: q.fiftyTwoWeekHigh
      }));
    } else {
      console.error("Quote data error:", quoteData);
    }
    
    const sp500Hist = await fetchUrl(`https://query1.finance.yahoo.com/v8/finance/chart/^GSPC?interval=1d&range=1mo`);
    const ndxHist = await fetchUrl(`https://query1.finance.yahoo.com/v8/finance/chart/^NDX?interval=1d&range=1mo`);
    
    const sp500Yearly = await fetchUrl(`https://query1.finance.yahoo.com/v8/finance/chart/^GSPC?interval=3mo&range=20y`);
    const ndxYearly = await fetchUrl(`https://query1.finance.yahoo.com/v8/finance/chart/^NDX?interval=3mo&range=20y`);

    const fs = require('fs');
    fs.writeFileSync('market_data.json', JSON.stringify({ 
      quotes, 
      sp500Hist: sp500Hist.chart ? sp500Hist.chart.result[0] : null, 
      ndxHist: ndxHist.chart ? ndxHist.chart.result[0] : null, 
      sp500Yearly: sp500Yearly.chart ? sp500Yearly.chart.result[0] : null, 
      ndxYearly: ndxYearly.chart ? ndxYearly.chart.result[0] : null 
    }, null, 2));
    console.log("Data written to market_data.json");
  } catch (e) {
    console.error(e);
  }
}
run();
