const fs = require('fs');

let content = fs.readFileSync('src/App.tsx', 'utf8');

const regex = /<div className="flex justify-between"><span>(.*?)<\/span><span className="text-slate-900">(.*?)%<\/span><\/div>/g;

function getAvgPrice(ticker) {
  // Simple deterministic assignment based on string hash for dummy data
  let num = 0;
  for (let i = 0; i < ticker.length; i++) {
    num += ticker.charCodeAt(i);
  }
  const avg = (num * 1.345 % 400 + 45).toFixed(2);
  // overrides for realism
  if(ticker.includes('AAPL')) return '145.20';
  if(ticker.includes('BAC')) return '32.10';
  if(ticker.includes('AXP')) return '185.50';
  if(ticker.includes('KO')) return '58.40';
  if(ticker.includes('CVX')) return '145.80';
  if(ticker.includes('OXY')) return '58.90';
  if(ticker.includes('KHC')) return '35.40';
  if(ticker.includes('IVV')) return '410.25';
  if(ticker.includes('IEMG')) return '48.90';
  if(ticker.includes('META')) return '245.50';
  if(ticker.includes('GOOGL')) return '125.80';
  if(ticker.includes('NVO')) return '85.20';
  if(ticker.includes('VRTX')) return '290.40';
  if(ticker.includes('PLTR')) return '18.50';
  if(ticker.includes('ARM')) return '95.80';
  if(ticker.includes('RXRX')) return '8.50';
  if(ticker.includes('SOUN')) return '4.20';
  if(ticker.includes('CEG')) return '120.40';
  if(ticker.includes('VST')) return '65.20';
  if(ticker.includes('TSM')) return '95.50';
  if(ticker.includes('OKLO')) return '12.40';
  if(ticker.includes('CCJ')) return '42.80';
  if(ticker.includes('ASML')) return '760.50';
  if(ticker.includes('SMCI')) return '650.00';
  if(ticker.includes('SPY')) return '425.50';
  if(ticker.includes('QQQ')) return '365.20';
  if(ticker.includes('MSFT')) return '310.40';
  if(ticker.includes('NVDA')) return '450.80';
  if(ticker.includes('AMZN')) return '125.40';
  
  return avg;
}

content = content.replace(regex, (match, ticker, pct) => {
  const price = getAvgPrice(ticker);
  return `<div className="flex justify-between items-center"><div className="flex items-center gap-1.5"><span>${ticker}</span><span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium border border-slate-200">Avg $${price}</span></div><span className="text-slate-900">${pct}%</span></div>`;
});

fs.writeFileSync('src/App.tsx', content);

console.log('Patched average prices in 13F sections.');
