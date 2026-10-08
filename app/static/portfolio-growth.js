let growthChart = null;
async function loadPortfolioGrowth() {
  try {
    const data = await api('/api/portfolio-growth');
    const points = data.points;
    document.getElementById('growth-note').textContent = data.note;
    document.getElementById('growth-summary').textContent = points.length
      ? '$' + fmt(points[0].balance) + ' → $' + fmt(points[points.length - 1].balance) + ' · ' + points.length + ' recorded snapshots · includes capital flows'
      : 'No recorded paper balances yet. Run a historical replay to populate this chart.';
    if (growthChart) growthChart.destroy();
    growthChart = new Chart(document.getElementById('growthChart'), {
      type: 'line',
      data: {
        labels: points.map(p => new Date(p.timestamp).toLocaleString(undefined, {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit', timeZone:'UTC'})),
        datasets: [{label: 'Paper portfolio balance (USD)', data: points.map(p => p.balance), borderColor:'#22c55e', backgroundColor:'rgba(34,197,94,.12)', fill:true, tension:0.15, pointRadius:2}]
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
