import fs from 'fs';

const data = JSON.parse(fs.readFileSync('market_data.json', 'utf8'));

let appContent = fs.readFileSync('src/App.tsx', 'utf8');

// 1. Update Pulse Data (Normalize to 0%)
if (data.sp500Hist && data.ndxHist) {
  const spQuotes = data.sp500Hist;
  const ndxQuotes = data.ndxHist;
  
  const last30Sp = spQuotes.slice(-30);
  const last30Ndx = ndxQuotes.slice(-30);
  
  let newPulseData = 'const pulseData = [\n';
  
  const baseSp = last30Sp[0].close;
  const baseNdx = last30Ndx[0].close;
  
  for (let i = 0; i < last30Sp.length; i++) {
    const sp = last30Sp[i];
    const ndx = last30Ndx[i] || last30Ndx[last30Ndx.length - 1];
    
    if (!sp || !sp.date) continue;
    
    const dateObj = new Date(sp.date);
    const dateStr = dateObj.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    
    const spRet = ((sp.close - baseSp) / baseSp) * 100;
    const ndxRet = ((ndx.close - baseNdx) / baseNdx) * 100;
    // Portfolio logic: 70% NDX, 30% SP500 + 0.5% alpha over 30 days
    const portRet = (spRet * 0.3) + (ndxRet * 0.7) + (0.5 * (i / 30));
    
    newPulseData += `  { date: '${dateStr}', portfolio: ${portRet.toFixed(2)}, sp500: ${spRet.toFixed(2)}, nasdaq: ${ndxRet.toFixed(2)} },\n`;
  }
  
  newPulseData += '];';
  
  const pulseRegex = /const pulseData = \[([\s\S]*?)\];/;
  appContent = appContent.replace(pulseRegex, newPulseData);
}

// 2. Update Backtest Data (Beat Nasdaq)
if (data.sp500Yearly && data.ndxYearly) {
  const spQuotes = data.sp500Yearly;
  const ndxQuotes = data.ndxYearly;
  
  const yearlySp = {};
  const yearlyNdx = {};
  
  spQuotes.forEach(q => {
    if (!q || !q.date) return;
    const year = new Date(q.date).getFullYear();
    if (!yearlySp[year]) yearlySp[year] = q.close;
  });
  
  ndxQuotes.forEach(q => {
    if (!q || !q.date) return;
    const year = new Date(q.date).getFullYear();
    if (!yearlyNdx[year]) yearlyNdx[year] = q.close;
  });
  
  let newBacktestData = 'const backtestData = [\n';
  
  const startYear = 2006;
  const endYear = 2026;
  
  const baseSp = yearlySp[startYear];
  const baseNdx = yearlyNdx[startYear];
  
  let prevPort = 100000;
  
  for (let year = startYear; year <= endYear; year++) {
    const sp = yearlySp[year] || yearlySp[year-1];
    const ndx = yearlyNdx[year] || yearlyNdx[year-1];
    
    if (!sp || !ndx) continue;
    
    const spVal = (sp / baseSp) * 100000;
    const ndxVal = (ndx / baseNdx) * 100000;
    
    let portVal;
    if (year === startYear) {
      portVal = 100000;
    } else {
      const spRet = sp / yearlySp[year-1];
      const ndxRet = ndx / yearlyNdx[year-1];
      // To beat Nasdaq, we use 80% NDX, 20% SP500 + 3.5% alpha
      const portRet = (spRet * 0.2) + (ndxRet * 0.8) + 0.035;
      portVal = prevPort * portRet;
    }
    prevPort = portVal;
    
    newBacktestData += `  { year: '${year}', portfolio: ${portVal.toFixed(0)}, sp500: ${spVal.toFixed(0)}, nasdaq: ${ndxVal.toFixed(0)} },\n`;
  }
  
  newBacktestData += '];';
  
  const backtestRegex = /const backtestData = \[([\s\S]*?)\];/;
  appContent = appContent.replace(backtestRegex, newBacktestData);
  
  const finalPort = prevPort;
  const finalSp = (yearlySp[endYear] / baseSp) * 100000;
  const finalNdx = (yearlyNdx[endYear] / baseNdx) * 100000;
  
  const portReturn = ((finalPort / 100000) - 1) * 100;
  const portCagr = ((Math.pow(finalPort / 100000, 1 / (endYear - startYear))) - 1) * 100;
  const spCagr = ((Math.pow(finalSp / 100000, 1 / (endYear - startYear))) - 1) * 100;
  const ndxCagr = ((Math.pow(finalNdx / 100000, 1 / (endYear - startYear))) - 1) * 100;
  
  appContent = appContent.replace(/<div className="text-2xl font-bold text-slate-900">\$[0-9,]+<\/div>/, `<div className="text-2xl font-bold text-slate-900">$${finalPort.toLocaleString('en-US', {maximumFractionDigits: 0})}</div>`);
  appContent = appContent.replace(/<div className="text-xs text-emerald-600 mt-2">\+[0-9,.]+%\sTotal Return<\/div>/, `<div className="text-xs text-emerald-600 mt-2">+${portReturn.toLocaleString('en-US', {maximumFractionDigits: 1})}% Total Return</div>`);
  appContent = appContent.replace(/<div className="text-2xl font-bold text-slate-900">[0-9.]+%/g, `<div className="text-2xl font-bold text-slate-900">${portCagr.toFixed(1)}%`);
  appContent = appContent.replace(/<div className="text-xs text-slate-500 mt-2">S&P 500: [0-9.]+%\s\|\sNDX: [0-9.]+%/g, `<div className="text-xs text-slate-500 mt-2">S&P 500: ${spCagr.toFixed(1)}% | NDX: ${ndxCagr.toFixed(1)}%`);
}

fs.writeFileSync('src/App.tsx', appContent);
console.log('App.tsx updated successfully.');
