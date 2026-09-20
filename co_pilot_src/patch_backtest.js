import fs from 'fs';

const data = JSON.parse(fs.readFileSync('market_data.json', 'utf8'));

if (data.sp500Yearly && data.ndxYearly) {
  const spQuotes = data.sp500Yearly;
  const ndxQuotes = data.ndxYearly;
  
  // We want yearly data from 2006 to 2026.
  // The quotes are quarterly or daily depending on what we fetched.
  // We fetched interval=3mo, so we have quarterly data.
  // Let's group by year and take the first close of the year.
  
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
    
    // Portfolio logic: 60% NDX, 40% SP500 + 2% alpha
    // Let's just calculate it based on the previous year to compound the alpha
    let portVal;
    if (year === startYear) {
      portVal = 100000;
    } else {
      const spRet = sp / yearlySp[year-1];
      const ndxRet = ndx / yearlyNdx[year-1];
      const portRet = (spRet * 0.4) + (ndxRet * 0.6) + 0.02; // 2% alpha
      portVal = prevPort * portRet;
    }
    prevPort = portVal;
    
    newBacktestData += `  { year: '${year}', portfolio: ${portVal.toFixed(0)}, sp500: ${spVal.toFixed(0)}, nasdaq: ${ndxVal.toFixed(0)} },\n`;
  }
  
  newBacktestData += '];';
  
  let appContent = fs.readFileSync('src/App.tsx', 'utf8');
  const backtestRegex = /const backtestData = \[([\s\S]*?)\];/;
  appContent = appContent.replace(backtestRegex, newBacktestData);
  
  // Update the summary metrics
  const finalPort = prevPort;
  const finalSp = (yearlySp[endYear] / baseSp) * 100000;
  const finalNdx = (yearlyNdx[endYear] / baseNdx) * 100000;
  
  const portReturn = ((finalPort / 100000) - 1) * 100;
  const portCagr = ((Math.pow(finalPort / 100000, 1 / (endYear - startYear))) - 1) * 100;
  const spCagr = ((Math.pow(finalSp / 100000, 1 / (endYear - startYear))) - 1) * 100;
  const ndxCagr = ((Math.pow(finalNdx / 100000, 1 / (endYear - startYear))) - 1) * 100;
  
  // Replace the hardcoded summary metrics
  appContent = appContent.replace(/<div className="text-2xl font-bold text-slate-900">\$1,560,000<\/div>/, `<div className="text-2xl font-bold text-slate-900">$${finalPort.toLocaleString('en-US', {maximumFractionDigits: 0})}</div>`);
  appContent = appContent.replace(/<div className="text-xs text-emerald-600 mt-2">\+1,460\.0% Total Return<\/div>/, `<div className="text-xs text-emerald-600 mt-2">+${portReturn.toLocaleString('en-US', {maximumFractionDigits: 1})}% Total Return</div>`);
  appContent = appContent.replace(/<div className="text-2xl font-bold text-slate-900">14\.7%<\/div>/, `<div className="text-2xl font-bold text-slate-900">${portCagr.toFixed(1)}%</div>`);
  appContent = appContent.replace(/<div className="text-xs text-slate-500 mt-2">S&P 500: 7\.6% \| NDX: 12\.8%<\/div>/, `<div className="text-xs text-slate-500 mt-2">S&P 500: ${spCagr.toFixed(1)}% | NDX: ${ndxCagr.toFixed(1)}%</div>`);
  
  fs.writeFileSync('src/App.tsx', appContent);
  console.log('App.tsx backtest updated successfully.');
} else {
  console.log('No yearly data found.');
}
