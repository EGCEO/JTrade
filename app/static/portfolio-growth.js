let growthChart = null;
async function loadPortfolioGrowth() {
  try {
    const data = await api('/api/portfolio-growth');
    const points = data.points;
    document.getElementById('growth-title').textContent = data.historical_dates
      ? 'Portfolio Growth & Compounding — 30-Day Simulation'
      : 'Portfolio Growth & Compounding — Recorded Paper Balances';
    document.getElementById('growth-note').textContent = data.note;
    const first = points.length ? points[0].balance : 0;
    const last = points.length ? points[points.length - 1].balance : 0;
    const change = last - first;
    const percent = first > 0 ? ' (' + (change >= 0 ? '+' : '') + fmt(change / first * 100) + '%)' : '';
    document.getElementById('growth-summary').textContent = points.length
      ? '$' + fmt(first) + ' → $' + fmt(last) + ' · Balance change: ' + (change >= 0 ? '+' : '') + '$' + fmt(change) + percent + ' · ' + points.length + ' snapshots'
      : 'No recorded paper balances yet. Run a historical replay to populate this chart.';
    if (growthChart) growthChart.destroy();
    growthChart = new Chart(document.getElementById('growthChart'), {
      type: 'line',
      data: {
        labels: points.map(p => new Date(p.timestamp).toLocaleString(undefined, {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit', timeZone:'UTC'})),
        datasets: [
          {label: 'Simulated working balance (USD)', data: points.map(p => p.balance), borderColor:'#22c55e', backgroundColor:'rgba(34,197,94,.12)', fill:true, tension:0, pointRadius:2},
          {label: 'Opening recorded balance', data: points.map(() => first), borderColor:'#8b95a7', borderDash:[6,4], pointRadius:0, fill:false}
        ]
      },
      options: {responsive:true, maintainAspectRatio:false, animation:false,
        scales: {x:{ticks:{maxTicksLimit:6}, title:{display:true,text:data.historical_dates ? 'Historical market date (UTC)' : 'Recorded execution time (UTC)'}}, y:{title:{display:true,text:'Portfolio balance (USD)'}}}
      }
    });
  } catch (error) {
    document.getElementById('growth-summary').textContent = 'Unable to load portfolio growth.';
    console.error(error);
  }
}
loadPortfolioGrowth();
setInterval(loadPortfolioGrowth, 15000);
