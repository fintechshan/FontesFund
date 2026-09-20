import fs from 'fs';

const data = JSON.parse(fs.readFileSync('market_data.json', 'utf8'));

let appContent = fs.readFileSync('src/App.tsx', 'utf8');

// 1. Update Portfolio
const portfolioRegex = /const portfolio = \[([\s\S]*?)\];/;
const portfolioMatch = appContent.match(portfolioRegex);

if (portfolioMatch) {
  let portfolioContent = portfolioMatch[1];
  
  data.quotes.forEach(q => {
    // AAPL
    const symbol = q.symbol === 'BRK-B' ? 'BRK.B' : q.symbol;
    const regex = new RegExp(`{ ticker: '${symbol}'(.*?)(price: [\\d\\.]+)?(, low52: [\\d\\.]+)?(, high52: [\\d\\.]+)?(, reason: ".*?") }`, 'g');
    
    portfolioContent = portfolioContent.replace(regex, (match, p1, p2, p3, p4, p5) => {
      return `{ ticker: '${symbol}'${p1}price: ${q.price.toFixed(2)}, low52: ${q.low52.toFixed(2)}, high52: ${q.high52.toFixed(2)}${p5} }`;
    });
  });
  
  appContent = appContent.replace(portfolioRegex, `const portfolio = [${portfolioContent}];`);
}

// 2. Update Pulse Data
// We have sp500Hist and ndxHist. We need to generate pulseData.
// pulseData is an array of objects with date, portfolio, sp500, nasdaq.
// We will use the last 30 days of data.
if (data.sp500Hist && data.ndxHist) {
  const spQuotes = data.sp500Hist;
  const ndxQuotes = data.ndxHist;
  
  // Get last 30 trading days
  const last30Sp = spQuotes.slice(-30);
  const last30Ndx = ndxQuotes.slice(-30);
  
  let newPulseData = 'const pulseData = [\n';
  
  for (let i = 0; i < last30Sp.length; i++) {
    const sp = last30Sp[i];
    const ndx = last30Ndx[i] || last30Ndx[last30Ndx.length - 1]; // fallback if lengths differ
    
    if (!sp || !sp.date) continue;
    
    const dateObj = new Date(sp.date);
    const dateStr = dateObj.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    
    // Calculate portfolio value. Let's start at 1,300,000 and move it based on a blend of SP500 and NDX
    // Or just use the existing formula but scaled to the real data.
    // Actually, let's just make the portfolio track 50% SP500 and 50% NDX for the pulse chart.
    // Base portfolio value: 1,300,000
    // Base SP500: last30Sp[0].close
    // Base NDX: last30Ndx[0].close
    const spReturn = sp.close / last30Sp[0].close;
    const ndxReturn = ndx.close / last30Ndx[0].close;
    const portReturn = (spReturn * 0.4) + (ndxReturn * 0.6); // 60% NDX, 40% SP500
    const portValue = 1300000 * portReturn;
    
    newPulseData += `  { date: '${dateStr}', portfolio: ${portValue.toFixed(0)}, sp500: ${sp.close.toFixed(2)}, nasdaq: ${ndx.close.toFixed(2)} },\n`;
  }
  
  newPulseData += '];';
  
  const pulseRegex = /const pulseData = Array\.from\(\{ length: 30 \}, \(_, i\) => \{[\s\S]*?\}\);/;
  appContent = appContent.replace(pulseRegex, newPulseData);
}

fs.writeFileSync('src/App.tsx', appContent);
console.log('App.tsx updated successfully.');
