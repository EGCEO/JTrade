// ── Arbitrage Gods – SPA ───────────────────────────────────────────────────
const API = '/api';
let token = localStorage.getItem('acc_token') || '';
let currentPage = 'dashboard';

const navItems = [
  { id: 'dashboard',  label: 'Dashboard',     icon: '📊' },
  { id: 'active',     label: 'Active Trades',  icon: '⚡' },
  { id: 'wallet',     label: 'Wallet Connect', icon: '👛' },
  { id: 'capital',    label: 'Capital & Balances', icon: '💰' },
  { id: 'risk',       label: 'Live Risk Monitor', icon: '🛡️' },
  { id: 'performance',label: 'Performance',   icon: '📉' },
  { id: 'trades',     label: 'Trade History',  icon: '📋' },
  { id: 'compounding',label: 'Compounding & Tiers', icon: '📈' },
  { id: 'bots',       label: 'Bot Team Control', icon: '🤖' },
  { id: 'botlogs',    label: 'Bot Logs',      icon: '📜' },
  { id: 'learning',   label: 'Learning Engine', icon: '🧠' },
  { id: 'insights',   label: 'Insights',      icon: '💡' },
  { id: 'notifications', label: 'Notifications', icon: '🔔' },
  { id: 'onboarding', label: 'Onboarding',    icon: '✅' },
  { id: 'settings',   label: 'Settings',      icon: '⚙️' },
  { id: 'security',   label: 'Security',      icon: '🔐' },
  { id: 'guide',      label: 'Integration Guide', icon: '📖' },
];

// ── API helpers ─────────────────────────────────────────────────────────────
async function api(path, method = 'GET', body = null, isWebhook = false) {
  const opts = { method, headers: {} };
  if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  if (isWebhook) {
    const key = localStorage.getItem('acc_webhook_key') || 'dev-webhook-key';
    opts.headers['X-API-Key'] = key;
  } else if (token) {
    opts.headers['Authorization'] = `Bearer ${token}`;
  }
  const res = await fetch(`${API}${path}`, opts);
  if (res.status === 401 && !isWebhook) {
    token = '';
    localStorage.removeItem('acc_token');
    render();
    throw new Error('Unauthorized');
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

// ── Login ────────────────────────────────────────────────────────────────────
async function handleLogin(e) {
  e.preventDefault();
  const username = e.target.username.value;
  const password = e.target.password.value;
  try {
    const data = await api('/auth/login', 'POST', { username, password });
    token = data.token;
    localStorage.setItem('acc_token', token);
    currentPage = 'dashboard';
    render();
  } catch (err) {
    document.getElementById('login-error').textContent = err.message;
  }
}

function renderLogin() {
  document.getElementById('app').innerHTML = `
    <div class="login-wrap">
      <div class="login-card">
        <h1><span class="logo-dot" style="display:inline-block;width:12px;height:12px;border-radius:50%;background:var(--accent);box-shadow:0 0 10px var(--accent);margin-right:8px;vertical-align:middle;"></span>Arbitrage Gods</h1>
        <p>Hybrid Engine — Execution Control Plane</p>
        <form onsubmit="handleLogin(event)">
          <div class="form-group">
            <label>Username</label>
            <input name="username" type="text" placeholder="Username" required autofocus>
          </div>
          <div class="form-group">
            <label>Password</label>
            <input name="password" type="password" placeholder="Enter password" required>
          </div>
          <div id="login-error" style="color:var(--danger);font-size:12px;margin-bottom:12px;"></div>
          <button type="submit" class="btn btn-primary" style="width:100%;">Login</button>
        </form>
        <p style="margin-top:16px;font-size:11px;color:var(--text-dim);text-align:center;">
          Enter your credentials
        </p>
      </div>
    </div>`;
}

// ── Layout ───────────────────────────────────────────────────────────────────
function renderLayout(content) {
  const nav = navItems.map(n =>
    `<a class="nav-item ${n.id === currentPage ? 'active' : ''}" href="#${n.id}">
      <span class="nav-icon">${n.icon}</span> ${n.label}
    </a>`).join('');
  document.getElementById('app').innerHTML = `
    <div class="layout">
      <div class="sidebar">
        <div class="sidebar-logo"><span class="logo-dot"></span> Arbitrage Gods</div>
        <div class="sidebar-subtitle">Hybrid Engine — Execution Control Plane</div>
        ${nav}
        <div class="sidebar-spacer"></div>
        <div class="sidebar-footer">
          <a href="#" onclick="logout();return false;" style="color:var(--text-dim);text-decoration:none;">⏻ Logout</a>
        </div>
      </div>
      <div class="main">
        <div class="ticker-bar"><div class="ticker-track" id="tickerTrack"></div></div>
        <div class="topbar" id="topbar"><h2>${navItems.find(n => n.id === currentPage)?.label || ''}</h2></div>
        <div class="master-controls" id="masterControls"></div>
        <div class="content" id="page-content">${content}</div>
        <div class="disclaimer">
          <strong>⚠️ Risk Disclaimer:</strong> Not financial advice. Flash-loan and arbitrage strategies carry real risk of loss,
          including gas fees on failed transactions. Only use capital you can afford to lose. Paper Trading Mode is strongly
          recommended until the system is fully understood and tested.
        </div>
      </div>
    </div>`;
  // Populate master controls after render
  populateMasterControls();
}

// ── Master Controls Bar ──────────────────────────────────────────────────────
async function populateMasterControls() {
  const bar = document.getElementById('masterControls');
  if (!bar) return;
  try {
    const config = await api('/config');
    const isRunning = config.is_running;
    const isReal = config.real_mode;
    const isAggressive = config.aggressive_mode;
    const isCompounding = config.compounding_mode;
    bar.innerHTML = `
      <div class="mc-group">
        <button class="mc-btn mc-start ${isRunning?'active':''}" onclick="mcStart()" title="Start all bots">▶ Start</button>
        <button class="mc-btn mc-pause" onclick="mcPause()" title="Pause all bots">⏸ Pause</button>
        <button class="mc-btn mc-stop" onclick="mcStop()" title="Stop all bots">⏹ Stop</button>
        <button class="mc-btn mc-kill" onclick="activateKillSwitch()" title="Emergency Kill Switch">🛑 KILL</button>
      </div>
      <div class="mc-group">
        <div class="mc-toggle" title="Paper / Real mode">
          <div class="toggle ${isReal?'on danger':''}" onclick="toggleReal(${!isReal})"></div>
          <span>${isReal?'🔴 REAL':'🟢 PAPER'}</span>
        </div>
        <div class="mc-toggle" title="Aggressive mode">
          <div class="toggle ${isAggressive?'on warning':''}" onclick="toggleAggressive(${!isAggressive})"></div>
          <span>Aggressive</span>
        </div>
        <div class="mc-toggle" title="Auto-compound">
          <div class="toggle ${isCompounding?'on':''}" onclick="toggleCompounding(${!isCompounding})"></div>
          <span>Compound</span>
        </div>
      </div>
      <div class="mc-group">
        <span class="pill ${isRunning?'pill-running':'pill-offline'}">${isRunning?'● RUNNING':'● STOPPED'}</span>
      </div>`;
  } catch (e) { bar.innerHTML = ''; }
}

async function mcStart() { try { await api('/master/start','POST'); populateMasterControls(); } catch(e){alert(e.message);} }
async function mcPause() { try { await api('/master/pause','POST'); populateMasterControls(); } catch(e){alert(e.message);} }
async function mcStop() { try { await api('/master/stop','POST'); populateMasterControls(); } catch(e){alert(e.message);} }

function logout() {
  token = '';
  localStorage.removeItem('acc_token');
  render();
}

// ── Crypto Ticker ────────────────────────────────────────────────────────────
const TICKER_COINS = [
  { sym: 'BTC', price: '$82,646', change: '+2.25%' },
  { sym: 'ETH', price: '$2,485', change: '+2.64%' },
  { sym: 'SOL', price: '$110', change: '+2.67%' },
  { sym: 'BNB', price: '$740', change: '+2.41%' },
  { sym: 'TON', price: '$1.46', change: '+7.81%' },
  { sym: 'XRP', price: '$1.39', change: '+4.43%' },
  { sym: 'DOGE', price: '$0.085', change: '+3.54%' },
  { sym: 'LTC', price: '$63.56', change: '+3.45%' },
];

function populateTicker() {
  const track = document.getElementById('tickerTrack');
  if (!track) return;
  const items = [...TICKER_COINS, ...TICKER_COINS].map(c =>
    `<span class="ticker-item"><span class="tkr-name">${c.sym}</span><span class="tkr-price">${c.price}</span><span class="tkr-change">▲ ${c.change}</span></span>`
  ).join('');
  track.innerHTML = items;
}

// ── Dashboard ────────────────────────────────────────────────────────────────
async function renderDashboard() {
  const [account, opps, bots, mode, config] = await Promise.all([
    api('/account'), api('/opportunities?limit=20'), api('/bots'), api('/mode'), api('/config'),
  ]);
  const isAggressive = config.aggressive_mode;
  const isReal = config.real_mode;

  renderLayout(`
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">Paper Balance</div>
        <div class="stat-value">$${account.paper_balance.toFixed(2)}</div>
        <div class="stat-sub ${account.paper_return_pct >= 0 ? 'stat-positive' : 'stat-negative'}">
          ${account.paper_return_pct >= 0 ? '▲' : '▼'} ${account.paper_return_pct.toFixed(1)}% return
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Real Balance</div>
        <div class="stat-value">$${account.real_balance.toFixed(2)}</div>
        <div class="stat-sub ${account.real_return_pct >= 0 ? 'stat-positive' : 'stat-negative'}">
          ${account.real_return_pct >= 0 ? '▲' : '▼'} ${account.real_return_pct.toFixed(1)}% return
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Current Tier</div>
        <div class="stat-value">Tier ${mode.tier}</div>
        <div class="stat-sub muted">${mode.unlocked_networks.join(', ').toUpperCase()}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Min Profit Threshold</div>
        <div class="stat-value">$${mode.thresholds.min_profit.toFixed(2)}</div>
        <div class="stat-sub muted">${isAggressive ? 'Aggressive' : 'Normal'} mode</div>
      </div>
    </div>

    <div class="card">
      <div class="flex-between mb-0">
        <div class="card-title mb-0">Real-Time Profit & Trading Activity</div>
        <div style="display:flex;gap:12px;align-items:center;">
          <span style="font-size:11px;color:var(--success);">● Paper</span>
          <span style="font-size:11px;color:var(--danger);">● Real</span>
          <span class="pill pill-running" id="chartLiveBadge">live</span>
        </div>
      </div>
      <div class="chart-wrap" style="height:340px;"><canvas id="dashPerfChart"></canvas></div>
      <div style="display:flex;gap:24px;margin-top:12px;font-size:12px;color:var(--text-dim);">
        <span>Lines = cumulative P&L ($)</span>
        <span>Bars = trade count per interval</span>
      </div>
    </div>
    <div class="card">
      <div class="flex-between mb-0">
        <div class="card-title mb-0">Success Rate & System Learning</div>
        <div style="display:flex;gap:12px;align-items:center;">
          <span style="font-size:11px;color:var(--success);">● Paper Win Rate</span>
          <span style="font-size:11px;color:var(--danger);">● Real Win Rate</span>
          <span style="font-size:11px;color:#58a6ff;">● Patterns Learned</span>
        </div>
      </div>
      <div class="chart-wrap" style="height:300px;"><canvas id="dashWinRateChart"></canvas></div>
      <div style="display:flex;gap:24px;margin-top:12px;font-size:12px;color:var(--text-dim);">
        <span>Lines = rolling win rate (%)</span>
        <span>Bars = cumulative learned patterns</span>
      </div>
    </div>

    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">Paper Trades Today</div>
        <div class="stat-value">${account.paper_stats.daily.total_trades}</div>
        <div class="stat-sub ${account.paper_stats.daily.total_pnl>=0?'stat-positive':'stat-negative'}">${account.paper_stats.daily.total_pnl>=0?'+':''}$${account.paper_stats.daily.total_pnl.toFixed(2)} P&L</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Real Trades Today</div>
        <div class="stat-value">${account.real_stats.daily.total_trades}</div>
        <div class="stat-sub ${account.real_stats.daily.total_pnl>=0?'stat-positive':'stat-negative'}">${account.real_stats.daily.total_pnl>=0?'+':''}$${account.real_stats.daily.total_pnl.toFixed(2)} P&L</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Paper Win Rate</div>
        <div class="stat-value">${account.paper_stats.all.win_rate.toFixed(0)}%</div>
        <div class="stat-sub muted">${account.paper_stats.all.wins}W / ${account.paper_stats.all.losses}L</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Real Win Rate</div>
        <div class="stat-value">${account.real_stats.all.win_rate.toFixed(0)}%</div>
        <div class="stat-sub muted">${account.real_stats.all.wins}W / ${account.real_stats.all.losses}L</div>
      </div>
    </div>

    <div class="card">
      <div class="flex-between mb-0">
        <div class="card-title mb-0">Mode Controls</div>
      </div>
      <div style="display:flex;gap:24px;flex-wrap:wrap;align-items:center;margin-top:12px;">
        <div style="display:flex;align-items:center;gap:10px;">
          <div class="toggle ${isAggressive ? 'on warning' : ''}" onclick="toggleAggressive(${!isAggressive})"></div>
          <span>Aggressive Mode ${isAggressive ? '(ON)' : '(OFF)'}</span>
        </div>
        <div style="display:flex;align-items:center;gap:10px;">
          <div class="toggle ${isReal ? 'on danger' : ''}" onclick="toggleReal(${!isReal})"></div>
          <span>Real Execution ${isReal ? '(ON)' : '(OFF)'}</span>
        </div>
        <span class="pill ${isReal ? 'pill-real' : 'pill-paper'}">${isReal ? '🔴 LIVE' : '🟢 PAPER'}</span>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Live Priority-Sorted Opportunities (Top 20)</div>
      ${opps.length === 0 ? '<div class="empty-state">No opportunities detected yet. Waiting for Scanner Bot…</div>' : `
      <table>
        <thead><tr>
          <th>#</th><th>Pair</th><th>Network</th><th>Style</th><th>Net Profit</th>
          <th>Confidence</th><th>Hops</th><th>Status</th>
        </tr></thead>
        <tbody>
          ${opps.map((o, i) => `
            <tr>
              <td>${i + 1}</td>
              <td><strong>${o.pair}</strong></td>
              <td>${o.network}</td>
              <td><span class="pill ${o.style === 'flash_loan' ? 'pill-flash' : 'pill-inventory'}">${o.style}</span></td>
              <td class="profit-cell ${o.net_profit >= 20 ? 'profit-high' : o.net_profit > 0 ? 'profit-low' : 'profit-neg'}">$${o.net_profit.toFixed(2)}</td>
              <td>${o.confidence.toFixed(0)}%</td>
              <td>${o.hops}</td>
              <td><span class="pill pill-${o.status}">${o.status}</span></td>
            </tr>`).join('')}
        </tbody>
      </table>`}
    </div>

    <div class="card">
      <div class="card-title">Bot Status Overview</div>
      <div class="bot-grid">
        ${bots.map(b => `
          <div class="bot-card">
            <h3>${b.bot_name.charAt(0).toUpperCase() + b.bot_name.slice(1)} Bot <span class="pill pill-${b.status}">${b.status}</span></h3>
            <div class="bot-info">Last action: ${b.last_action || '—'}</div>
            <div class="bot-info">Heartbeat: ${b.last_heartbeat ? new Date(b.last_heartbeat).toLocaleTimeString() : '—'}</div>
            ${b.error_message ? `<div class="bot-info" style="color:var(--danger);">Error: ${b.error_message}</div>` : ''}
          </div>`).join('')}
      </div>
    </div>

    <div class="card">
      <div class="card-title">Net Profit Formula</div>
      <pre class="code-block"><code>Net Profit = Gross Profit – (DEX fees + Flash-loan fees + Gas cost + Slippage cost + Price Impact cost + Competition haircut)

Gross Profit = amountOut – amountIn</code></pre>
      <p style="margin-top:12px;font-size:13px;color:var(--text-dim);">
        Only opportunities with Net Profit above the current minimum threshold ($${mode.thresholds.min_profit.toFixed(2)}) are allowed.
        Opportunities are always sorted by Net Profit (highest first).
      </p>
    </div>
  `);
  updateTopbar(mode, config);

  // Render real-time profit & activity chart
  renderRealtimeChart();
  // Render win rate & learning chart
  renderWinRateChart();
}

let dashChartInstance = null;
let dashChartInterval = null;
let dashWinRateChart = null;
let dashWinRateInterval = null;

async function renderRealtimeChart() {
  let chartData;
  try {
    chartData = await api('/chart-data');
  } catch (e) { return; }

  const chartCtx = document.getElementById('dashPerfChart');
  if (!chartCtx) return;

  const hasData = chartData.paper.length > 0 || chartData.real.length > 0;
  if (!hasData) {
    chartCtx.parentElement.innerHTML = '<div class="empty-state">No trading data yet. Profit and activity will appear here once bots start executing trades.</div>';
    return;
  }

  // Build unified timeline from both series
  const allPoints = [
    ...chartData.paper.map(p => ({ ...p, mode: 'paper' })),
    ...chartData.real.map(p => ({ ...p, mode: 'real' })),
  ].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

  const labels = allPoints.map(p => new Date(p.timestamp).toLocaleTimeString());

  // Cumulative P&L: walk through all points, keeping running sum per mode
  let paperCum = 0, realCum = 0;
  const paperPnl = [];
  const realPnl = [];
  allPoints.forEach(p => {
    if (p.mode === 'paper') paperCum = p.cumulative_pnl;
    if (p.mode === 'real') realCum = p.cumulative_pnl;
    paperPnl.push(p.mode === 'paper' ? paperCum : null);
    realPnl.push(p.mode === 'real' ? realCum : null);
  });

  // Trade activity bars: count 1 per trade at its position
  const paperBars = allPoints.map(p => p.mode === 'paper' ? 1 : 0);
  const realBars = allPoints.map(p => p.mode === 'real' ? 1 : 0);

  if (dashChartInstance) dashChartInstance.destroy();

  dashChartInstance = new Chart(chartCtx, {
    data: {
      labels,
      datasets: [
        {
          type: 'bar', label: 'Paper Trades', data: paperBars,
          backgroundColor: 'rgba(63,185,80,.35)', borderColor: 'rgba(63,185,80,.6)',
          borderWidth: 1, yAxisID: 'y2', order: 3,
        },
        {
          type: 'bar', label: 'Real Trades', data: realBars,
          backgroundColor: 'rgba(248,81,73,.35)', borderColor: 'rgba(248,81,73,.6)',
          borderWidth: 1, yAxisID: 'y2', order: 3,
        },
        {
          type: 'line', label: 'Paper P&L ($)', data: paperPnl,
          borderColor: '#3fb950', backgroundColor: 'rgba(63,185,80,.08)',
          tension: .3, fill: true, yAxisID: 'y', order: 1,
          spanGaps: true, pointRadius: 2,
        },
        {
          type: 'line', label: 'Real P&L ($)', data: realPnl,
          borderColor: '#f85149', backgroundColor: 'rgba(248,81,73,.08)',
          tension: .3, fill: true, yAxisID: 'y', order: 2,
          spanGaps: true, pointRadius: 2,
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: '#e6edf3', boxWidth: 12 }},
        tooltip: {
          callbacks: {
            label: (ctx) => {
              if (ctx.dataset.type === 'bar') return null; // skip bar tooltips
              const val = ctx.parsed.y;
              return val === null ? null : `${ctx.dataset.label}: $${val.toFixed(2)}`;
            },
          },
        },
      },
      scales: {
        x: { ticks: { color: '#8b949e', maxTicksLimit: 8 }, stacked: true },
        y: { type: 'linear', position: 'left', ticks: { color: '#8b949e' },
             title: { display: true, text: 'Cumulative P&L ($)', color: '#8b949e', font: { size: 11 }}},
        y2: { type: 'linear', position: 'right', ticks: { color: '#8b949e', stepSize: 1 },
              title: { display: true, text: 'Trades', color: '#8b949e', font: { size: 11 }},
              min: 0, max: 2, grid: { drawOnChartArea: false }},
      },
    },
  });

  // Auto-refresh chart every 10 seconds
  if (dashChartInterval) clearInterval(dashChartInterval);
  dashChartInterval = setInterval(async () => {
    if (currentPage === 'dashboard') {
      try { await renderRealtimeChart(); } catch (e) {}
    } else {
      clearInterval(dashChartInterval);
    }
  }, 10000);
}

async function renderWinRateChart() {
  let data;
  try {
    data = await api('/performance/winrate');
  } catch (e) { return; }

  const ctx = document.getElementById('dashWinRateChart');
  if (!ctx) return;

  const hasData = (data.paper && data.paper.length > 0) || (data.real && data.real.length > 0);

  if (dashWinRateChart) { dashWinRateChart.destroy(); dashWinRateChart = null; }

  if (!hasData) {
    ctx.parentElement.innerHTML = '<div class="empty-state">No trade data yet. Win rate and learning progress will appear here once trades are executed.</div>';
    return;
  }

  // Build labels from the longer series
  const maxLen = Math.max(data.paper.length, data.real.length);
  const labels = Array.from({ length: maxLen }, (_, i) => `#${i + 1}`);

  const paperWR = data.paper.map(p => p.win_rate);
  const realWR = data.real.map(p => p.win_rate);

  // Patterns learned — align to trade index
  const patternData = [];
  const learnPts = data.learning || [];
  for (let i = 0; i < maxLen; i++) {
    // Find the latest learning point at or before this trade index
    const ts = i < data.paper.length ? data.paper[i].timestamp :
               (i < data.real.length ? data.real[i].timestamp : null);
    let count = 0;
    if (ts) {
      for (const lp of learnPts) {
        if (lp.timestamp <= ts) count = lp.patterns_learned;
      }
    }
    patternData.push(count);
  }

  if (dashWinRateChart) dashWinRateChart.destroy();

  dashWinRateChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          type: 'line', label: 'Paper Win Rate (%)', data: paperWR,
          borderColor: '#00ff94', backgroundColor: 'rgba(0,255,148,.08)',
          tension: .3, fill: false, yAxisID: 'y', spanGaps: true, pointRadius: 2,
        },
        {
          type: 'line', label: 'Real Win Rate (%)', data: realWR,
          borderColor: '#f85149', backgroundColor: 'rgba(248,81,73,.08)',
          tension: .3, fill: false, yAxisID: 'y', spanGaps: true, pointRadius: 2,
        },
        {
          type: 'bar', label: 'Patterns Learned', data: patternData,
          backgroundColor: 'rgba(88,166,255,.35)', borderColor: '#58a6ff',
          borderWidth: 1, yAxisID: 'y2', order: 3,
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: '#e6edf3', boxWidth: 12 } },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              if (ctx.dataset.type === 'bar') return `Patterns: ${ctx.parsed.y}`;
              return `${ctx.dataset.label}: ${ctx.parsed.y?.toFixed(1)}%`;
            },
          },
        },
      },
      scales: {
        x: { ticks: { color: '#8b949e', maxTicksLimit: 10 } },
        y: { type: 'linear', position: 'left', min: 0, max: 100,
             ticks: { color: '#8b949e' },
             title: { display: true, text: 'Win Rate (%)', color: '#8b949e', font: { size: 11 } } },
        y2: { type: 'linear', position: 'right', min: 0,
              ticks: { color: '#8b949e', stepSize: 1 },
              title: { display: true, text: 'Patterns', color: '#8b949e', font: { size: 11 } },
              grid: { drawOnChartArea: false } },
      },
    },
  });

  if (dashWinRateInterval) clearInterval(dashWinRateInterval);
  dashWinRateInterval = setInterval(async () => {
    if (currentPage === 'dashboard') {
      try { await renderWinRateChart(); } catch (e) {}
    } else {
      clearInterval(dashWinRateInterval);
    }
  }, 15000);
}

function updateTopbar(mode, config) {
  const topbar = document.getElementById('topbar');
  if (!topbar) return;
  const isReal = config.real_mode;
  const isAggressive = config.aggressive_mode;
  topbar.innerHTML = `
    <h2>${navItems.find(n => n.id === currentPage)?.label || ''}</h2>
    <span class="badge ${isReal ? 'badge-real' : 'badge-paper'}">
      <span class="badge-dot"></span> ${isReal ? 'REAL' : 'PAPER'}
    </span>
    ${isAggressive ? '<span class="badge badge-aggressive"><span class="badge-dot"></span> AGGRESSIVE</span>' : ''}
    <span class="badge badge-paper" style="background:rgba(88,166,255,.15);color:var(--accent);">
      <span class="badge-dot" style="background:var(--accent);"></span> Tier ${mode.tier}
    </span>`;
}

async function toggleAggressive(enabled) {
  try {
    await api('/mode/aggressive', 'POST', { enabled });
    renderDashboard();
  } catch (e) { alert(e.message); }
}

async function toggleReal(enabled) {
  if (enabled) {
    const confirmed = confirm(
      '⚠️ WARNING: You are about to enable REAL EXECUTION MODE.\n\n' +
      'This means external bots will execute real trades with real funds.\n\n' +
      'Type "I UNDERSTAND THE RISKS" in the next prompt to confirm.'
    );
    if (!confirmed) return;
    const confirmation = prompt('Type "I UNDERSTAND THE RISKS" to enable Real Execution:');
    if (confirmation !== 'I UNDERSTAND THE RISKS') {
      alert('Confirmation text did not match. Real mode not enabled.');
      return;
    }
  }
  try {
    await api('/mode/real', 'POST', { enabled, confirmation: enabled ? 'I UNDERSTAND THE RISKS' : null });
    renderDashboard();
  } catch (e) { alert(e.message); }
}

async function toggleCompounding(enabled) {
  try {
    await api('/mode/compounding', 'POST', { enabled });
    renderCompounding();
  } catch (e) { alert(e.message); }
}

// ── Settings ─────────────────────────────────────────────────────────────────
async function renderSettings() {
  const config = await api('/config');
  const fields = [
    ['starting_capital', 'Starting Capital ($)', 'number'],
    ['current_paper_balance', 'Current Paper Balance ($)', 'number'],
    ['current_real_balance', 'Current Real Balance ($)', 'number'],
    ['min_profit_normal', 'Min Profit — Normal ($)', 'number'],
    ['min_profit_aggressive', 'Min Profit — Aggressive ($)', 'number'],
    ['max_risk_normal', 'Max Risk per Trade — Normal (%)', 'number'],
    ['max_risk_aggressive', 'Max Risk per Trade — Aggressive (%)', 'number'],
    ['daily_loss_limit', 'Daily Loss Limit (%)', 'number'],
    ['max_open_exposure', 'Max Open Exposure (%)', 'number'],
    ['cex_fee_pct', 'CEX Fee (%)', 'number'],
    ['dex_fee_pct', 'DEX Fee (%)', 'number'],
    ['estimated_gas_usd', 'Estimated Gas (USD)', 'number'],
    ['slippage_pct', 'Slippage Estimate (%)', 'number'],
    ['flash_loan_fee_pct', 'Flash Loan Fee (%)', 'number'],
    ['transfer_cost_usd', 'Transfer Cost (USD)', 'number'],
    ['base_router', 'Base Universal Router', 'text'],
    ['eth_router', 'Ethereum Universal Router', 'text'],
  ];
  const formHtml = fields.map(([key, label, type]) => {
    let val = config[key];
    if (type === 'number' && typeof val === 'number') val = val;
    else if (type === 'number') val = Number(val) || 0;
    const step = key.includes('router') ? '' : (key.includes('pct') || key.includes('fee') ? '0.001' : '0.01');
    return `<div class="form-group">
      <label>${label}</label>
      <input name="${key}" type="${type}" value="${val}" step="${step}">
    </div>`;
  }).join('');

  renderLayout(`
    <div class="card">
      <div class="card-title">Trading Parameters & Risk Limits</div>
      <form onsubmit="saveSettings(event)">
        <div class="form-row">${formHtml.slice(0, 4 * formHtml.split('</div>').filter(Boolean).length / 17 * 4)}</div>
        <div style="columns:2;column-gap:16px;">${formHtml}</div>
        <button type="submit" class="btn btn-primary mt-16">Save Settings</button>
      </form>
    </div>
    <div class="card">
      <div class="card-title">Webhook API Key</div>
      <p class="muted" style="margin-bottom:12px;">External bots use this key in the <code>X-API-Key</code> header to push data.</p>
      <div class="form-group">
        <label>API Key</label>
        <input type="text" value="${config.webhook_api_key || ''}" readonly style="font-family:monospace;">
      </div>
    </div>
  `);
}

async function saveSettings(e) {
  e.preventDefault();
  const formData = new FormData(e.target);
  const settings = {};
  for (const [key, val] of formData.entries()) {
    const numKeys = ['starting_capital','current_paper_balance','current_real_balance',
      'min_profit_normal','min_profit_aggressive','max_risk_normal','max_risk_aggressive',
      'daily_loss_limit','max_open_exposure','cex_fee_pct','dex_fee_pct',
      'estimated_gas_usd','slippage_pct','flash_loan_fee_pct','transfer_cost_usd'];
    settings[key] = numKeys.includes(key) ? parseFloat(val) : val;
  }
  try {
    await api('/config', 'PUT', { settings });
    alert('Settings saved!');
  } catch (err) { alert('Error: ' + err.message); }
}

// ── Bot Control ──────────────────────────────────────────────────────────────
async function renderBots() {
  const [bots, logs] = await Promise.all([
    api('/bots'), api('/logs?limit=20').catch(() => [])
  ]);
  const botRoles = {
    scanner: '🔍 Finds raw opportunities on unlocked networks',
    quant: '🧮 Runs routing + net profit formula + risk checks',
    guardian: '🛡️ Simulates transactions, final risk check',
    execution: '⚡ Executes Guardian-approved opportunities',
  };
  renderLayout(`
    <div class="card">
      <div class="card-title">Four-Bot Team Control Panel</div>
      <p class="muted" style="margin-bottom:16px;">
        The dashboard manages four specialized external bots. Use pause/resume to control them.
        Heartbeats are pushed by the bots via the <code>/api/heartbeats</code> endpoint.
      </p>
      <div class="bot-grid">
        ${bots.map(b => `
          <div class="bot-card">
            <h3>${b.bot_name.charAt(0).toUpperCase() + b.bot_name.slice(1)} Bot
              <span class="pill pill-${b.status}">${b.status}</span>
            </h3>
            <div class="bot-info" style="font-size:11px;">${botRoles[b.bot_name] || ''}</div>
            <div class="bot-info"><strong>Last action:</strong> ${b.last_action || '—'}</div>
            <div class="bot-info"><strong>Heartbeat:</strong> ${b.last_heartbeat ? new Date(b.last_heartbeat).toLocaleString() : 'Never'}</div>
            ${b.error_message ? `<div class="bot-info" style="color:var(--danger);"><strong>Error:</strong> ${b.error_message}</div>` : ''}
            <div class="bot-actions">
              <button class="btn btn-sm" onclick="testHeartbeat('${b.bot_name}')">💓 Test Heartbeat</button>
              <button class="btn btn-sm" onclick="pauseBot('${b.bot_name}')">⏸ Pause</button>
              <button class="btn btn-sm" onclick="resumeBot('${b.bot_name}')">▶ Resume</button>
            </div>
          </div>`).join('')}
      </div>
    </div>
    <div class="card">
      <div class="card-title">API Endpoints (for external bots)</div>
      <table>
        <thead><tr><th>Method</th><th>Endpoint</th><th>Purpose</th></tr></thead>
        <tbody>
          <tr><td>GET</td><td><code>/api/test</code></td><td>Connectivity test</td></tr>
          <tr><td>GET</td><td><code>/api/status</code></td><td>Read mode, is_running, thresholds, risk limits, unlocked networks, network config</td></tr>
          <tr><td>GET</td><td><code>/api/mode</code></td><td>Read current mode (legacy)</td></tr>
          <tr><td>POST</td><td><code>/api/heartbeats</code></td><td>Push bot heartbeat (unified — bot name in body)</td></tr>
          <tr><td>POST</td><td><code>/api/opportunities</code></td><td>Push discovered/scored opportunities</td></tr>
          <tr><td>POST</td><td><code>/api/trades</code></td><td>Push trade results</td></tr>
          <tr><td>POST</td><td><code>/api/logs</code></td><td>Push log entries (info/warning/error)</td></tr>
          <tr><td>POST</td><td><code>/api/account/balance</code></td><td>Update paper/real balance</td></tr>
          <tr><td>POST</td><td><code>/api/bots/{name}/heartbeat</code></td><td>Push heartbeat (legacy)</td></tr>
        </tbody>
      </table>
      <p class="muted mt-16">Auth: <code>Authorization: Bearer BOT_SECRET</code> (preferred) or <code>X-API-Key: WEBHOOK_API_KEY</code> (legacy).</p>
    </div>
    <div class="card">
      <div class="card-title">Recent Bot Logs</div>
      ${logs.length === 0 ? '<div class="empty-state">No bot logs yet.</div>' : `
      <table>
        <thead><tr><th>Time</th><th>Bot</th><th>Level</th><th>Message</th></tr></thead>
        <tbody>
          ${logs.map(l => `
            <tr>
              <td>${l.timestamp ? new Date(l.timestamp).toLocaleString() : '—'}</td>
              <td><strong>${l.bot}</strong></td>
              <td><span class="log-level-${l.level}">${l.level.toUpperCase()}</span></td>
              <td>${l.message}</td>
            </tr>`).join('')}
        </tbody>
      </table>`}
    </div>
  `);
}

async function pauseBot(name) {
  try { await api(`/bots/${name}/pause`, 'POST'); renderBots(); } catch (e) { alert(e.message); }
}
async function resumeBot(name) {
  try { await api(`/bots/${name}/resume`, 'POST'); renderBots(); } catch (e) { alert(e.message); }
}
async function testHeartbeat(name) {
  try {
    await api(`/bots/${name}/test-heartbeat`, 'POST');
    renderBots();
  } catch (e) { alert(e.message); }
}

// ── Active Trades Board ──────────────────────────────────────────────────────
let activeRefreshInterval = null;
let activeFilter = 'all';
let selectedOppIds = new Set();
let pendingOppIds = [];

async function renderActive() {
  const data = await api('/active');
  pendingOppIds = data.pending_opportunities.map(o => o.id);
  selectedOppIds = new Set([...selectedOppIds].filter(id => pendingOppIds.includes(id)));

  const totalCount = data.counts.active_trades + data.counts.pending_opportunities + data.counts.waiting_confirmation;

  const filterTabsHtml = `
    <div class="filter-tabs">
      <button class="filter-tab ${activeFilter==='all'?'active':''}" onclick="setActiveFilter('all')">All <span class="filter-tab-count">${totalCount}</span></button>
      <button class="filter-tab ${activeFilter==='pending'?'active':''}" onclick="setActiveFilter('pending')">Pending <span class="filter-tab-count">${data.counts.pending_opportunities}</span></button>
      <button class="filter-tab ${activeFilter==='active'?'active':''}" onclick="setActiveFilter('active')">Active <span class="filter-tab-count">${data.counts.active_trades}</span></button>
      <button class="filter-tab ${activeFilter==='waiting'?'active':''}" onclick="setActiveFilter('waiting')">Waiting <span class="filter-tab-count">${data.counts.waiting_confirmation}</span></button>
    </div>`;

  // ── Active trades section ──
  let activeHtml = '';
  if (activeFilter === 'all' || activeFilter === 'active') {
    activeHtml = `
    <div class="card">
      <div class="flex-between mb-0">
        <div class="card-title mb-0">⚡ Active Trades — In Progress</div>
        <span class="pill pill-pending">Live</span>
      </div>
      ${data.active_trades.length === 0 ? '<div class="empty-state">No active trades in progress.</div>' : `
      <table>
        <thead><tr><th>Started</th><th>Mode</th><th>Pair</th><th>Network</th><th>Style</th><th>Expected Profit</th><th>Status</th></tr></thead>
        <tbody>
          ${data.active_trades.map(t => `
            <tr>
              <td>${t.created_at ? new Date(t.created_at).toLocaleTimeString() : '—'}</td>
              <td><span class="pill pill-${t.mode}">${t.mode}</span></td>
              <td><strong>${t.pair}</strong></td>
              <td>${t.network}</td>
              <td><span class="pill ${t.style==='flash_loan'?'pill-flash':'pill-inventory'}">${t.style}</span></td>
              <td>$${t.expected_profit.toFixed(2)}</td>
              <td><span class="pill pill-pending">⏳ executing</span></td>
            </tr>`).join('')}
        </tbody>
      </table>`}
    </div>`;
  }

  // ── Pending opportunities section with bulk actions ──
  let pendingHtml = '';
  if (activeFilter === 'all' || activeFilter === 'pending') {
    const allSelected = pendingOppIds.length > 0 && pendingOppIds.every(id => selectedOppIds.has(id));
    const bulkBarHtml = data.pending_opportunities.length > 0 ? `
      <div class="bulk-bar" id="bulkBar" style="${selectedOppIds.size > 0 ? '' : 'display:none;'}">
        <span class="selected-count"><span id="selectedCount">${selectedOppIds.size}</span> selected</span>
        <button class="btn btn-sm btn-primary" onclick="bulkApprove()">✓ Approve Selected</button>
        <button class="btn btn-sm btn-danger" onclick="bulkReject()">✕ Reject Selected</button>
        <button class="btn btn-sm" onclick="clearOppSelection()">Clear</button>
      </div>` : '';
    pendingHtml = `
    <div class="card">
      <div class="flex-between mb-0">
        <div class="card-title mb-0">📋 Pending Opportunities — Awaiting Your Review</div>
        ${data.pending_opportunities.length > 0 ? '<span class="muted" style="font-size:12px;">Select items to approve or reject in bulk</span>' : ''}
      </div>
      ${bulkBarHtml}
      ${data.pending_opportunities.length === 0 ? '<div class="empty-state">No pending opportunities. Scanner Bot will push them here.</div>' : `
      <table>
        <thead><tr>
          <th style="width:32px;"><input type="checkbox" class="cb" id="selectAllOpps" ${allSelected?'checked':''} onchange="toggleAllOpps(this.checked)"></th>
          <th>Pair</th><th>Network</th><th>Style</th><th>Net Profit</th><th>Confidence</th><th>Hops</th><th>Priority</th><th>Status</th>
        </tr></thead>
        <tbody>
          ${data.pending_opportunities.map(o => `
            <tr>
              <td><input type="checkbox" class="cb" ${selectedOppIds.has(o.id)?'checked':''} onchange="toggleOppSelection(${o.id}, this.checked)"></td>
              <td><strong>${o.pair}</strong></td>
              <td>${o.network}</td>
              <td><span class="pill ${o.style==='flash_loan'?'pill-flash':'pill-inventory'}">${o.style}</span></td>
              <td class="profit-cell ${o.net_profit>=20?'profit-high':o.net_profit>0?'profit-low':'profit-neg'}">$${o.net_profit.toFixed(2)}</td>
              <td>${o.confidence.toFixed(0)}%</td>
              <td>${o.hops}</td>
              <td>${o.priority_score.toFixed(0)}</td>
              <td><span class="pill pill-pending">pending</span></td>
            </tr>`).join('')}
        </tbody>
      </table>`}
    </div>`;
  }

  // ── Waiting confirmation section ──
  let waitingHtml = '';
  if (activeFilter === 'all' || activeFilter === 'waiting') {
    waitingHtml = `
    <div class="card">
      <div class="card-title">✅ Waiting for Confirmation — Approved & Ready</div>
      ${data.waiting_confirmation.length === 0 ? '<div class="empty-state">No opportunities awaiting confirmation. Approve pending opportunities above to make them available for execution.</div>' : `
      <table>
        <thead><tr><th>Pair</th><th>Network</th><th>Style</th><th>Net Profit</th><th>Confidence</th><th>Priority</th><th>Created</th><th>Status</th><th>Action</th></tr></thead>
        <tbody>
          ${data.waiting_confirmation.map(o => `
            <tr>
              <td><strong>${o.pair}</strong></td>
              <td>${o.network}</td>
              <td><span class="pill ${o.style==='flash_loan'?'pill-flash':'pill-inventory'}">${o.style}</span></td>
              <td class="profit-cell ${o.net_profit>=20?'profit-high':o.net_profit>0?'profit-low':'profit-neg'}">$${o.net_profit.toFixed(2)}</td>
              <td>${o.confidence.toFixed(0)}%</td>
              <td>${o.priority_score.toFixed(0)}</td>
              <td>${o.created_at ? new Date(o.created_at).toLocaleTimeString() : '—'}</td>
              <td><span class="pill pill-approved">approved</span></td>
              <td><button class="btn btn-sm btn-primary" onclick='openExecuteModal(${JSON.stringify(o)})'>⚡ Execute</button></td>
            </tr>`).join('')}
        </tbody>
      </table>`}
    </div>`;
  }

  renderLayout(`
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">Active Trades</div>
        <div class="stat-value">${data.counts.active_trades}</div>
        <div class="stat-sub muted">In-progress executions</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Pending Opportunities</div>
        <div class="stat-value">${data.counts.pending_opportunities}</div>
        <div class="stat-sub muted">Awaiting your review</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Waiting Confirmation</div>
        <div class="stat-value">${data.counts.waiting_confirmation}</div>
        <div class="stat-sub muted">Approved, ready to execute</div>
      </div>
    </div>
    ${filterTabsHtml}
    ${activeHtml}
    ${pendingHtml}
    ${waitingHtml}
  `);

  // Auto-refresh every 5 seconds while on this tab
  if (activeRefreshInterval) clearInterval(activeRefreshInterval);
  activeRefreshInterval = setInterval(() => {
    if (currentPage === 'active') renderActive();
    else clearInterval(activeRefreshInterval);
  }, 5000);
}

function setActiveFilter(f) { activeFilter = f; renderActive(); }

function toggleOppSelection(id, checked) {
  if (checked) selectedOppIds.add(id); else selectedOppIds.delete(id);
  const bar = document.getElementById('bulkBar');
  if (bar) bar.style.display = selectedOppIds.size > 0 ? 'flex' : 'none';
  const count = document.getElementById('selectedCount');
  if (count) count.textContent = selectedOppIds.size;
  const selectAll = document.getElementById('selectAllOpps');
  if (selectAll) selectAll.checked = pendingOppIds.length > 0 && pendingOppIds.every(i => selectedOppIds.has(i));
}

function toggleAllOpps(checked) {
  if (checked) pendingOppIds.forEach(id => selectedOppIds.add(id));
  else pendingOppIds.forEach(id => selectedOppIds.delete(id));
  document.querySelectorAll('input.cb').forEach(cb => { if (cb.id !== 'selectAllOpps') cb.checked = checked; });
  const bar = document.getElementById('bulkBar');
  if (bar) bar.style.display = selectedOppIds.size > 0 ? 'flex' : 'none';
  const count = document.getElementById('selectedCount');
  if (count) count.textContent = selectedOppIds.size;
}

function clearOppSelection() { selectedOppIds.clear(); renderActive(); }

async function bulkApprove() {
  if (selectedOppIds.size === 0) return;
  try {
    await api('/opportunities/bulk-approve', 'POST', { ids: [...selectedOppIds] });
    selectedOppIds.clear();
    renderActive();
  } catch (e) { alert(e.message); }
}

async function bulkReject() {
  if (selectedOppIds.size === 0) return;
  try {
    await api('/opportunities/bulk-reject', 'POST', { ids: [...selectedOppIds] });
    selectedOppIds.clear();
    renderActive();
  } catch (e) { alert(e.message); }
}

// ── 3-Step Confirmation Modal for Real Trade Execution ──────────────────────
let executeTargetOpp = null;
let confirmStep = 1;
let confirmCheckboxes = { risk1: false, risk2: false, risk3: false };

function openExecuteModal(opp) {
  executeTargetOpp = opp;
  confirmStep = 1;
  confirmCheckboxes = { risk1: false, risk2: false, risk3: false };
  renderExecuteModal();
}

function closeExecuteModal() {
  executeTargetOpp = null;
  const overlay = document.getElementById('execModalOverlay');
  if (overlay) overlay.remove();
}

function renderExecuteModal() {
  if (!executeTargetOpp) return;
  const o = executeTargetOpp;
  const isReal = document.querySelector('.badge-real') !== null;

  // Remove existing modal
  const existing = document.getElementById('execModalOverlay');
  if (existing) existing.remove();

  const steps = [
    `<div class="exec-step active">1</div><div class="exec-step-line"></div>
     <div class="exec-step ${confirmStep>=2?'active':''}">2</div><div class="exec-step-line"></div>
     <div class="exec-step ${confirmStep>=3?'active':''}">3</div>`
  ].join('');

  let content = '';

  if (confirmStep === 1) {
    content = `
      <h3 style="margin-bottom:16px;">Step 1 — Review Trade Details</h3>
      <div class="exec-detail-grid">
        <div class="exec-detail"><span class="exec-detail-label">Pair</span><span class="exec-detail-value">${o.pair}</span></div>
        <div class="exec-detail"><span class="exec-detail-label">Network</span><span class="exec-detail-value">${o.network.toUpperCase()}</span></div>
        <div class="exec-detail"><span class="exec-detail-label">Style</span><span class="exec-detail-value">${o.style}</span></div>
        <div class="exec-detail"><span class="exec-detail-label">Buy Venue</span><span class="exec-detail-value" style="font-family:monospace;font-size:11px;">${o.buy_venue}</span></div>
        <div class="exec-detail"><span class="exec-detail-label">Sell Venue</span><span class="exec-detail-value" style="font-family:monospace;font-size:11px;">${o.sell_venue}</span></div>
        <div class="exec-detail"><span class="exec-detail-label">Buy Price</span><span class="exec-detail-value">$${o.buy_price.toFixed(6)}</span></div>
        <div class="exec-detail"><span class="exec-detail-label">Sell Price</span><span class="exec-detail-value">$${o.sell_price.toFixed(6)}</span></div>
        <div class="exec-detail"><span class="exec-detail-label">Gross Profit</span><span class="exec-detail-value">$${o.gross_profit.toFixed(4)}</span></div>
        <div class="exec-detail"><span class="exec-detail-label">Est. Costs</span><span class="exec-detail-value">$${o.estimated_costs.toFixed(4)}</span></div>
        <div class="exec-detail"><span class="exec-detail-label">Net Profit</span><span class="exec-detail-value" style="color:var(--success);font-size:18px;">$${o.net_profit.toFixed(4)}</span></div>
        <div class="exec-detail"><span class="exec-detail-label">Confidence</span><span class="exec-detail-value">${o.confidence.toFixed(0)}%</span></div>
        <div class="exec-detail"><span class="exec-detail-label">Hops</span><span class="exec-detail-value">${o.hops}</span></div>
      </div>
      ${isReal ? `<div class="exec-warning">⚠️ REAL EXECUTION — Real funds will be used.</div>` : ''}
      <div class="exec-actions">
        <button class="btn" onclick="closeExecuteModal()">Cancel</button>
        <button class="btn btn-primary" onclick="confirmStep=2;renderExecuteModal()">Review & Continue →</button>
      </div>`;
  } else if (confirmStep === 2) {
    content = `
      <h3 style="margin-bottom:16px;">Step 2 — Acknowledge Risks</h3>
      <p class="muted" style="margin-bottom:16px;">Check all boxes to confirm you understand the risks:</p>
      <div class="exec-checkbox-list">
        <label class="exec-checkbox"><input type="checkbox" ${confirmCheckboxes.risk1?'checked':''} onchange="confirmCheckboxes.risk1=this.checked;renderExecuteModal()">
          I understand this trade uses <strong>${isReal ? 'REAL FUNDS' : 'simulated paper trading'}</strong> and ${isReal ? 'real' : 'no'} money is at risk.
        </label>
        <label class="exec-checkbox"><input type="checkbox" ${confirmCheckboxes.risk2?'checked':''} onchange="confirmCheckboxes.risk2=this.checked;renderExecuteModal()">
          I have reviewed the trade details and confirmed the opportunity is legitimate.
        </label>
        <label class="exec-checkbox"><input type="checkbox" ${confirmCheckboxes.risk3?'checked':''} onchange="confirmCheckboxes.risk3=this.checked;renderExecuteModal()">
          I accept that arbitrage trades can fail due to slippage, gas costs, network congestion, or liquidity changes.
        </label>
      </div>
      <div class="exec-actions">
        <button class="btn" onclick="confirmStep=1;renderExecuteModal()">← Back</button>
        <button class="btn btn-primary" ${(!confirmCheckboxes.risk1||!confirmCheckboxes.risk2||!confirmCheckboxes.risk3)?'disabled':''}
          onclick="${(confirmCheckboxes.risk1&&confirmCheckboxes.risk2&&confirmCheckboxes.risk3)?'confirmStep=3;renderExecuteModal()':''}">
          Acknowledge & Continue →</button>
      </div>`;
  } else if (confirmStep === 3) {
    content = `
      <h3 style="margin-bottom:16px;">Step 3 — Final Confirmation</h3>
      ${isReal ? `<div class="exec-warning" style="margin-bottom:16px;">
        🔴 FINAL WARNING: You are about to execute a <strong>REAL TRADE</strong> with real funds.<br>
        Pair: <strong>${o.pair}</strong> | Net Profit: <strong>$${o.net_profit.toFixed(4)}</strong>
      </div>` : ''}
      <p class="muted" style="margin-bottom:8px;">Type <code style="color:var(--accent);font-size:16px;">EXECUTE</code> below to confirm:</p>
      <div class="form-group" style="margin-bottom:16px;">
        <input type="text" id="execConfirmText" placeholder="Type EXECUTE here"
          oninput="document.getElementById('execFinalBtn').disabled = this.value !== 'EXECUTE'"
          style="text-align:center;font-size:18px;font-weight:700;letter-spacing:2px;" autofocus>
      </div>
      <div class="exec-actions">
        <button class="btn" onclick="confirmStep=2;renderExecuteModal()">← Back</button>
        <button class="btn btn-primary" id="execFinalBtn" disabled
          onclick="submitExecution()">Confirm & Execute</button>
      </div>`;
  }

  const overlay = document.createElement('div');
  overlay.id = 'execModalOverlay';
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal-card">
      <div class="modal-header">
        <span class="modal-title">Execute Trade — 3-Step Confirmation</span>
        <button class="modal-close" onclick="closeExecuteModal()">✕</button>
      </div>
      <div class="exec-steps">${steps}</div>
      ${content}
    </div>`;
  document.body.appendChild(overlay);

  // Focus input on step 3
  if (confirmStep === 3) {
    setTimeout(() => {
      const input = document.getElementById('execConfirmText');
      if (input) input.focus();
    }, 50);
  }
}

async function submitExecution() {
  if (!executeTargetOpp) return;
  const btn = document.getElementById('execFinalBtn');
  if (btn) { btn.disabled = true; btn.textContent = 'Executing...'; }
  try {
    const result = await api(`/opportunities/${executeTargetOpp.id}/execute`, 'POST', {
      confirmation_step1: true,
      confirmation_step2: true,
      confirmation_text: 'EXECUTE',
    });
    closeExecuteModal();
    if (result.status === 'success') {
      alert(`✅ Trade executed successfully!\nMode: ${result.mode}\nNet Result: $${result.net_result.toFixed(4)}`);
    } else {
      alert(`⚠️ Trade execution: ${result.status}\n${result.execution_result?.error || ''}`);
    }
    renderActive();
  } catch (e) {
    alert('Execution failed: ' + e.message);
    if (btn) { btn.disabled = false; btn.textContent = 'Confirm & Execute'; }
  }
}

// ── Trade History ────────────────────────────────────────────────────────────
let tradeFilter = 'all';
let tradeStatusFilter = 'all';
async function renderTrades() {
  let path = '/trades?limit=100';
  if (tradeFilter !== 'all') path += `&mode=${tradeFilter}`;
  if (tradeStatusFilter !== 'all') path += `&status=${tradeStatusFilter}`;
  const trades = await api(path);
  renderLayout(`
    <div class="filter-bar">
      <select onchange="tradeFilter=this.value;renderTrades()">
        <option value="all" ${tradeFilter==='all'?'selected':''}>All Modes</option>
        <option value="paper" ${tradeFilter==='paper'?'selected':''}>Paper Only</option>
        <option value="real" ${tradeFilter==='real'?'selected':''}>Real Only</option>
      </select>
      <select onchange="tradeStatusFilter=this.value;renderTrades()">
        <option value="all" ${tradeStatusFilter==='all'?'selected':''}>All Statuses</option>
        <option value="pending" ${tradeStatusFilter==='pending'?'selected':''}>Active (In-Progress)</option>
        <option value="success" ${tradeStatusFilter==='success'?'selected':''}>Finished — Success</option>
        <option value="failed" ${tradeStatusFilter==='failed'?'selected':''}>Finished — Failed</option>
        <option value="skipped" ${tradeStatusFilter==='skipped'?'selected':''}>Finished — Skipped</option>
      </select>
    </div>
    <div class="card">
      <div class="card-title">Trade History & Execution Log</div>
      ${trades.length === 0 ? '<div class="empty-state">No trades logged yet.</div>' : `
      <table>
        <thead><tr>
          <th>Time</th><th>Mode</th><th>Style</th><th>Network</th><th>Pair</th>
          <th>Expected</th><th>Actual</th><th>Status</th><th>Net Result</th>
        </tr></thead>
        <tbody>
          ${trades.map(t => `
            <tr>
              <td>${t.created_at ? new Date(t.created_at).toLocaleString() : '—'}</td>
              <td><span class="pill pill-${t.mode}">${t.mode}</span></td>
              <td><span class="pill ${t.style==='flash_loan'?'pill-flash':'pill-inventory'}">${t.style}</span></td>
              <td>${t.network}</td>
              <td><strong>${t.pair}</strong></td>
              <td>$${t.expected_profit.toFixed(2)}</td>
              <td>$${t.actual_profit.toFixed(2)}</td>
              <td><span class="pill pill-${t.status==='success'?'executed':t.status==='failed'?'error':'pending'}">${t.status}</span></td>
              <td class="profit-cell ${t.net_result>0?'profit-high':t.net_result<0?'profit-neg':'profit-low'}">$${t.net_result.toFixed(2)}</td>
            </tr>`).join('')}
        </tbody>
      </table>`}
    </div>
  `);
}

// ── Compounding & Tiers ──────────────────────────────────────────────────────
async function renderCompounding() {
  const [account, tiers, snapshots, config] = await Promise.all([
    api('/account'), api('/tiers'), api('/account/snapshots?limit=50'), api('/config'),
  ]);
  const isCompounding = config.compounding_mode;
  renderLayout(`
    <div class="card">
      <div class="flex-between mb-0">
        <div class="card-title mb-0">Compounding Mode</div>
      </div>
      <div style="display:flex;gap:24px;flex-wrap:wrap;align-items:center;margin-top:12px;">
        <div style="display:flex;align-items:center;gap:10px;">
          <div class="toggle ${isCompounding ? 'on' : ''}" onclick="toggleCompounding(${!isCompounding})"></div>
          <span>Compounding Profit ${isCompounding ? '(ON)' : '(OFF)'}</span>
        </div>
        <span class="pill ${isCompounding ? 'pill-approved' : 'pill-offline'}">${isCompounding ? '📈 REINVESTING' : '⏸ WITHDRAWABLE'}</span>
        <span class="muted" style="font-size:12px;">When ON, profits are reinvested into the trading balance. When OFF, profits remain withdrawable.</span>
      </div>
    </div>

    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">Starting Capital</div>
        <div class="stat-value">$${account.starting_capital.toFixed(2)}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Paper Balance</div>
        <div class="stat-value">$${account.paper_balance.toFixed(2)}</div>
        <div class="stat-sub ${account.paper_return_pct>=0?'stat-positive':'stat-negative'}">${account.paper_return_pct.toFixed(1)}% return</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Real Balance</div>
        <div class="stat-value">$${account.real_balance.toFixed(2)}</div>
        <div class="stat-sub ${account.real_return_pct>=0?'stat-positive':'stat-negative'}">${account.real_return_pct.toFixed(1)}% return</div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Compounding Performance</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;">
        <div>
          <h4 style="margin-bottom:8px;">Paper Trading</h4>
          <div class="bot-info">All-time P&L: $${account.paper_stats.all.total_pnl.toFixed(2)}</div>
          <div class="bot-info">Win rate: ${account.paper_stats.all.win_rate.toFixed(1)}%</div>
          <div class="bot-info">Total trades: ${account.paper_stats.all.total_trades}</div>
          <div class="bot-info">Daily P&L: $${account.paper_stats.daily.total_pnl.toFixed(2)}</div>
          <div class="bot-info">Weekly P&L: $${account.paper_stats.weekly.total_pnl.toFixed(2)}</div>
        </div>
        <div>
          <h4 style="margin-bottom:8px;">Real Trading</h4>
          <div class="bot-info">All-time P&L: $${account.real_stats.all.total_pnl.toFixed(2)}</div>
          <div class="bot-info">Win rate: ${account.real_stats.all.win_rate.toFixed(1)}%</div>
          <div class="bot-info">Total trades: ${account.real_stats.all.total_trades}</div>
          <div class="bot-info">Daily P&L: $${account.real_stats.daily.total_pnl.toFixed(2)}</div>
          <div class="bot-info">Weekly P&L: $${account.real_stats.weekly.total_pnl.toFixed(2)}</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Balance History</div>
      <div class="chart-wrap"><canvas id="balanceChart"></canvas></div>
    </div>

    <div class="card">
      <div class="card-title">Tier Progress</div>
      <div style="margin-bottom:12px;">
        <div class="flex-between">
          <span><strong>${tiers.current_tier_name}</strong></span>
          <span class="muted">${tiers.next_tier ? 'Next: ' + tiers.next_tier : 'Max tier reached'}</span>
        </div>
        <div class="progress-bar"><div class="progress-fill" style="width:${tiers.progress_to_next}%"></div></div>
        <div class="muted" style="font-size:12px;">${tiers.next_tier_requirement}</div>
      </div>
      <div class="tier-list">
        ${tiers.all_tiers.map(t => `
          <div class="tier-item ${t.level===tiers.current_tier?'current':t.level>tiers.current_tier?'locked':''}">
            <div class="tier-num">${t.level}</div>
            <div>
              <div><strong>${t.name}</strong></div>
              <div class="muted" style="font-size:12px;">${t.description} — Networks: ${t.networks.join(', ')}</div>
            </div>
          </div>`).join('')}
      </div>
    </div>
  `);

  // Balance chart
  if (snapshots.length > 0) {
    const ctx = document.getElementById('balanceChart');
    if (ctx) {
      const paperSnaps = snapshots.filter(s => s.mode === 'paper').reverse();
      const realSnaps = snapshots.filter(s => s.mode === 'real').reverse();
      new Chart(ctx, {
        type: 'line',
        data: {
          labels: paperSnaps.map(s => new Date(s.timestamp).toLocaleDateString()),
          datasets: [
            { label: 'Paper', data: paperSnaps.map(s => s.balance), borderColor: '#3fb950', tension: .3, fill: false },
            { label: 'Real', data: realSnaps.map(s => s.balance), borderColor: '#f85149', tension: .3, fill: false },
          ],
        },
        options: { responsive: true, plugins: { legend: { labels: { color: '#e6edf3' }}}, scales: {
          x: { ticks: { color: '#8b949e' }}, y: { ticks: { color: '#8b949e' }}
        }},
      });
    }
  }
}

// ── Performance Dashboard (side-by-side charts) ──────────────────────────────
let perfChartPaper = null;
let perfChartReal = null;

async function renderPerformance() {
  const [perf, summary, execStatus] = await Promise.all([
    api('/performance'), api('/summary'), api('/execution/status').catch(() => null),
  ]);

  const pStats = perf.paper.stats;
  const rStats = perf.real.stats;

  renderLayout(`
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">Paper Total P&L</div>
        <div class="stat-value ${pStats.total_pnl>=0?'profit-high':'profit-neg'}">$${pStats.total_pnl.toFixed(2)}</div>
        <div class="stat-sub muted">${pStats.total_trades} trades · ${pStats.win_rate}% win rate</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Real Total P&L</div>
        <div class="stat-value ${rStats.total_pnl>=0?'profit-high':'profit-neg'}">$${rStats.total_pnl.toFixed(2)}</div>
        <div class="stat-sub muted">${rStats.total_trades} trades · ${rStats.win_rate}% win rate</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Combined P&L</div>
        <div class="stat-value ${(pStats.total_pnl+rStats.total_pnl)>=0?'profit-high':'profit-neg'}">$${(pStats.total_pnl+rStats.total_pnl).toFixed(2)}</div>
        <div class="stat-sub muted">${pStats.total_trades+rStats.total_trades} total trades</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Execution Engine</div>
        <div class="stat-value" style="font-size:16px;">${execStatus?.configured?'🟢 Ready':'🟡 Not Configured'}</div>
        <div class="stat-sub muted">${execStatus?.connected?'Connected':'Disconnected'} · ${execStatus?.network||'—'}</div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Side-by-Side Performance Comparison</div>
      <div class="perf-dual-chart">
        <div class="perf-chart-col">
          <h4 style="margin-bottom:8px;color:var(--success);">📄 Paper Trading</h4>
          <div class="chart-wrap" style="height:280px;"><canvas id="perfChartPaper"></canvas></div>
        </div>
        <div class="perf-chart-col">
          <h4 style="margin-bottom:8px;color:var(--danger);">🔴 Real Trading</h4>
          <div class="chart-wrap" style="height:280px;"><canvas id="perfChartReal"></canvas></div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Detailed P&L Summary</div>
      <div class="perf-dual-chart">
        <div class="perf-chart-col">
          <h4 style="margin-bottom:12px;color:var(--success);">📄 Paper Trading Summary</h4>
          ${renderSummaryBlock(summary.paper)}
        </div>
        <div class="perf-chart-col">
          <h4 style="margin-bottom:12px;color:var(--danger);">🔴 Real Trading Summary</h4>
          ${renderSummaryBlock(summary.real)}
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Combined Performance</div>
      <div class="stat-grid" style="margin-bottom:0;">
        <div class="stat-card">
          <div class="stat-label">Total P&L (Paper + Real)</div>
          <div class="stat-value ${summary.combined.total_pnl>=0?'profit-high':'profit-neg'}">$${summary.combined.total_pnl.toFixed(2)}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Total Trades</div>
          <div class="stat-value">${summary.combined.total_trades}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Total Fees Paid</div>
          <div class="stat-value">$${summary.combined.total_fees.toFixed(2)}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Total Gas Paid</div>
          <div class="stat-value">$${summary.combined.total_gas.toFixed(2)}</div>
        </div>
      </div>
    </div>

    ${execStatus ? `
    <div class="card">
      <div class="card-title">Real Execution Engine Status</div>
      <div class="stat-grid" style="margin-bottom:0;">
        <div class="stat-card">
          <div class="stat-label">Wallet Address</div>
          <div class="stat-value" style="font-size:13px;font-family:monospace;word-break:break-all;">${execStatus.wallet_address || 'Not set'}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Wallet Balance (ETH)</div>
          <div class="stat-value">${execStatus.balance.toFixed(6)}</div>
          <div class="stat-sub muted">${execStatus.network}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Private Key</div>
          <div class="stat-value" style="font-size:16px;">${execStatus.private_key_set?'✅ Set':'❌ Missing'}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Engine Status</div>
          <div class="stat-value" style="font-size:16px;">${execStatus.configured?'✅ Ready':'⚠️ Incomplete'}</div>
          <div class="stat-sub muted">${execStatus.connected?'RPC Connected':'RPC Disconnected'}</div>
        </div>
      </div>
      ${!execStatus.configured ? `
        <div class="exec-warning" style="margin-top:16px;">
          ⚠️ Real execution requires <code>PRIVATE_KEY</code> and <code>WALLET_ADDRESS</code> to be set in the
          <a href="#" onclick="currentPage='settings';render();return false;" style="color:var(--accent);">Secrets</a> page.
          The wallet address must match the private key owner.
        </div>` : ''}
    </div>` : ''}
  `);

  // Render side-by-side charts
  renderPerfCharts(perf);
}

function renderSummaryBlock(s) {
  return `
    <div class="summary-grid">
      <div class="summary-item"><span class="summary-label">Starting Capital</span><span class="summary-value">$${s.starting_capital.toFixed(2)}</span></div>
      <div class="summary-item"><span class="summary-label">Current Balance</span><span class="summary-value">$${s.current_balance.toFixed(2)}</span></div>
      <div class="summary-item"><span class="summary-label">Return %</span><span class="summary-value ${s.return_pct>=0?'profit-high':'profit-neg'}">${s.return_pct>=0?'+':''}${s.return_pct.toFixed(1)}%</span></div>
      <div class="summary-item"><span class="summary-label">Total P&L</span><span class="summary-value ${s.total_pnl>=0?'profit-high':'profit-neg'}">$${s.total_pnl.toFixed(2)}</span></div>
      <div class="summary-item"><span class="summary-label">Wins</span><span class="summary-value profit-high">${s.wins}</span></div>
      <div class="summary-item"><span class="summary-label">Losses</span><span class="summary-value profit-neg">${s.losses}</span></div>
      <div class="summary-item"><span class="summary-label">Win Rate</span><span class="summary-value">${s.win_rate}%</span></div>
      <div class="summary-item"><span class="summary-label">Avg Profit</span><span class="summary-value">$${s.avg_profit.toFixed(4)}</span></div>
      <div class="summary-item"><span class="summary-label">Total Fees</span><span class="summary-value">$${s.total_fees.toFixed(2)}</span></div>
      <div class="summary-item"><span class="summary-label">Total Gas</span><span class="summary-value">$${s.total_gas.toFixed(2)}</span></div>
      ${s.best_trade ? `<div class="summary-item"><span class="summary-label">Best Trade</span><span class="summary-value profit-high">${s.best_trade.pair} +$${s.best_trade.profit.toFixed(2)}</span></div>` : ''}
      ${s.worst_trade ? `<div class="summary-item"><span class="summary-label">Worst Trade</span><span class="summary-value profit-neg">${s.worst_trade.pair} -$${Math.abs(s.worst_trade.profit).toFixed(2)}</span></div>` : ''}
    </div>`;
}

function renderPerfCharts(perf) {
  // Paper chart
  const paperCanvas = document.getElementById('perfChartPaper');
  if (paperCanvas) {
    const paperData = perf.paper.series;
    if (perfChartPaper) perfChartPaper.destroy();
    if (paperData.length === 0) {
      paperCanvas.parentElement.innerHTML = '<div class="empty-state" style="padding:24px;">No paper trades yet</div>';
    } else {
      perfChartPaper = new Chart(paperCanvas, {
        type: 'line',
        data: {
          labels: paperData.map(p => `#${p.index}`),
          datasets: [{
            label: 'Cumulative P&L ($)',
            data: paperData.map(p => p.cumulative_pnl),
            borderColor: '#00ff94',
            backgroundColor: 'rgba(0,255,148,.08)',
            tension: .3, fill: true, pointRadius: 2,
          }],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { labels: { color: '#e6edf3', boxWidth: 10 }}},
          scales: {
            x: { ticks: { color: '#8b949e', maxTicksLimit: 6 }},
            y: { ticks: { color: '#8b949e' },
                 title: { display: true, text: 'P&L ($)', color: '#8b949e', font: { size: 10 }}},
          },
        },
      });
    }
  }

  // Real chart
  const realCanvas = document.getElementById('perfChartReal');
  if (realCanvas) {
    const realData = perf.real.series;
    if (perfChartReal) perfChartReal.destroy();
    if (realData.length === 0) {
      realCanvas.parentElement.innerHTML = '<div class="empty-state" style="padding:24px;">No real trades yet</div>';
    } else {
      perfChartReal = new Chart(realCanvas, {
        type: 'line',
        data: {
          labels: realData.map(p => `#${p.index}`),
          datasets: [{
            label: 'Cumulative P&L ($)',
            data: realData.map(p => p.cumulative_pnl),
            borderColor: '#ff4757',
            backgroundColor: 'rgba(255,71,87,.08)',
            tension: .3, fill: true, pointRadius: 2,
          }],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { labels: { color: '#e6edf3', boxWidth: 10 }}},
          scales: {
            x: { ticks: { color: '#8b949e', maxTicksLimit: 6 }},
            y: { ticks: { color: '#8b949e' },
                 title: { display: true, text: 'P&L ($)', color: '#8b949e', font: { size: 10 }}},
          },
        },
      });
    }
  }
}

// ── Insights ──────────────────────────────────────────────────────────────────
async function renderInsights() {
  const insights = await api('/insights');
  renderLayout(`
    <div class="card">
      <div class="card-title">Performance Insights</div>
      <p class="muted" style="margin-bottom:16px;">
        Data-driven observations from executed trades. These insights help improve rules over time.
        The system does not change strategy autonomously — insights are for human review.
      </p>
      ${insights.length === 0 ? '<div class="empty-state">No insights yet — execute some trades to generate data.</div>' : `
      <table>
        <thead><tr><th>Type</th><th>Pair / Network</th><th>Metric</th><th>Value</th><th>Notes</th></tr></thead>
        <tbody>
          ${insights.map(i => `
            <tr>
              <td>${i.insight_type.replace(/_/g,' ')}</td>
              <td>${i.pair || i.network || '—'}</td>
              <td>${i.metric.replace(/_/g,' ')}</td>
              <td><strong>${typeof i.value === 'number' ? i.value.toFixed(2) : i.value}</strong></td>
              <td class="muted">${i.notes}</td>
            </tr>`).join('')}
        </tbody>
      </table>`}
    </div>
  `);
}

// ── Learning Engine ───────────────────────────────────────────────────────────
let learningAnalysis = null;

async function renderLearning() {
  // Try cached patterns first, then fetch status
  const [status, patterns, recommendations] = await Promise.all([
    api('/learning/status'),
    api('/learning/patterns').catch(() => []),
    api('/learning/recommendations').catch(() => []),
  ]);

  const hasData = status.total_trades_analyzed > 0;

  // Group patterns by dimension
  const dims = {};
  patterns.forEach(p => {
    if (!dims[p.dimension]) dims[p.dimension] = [];
    dims[p.dimension].push(p);
  });
  // Sort each dimension by win rate descending
  Object.keys(dims).forEach(d => dims[d].sort((a, b) => b.win_rate - a.win_rate));

  const dimLabels = {
    pair: 'Pair Performance',
    network: 'Network Performance',
    style: 'Strategy Style',
    time_of_day: 'Time of Day (UTC)',
    hop_count: 'Route Hops',
    expected_profit_signal: 'Profit Signal',
  };

  const priorityColors = {
    high: 'pill-error', medium: 'pill-pending', low: 'pill-approved',
    info: 'pill-running', warning: 'pill-error',
  };

  renderLayout(`
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">Trades Analyzed</div>
        <div class="stat-value">${status.total_trades_analyzed}</div>
        <div class="stat-sub muted">${status.learning_active ? 'Learning active' : 'Needs 3+ trades to start'}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Patterns Found</div>
        <div class="stat-value">${status.patterns_cached}</div>
        <div class="stat-sub muted">Across ${Object.keys(dims).length} dimensions</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Recommendations</div>
        <div class="stat-value">${status.recommendations_cached}</div>
        <div class="stat-sub muted">Actionable insights</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Learning Status</div>
        <div class="stat-value" style="font-size:16px;">${status.learning_active ? '🧠 Active' : '⏳ Warming Up'}</div>
        <div class="stat-sub muted">Min ${status.min_sample_for_reliability} samples per pattern</div>
      </div>
    </div>

    <div class="card">
      <div class="flex-between mb-0">
        <div class="card-title mb-0">Pattern Learning Engine</div>
        <button class="btn btn-primary" id="analyzeBtn" onclick="runLearningAnalysis()">🔄 Re-Analyze Trades</button>
      </div>
      <p class="muted" style="margin-top:12px;margin-bottom:16px;">
        The engine analyzes historical trade outcomes to identify which conditions (pairs, networks, time windows,
        route complexity) correlate with profitable executions. Learned patterns automatically adjust confidence
        and priority scores on new opportunities — the system gets smarter as it accumulates trade data.
      </p>
      ${!hasData ? '<div class="empty-state">No trade data yet. Execute some trades (paper or real) and the engine will begin learning from the outcomes.</div>' : ''}
    </div>

    ${recommendations.length > 0 ? `
    <div class="card">
      <div class="card-title">🎯 Recommendations</div>
      <div style="display:flex;flex-direction:column;gap:12px;">
        ${recommendations.map(r => `
          <div style="border-left:3px solid var(--accent);padding:12px 16px;background:rgba(255,255,255,.03);border-radius:0 8px 8px 0;">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
              <span class="pill ${priorityColors[r.priority] || 'pill-pending'}">${r.priority.toUpperCase()}</span>
              <strong>${r.title}</strong>
            </div>
            <div class="muted" style="font-size:13px;">${r.detail}</div>
          </div>`).join('')}
      </div>
    </div>` : ''}

    ${hasData && Object.keys(dims).length > 0 ? Object.entries(dims).map(([dim, pats]) => `
    <div class="card">
      <div class="card-title">${dimLabels[dim] || dim}</div>
      <table>
        <thead><tr>
          <th>${dim === 'time_of_day' ? 'Time Window' : dim === 'hop_count' ? 'Hops' : 'Key'}</th>
          <th>Trades</th><th>Win Rate</th><th>Avg Profit</th><th>Total P&L</th><th>vs Baseline</th><th>Reliable</th>
        </tr></thead>
        <tbody>
          ${pats.map(p => `
            <tr>
              <td><strong>${p.label || p.key}</strong></td>
              <td>${p.sample_size}</td>
              <td class="${p.win_rate >= 60 ? 'profit-high' : p.win_rate < 40 ? 'profit-neg' : 'profit-low'}">${p.win_rate.toFixed(1)}%</td>
              <td>$${p.avg_profit.toFixed(4)}</td>
              <td class="${p.total_pnl >= 0 ? 'profit-high' : 'profit-neg'}">$${p.total_pnl.toFixed(2)}</td>
              <td class="${p.deviation >= 0 ? 'profit-high' : 'profit-neg'}">${p.deviation >= 0 ? '+' : ''}${p.deviation.toFixed(1)}%</td>
              <td>${p.reliable ? '✅' : '⏳'}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`).join('') : ''}

    <div class="disclaimer">
      <strong>🧠 How Learning Works:</strong> The engine uses statistical analysis of past trade outcomes — no
      external AI or ML service. Patterns become reliable after 3+ trades per category. Confidence adjustments
      are capped at ±40% to prevent overreaction to small samples. The system does not auto-execute trades;
      it only adjusts scoring to help you spot better opportunities.
    </div>
  `);
}

async function runLearningAnalysis() {
  const btn = document.getElementById('analyzeBtn');
  if (btn) { btn.disabled = true; btn.textContent = 'Analyzing...'; }
  try {
    const result = await api('/learning/analyze', 'POST');
    if (btn) { btn.disabled = false; btn.textContent = '🔄 Re-Analyze Trades'; }
    alert(`✅ Analysis complete!\n${result.summary.patterns_found} patterns found\n${result.summary.recommendations_count} recommendations generated\nBaseline win rate: ${result.summary.baseline_win_rate}%`);
    renderLearning();
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = '🔄 Re-Analyze Trades'; }
    alert('Analysis failed: ' + e.message);
  }
}

// ── Tiers Page ────────────────────────────────────────────────────────────────
async function renderTiers() {
  const tiers = await api('/tiers');
  renderLayout(`
    <div class="card">
      <div class="card-title">Account Level & Network Unlocks</div>
      <div style="margin-bottom:20px;">
        <div class="flex-between">
          <span><strong>${tiers.current_tier_name}</strong></span>
          <span class="muted">Balance: $${tiers.balance.toFixed(2)}</span>
        </div>
        <div class="progress-bar"><div class="progress-fill" style="width:${tiers.progress_to_next}%"></div></div>
        <div class="muted" style="font-size:12px;">${tiers.next_tier_requirement}</div>
      </div>
      <div class="tier-list">
        ${tiers.all_tiers.map(t => `
          <div class="tier-item ${t.level===tiers.current_tier?'current':t.level>tiers.current_tier?'locked':''}">
            <div class="tier-num">${t.level}</div>
            <div style="flex:1;">
              <div><strong>${t.name}</strong> ${t.level===tiers.current_tier?'<span class="pill pill-approved" style="margin-left:8px;">Current</span>':''}</div>
              <div class="muted" style="font-size:12px;">${t.description}</div>
              <div style="margin-top:4px;">
                <strong>Networks:</strong> ${t.networks.join(', ')} |
                <strong>Max size:</strong> ${(t.max_size_percent*100).toFixed(0)}% |
                <strong>Min balance:</strong> $${t.min_balance}
              </div>
            </div>
          </div>`).join('')}
      </div>
    </div>
    <div class="card">
      <div class="card-title">Unlocked Networks</div>
      <p>Currently unlocked: <strong>${tiers.unlocked_networks.join(', ').toUpperCase()}</strong></p>
      <p class="muted mt-16">Scanning and execution are restricted to unlocked networks only.
      Ethereum is the final network unlocked and only after significant compounded growth.</p>
    </div>
  `);
}

// ── Bot Integration Guide ─────────────────────────────────────────────────────
function renderGuide() {
  renderLayout(`
    <div class="guide-page">

      <div class="card">
        <div class="card-title">Connect the External Execution Bot Safely</div>
        <div class="guide-safety">
          <p>Keep <strong>Paper Mode</strong> enabled until the external bot is validated. This repository is a control dashboard, not an exchange executor. A heartbeat proves connectivity only; it does not verify exchange permissions, account balances, contract safety, or successful execution.</p>
          <ul>
            <li>Use an always-on HTTPS deployment for live trading. The current sandbox preview is for development, not production.</li>
            <li>Change the default dashboard password. Get <code>BOT_SECRET</code> from Security and store it only in the external bot's secret manager. Never put it in source code or logs.</li>
            <li>Keep wallet signing keys and exchange credentials on the executor host, not this dashboard. For exchanges, use a dedicated subaccount, trade-only access, no withdrawal permissions, and an IP allowlist.</li>
            <li>On the external bot, test <code>GET /api/test</code>, then read <code>GET /api/status</code>. Start in paper or exchange testnet mode with signing and live orders disabled.</li>
            <li>Send authenticated heartbeats every 15–30 seconds. Missing heartbeats become stale after 60 seconds. Replay and dashboard tests never establish external readiness.</li>
            <li>Before every order, require <code>mode == "real"</code>, <code>is_running == true</code>, Guardian approval, the correct account/network, and locally enforced size, exposure, daily-loss, slippage, and gas limits. Stop on failed or stale status reads; respect per-bot pause commands.</li>
            <li>Validate paper fills, reconcile actual account balances independently, and test stop/kill handling without funds. Dashboard deposits/withdrawals only edit a ledger.</li>
            <li>Only after validation, complete the Dashboard safety gate yourself: prerequisites, exact risk phrase, and three-second hold. Enabling Real Mode does not press Start. Begin with a small, explicitly capped amount you can afford to lose.</li>
          </ul>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Quick Connection Test (run on the external bot host)</div>
        <p class="muted" style="margin-bottom:12px;">Set <code>DASHBOARD_URL</code> and <code>BOT_SECRET</code> securely on the external bot host.</p>
        <pre class="code-block"><code># Run only on the external bot host; set DASHBOARD_URL and BOT_SECRET securely.
curl --fail --show-error "$DASHBOARD_URL/api/test" \\
  -H "Authorization: Bearer $BOT_SECRET"
curl --fail --show-error "$DASHBOARD_URL/api/status" \\
  -H "Authorization: Bearer $BOT_SECRET"
curl --fail --show-error -X POST "$DASHBOARD_URL/api/heartbeats" \\
  -H "Authorization: Bearer $BOT_SECRET" -H "Content-Type: application/json" \\
  -d '{"bot":"execution","status":"running","message":"External executor connected in paper mode"}'</code></pre>
        <div class="guide-callout">
          <strong>BOT_SECRET</strong> is a shared credential with write access across the bot API; trust only your own bot processes. Do not use a fabricated heartbeat to clear the gate. No order or signing code is installed by this guide.
        </div>
      </div>

      <div class="card">
        <div class="card-title">Authentication</div>
        <p style="margin-bottom:8px;">All POST endpoints require the <code>Authorization: Bearer BOT_SECRET</code> header. Get your <code>BOT_SECRET</code> from the Security page.</p>
        <pre class="code-block"><code>Authorization: Bearer YOUR_BOT_SECRET</code></pre>
        <p class="muted" style="margin-top:8px;">Backward compat: <code>X-API-Key: WEBHOOK_API_KEY</code> also accepted.</p>
      </div>

      <div class="card">
        <div class="card-title">1. Read System Status</div>
        <p class="muted" style="margin-bottom:12px;">Bots read mode, is_running, thresholds, risk limits, unlocked networks.</p>
        <pre class="code-block"><code>curl -H "Authorization: Bearer YOUR_SECRET" $DASHBOARD_URL/api/status</code></pre>
        <p style="margin-top:12px;"><strong>Returns:</strong> <code>mode</code> (paper/real), <code>is_running</code>, <code>is_aggressive</code>, <code>account_balance</code>, <code>thresholds</code>, <code>risk_limits</code>, <code>unlocked_networks</code>, <code>routers</code>, <code>wallet_address</code>, <code>network_config</code> (chain_id, rpc_url)</p>
      </div>

      <div class="card">
        <div class="card-title">2. Push Heartbeat</div>
        <pre class="code-block"><code>curl -X POST -H "Authorization: Bearer YOUR_SECRET" -H "Content-Type: application/json" \\
  -d '{
    "bot": "scanner",
    "status": "running",
    "message": "Scanning Base network for opportunities",
    "timestamp": 1728345900,
    "meta": {}
  }' \\
  $DASHBOARD_URL/api/heartbeats</code></pre>
        <p style="margin-top:12px;"><strong>bot:</strong> scanner | quant | guardian | execution · <strong>status:</strong> running | paused | error | offline</p>
      </div>

      <div class="card">
        <div class="card-title">3. Push Opportunity</div>
        <pre class="code-block"><code>curl -X POST -H "Authorization: Bearer YOUR_SECRET" -H "Content-Type: application/json" \\
  -d '{
    "id": "opp_123",
    "type": "flashloan",
    "network": "base",
    "path": ["0xTokenA", "0xTokenB"],
    "amountIn": "1000000000000000000",
    "expectedAmountOut": "1008500000000000000",
    "netProfit": "6200000000000000",
    "netProfitUsd": 6.20,
    "score": 6200,
    "status": "approved",
    "source": "quant",
    "timestamp": 1728345901
  }' \\
  $DASHBOARD_URL/api/opportunities</code></pre>
        <p style="margin-top:12px;"><strong>type:</strong> crossdex | flashloan | triangular | multihop · Opportunities on locked networks are rejected.</p>
      </div>

      <div class="card">
        <div class="card-title">4. Push Trade Result</div>
        <pre class="code-block"><code>curl -X POST -H "Authorization: Bearer YOUR_SECRET" -H "Content-Type: application/json" \\
  -d '{
    "opportunityId": "opp_123",
    "mode": "paper",
    "status": "success",
    "network": "base",
    "txHash": "0xabc123...",
    "amountIn": "1000000000000000000",
    "amountOut": "1008500000000000000",
    "netProfit": "5800000000000000",
    "netProfitUsd": 5.80,
    "gasUsed": "687432",
    "notes": "Flash-loan executed",
    "timestamp": 1728345910
  }' \\
  $DASHBOARD_URL/api/trades</code></pre>
        <p style="margin-top:12px;"><strong>mode:</strong> paper | real · <strong>status:</strong> success | failed · Balances update automatically.</p>
      </div>

      <div class="card">
        <div class="card-title">5. Push Log Entry</div>
        <pre class="code-block"><code>curl -X POST -H "Authorization: Bearer YOUR_SECRET" -H "Content-Type: application/json" \\
  -d '{
    "bot": "guardian",
    "level": "warning",
    "message": "Slippage above 2% threshold on opp_123",
    "meta": {"opportunity_id": "opp_123", "slippage": 0.025}
  }' \\
  $DASHBOARD_URL/api/logs</code></pre>
        <p style="margin-top:12px;"><strong>level:</strong> info | warning | error · Error logs also create a notification.</p>
      </div>

      <div class="card">
        <div class="card-title">Bot Roles</div>
        <div class="bot-roles-grid">
          <div class="bot-role-card">
            <div class="bot-role-icon">🔍</div>
            <div><strong>Scanner Bot</strong><br><span class="muted">Finds raw opportunities on unlocked networks only. Pushes them via /api/opportunities.</span></div>
          </div>
          <div class="bot-role-card">
            <div class="bot-role-icon">🧮</div>
            <div><strong>Quant Bot</strong><br><span class="muted">Runs routing + full net profit formula + risk checks + prioritization. Pushes scored opportunities.</span></div>
          </div>
          <div class="bot-role-card">
            <div class="bot-role-icon">🛡️</div>
            <div><strong>Guardian Bot</strong><br><span class="muted">Simulates the exact transaction and performs final risk check before execution.</span></div>
          </div>
          <div class="bot-role-card">
            <div class="bot-role-icon">⚡</div>
            <div><strong>Execution Bot</strong><br><span class="muted">Only executes Guardian-approved opportunities. Respects Paper vs Real mode. Reports results back.</span></div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Base Network Configuration</div>
        <div class="guide-config-grid">
          <div class="guide-config-item"><span class="guide-config-label">Chain ID</span><span class="guide-config-value">8453</span></div>
          <div class="guide-config-item"><span class="guide-config-label">RPC URL</span><span class="guide-config-value" style="font-family:monospace;font-size:12px;">https://mainnet.base.org</span></div>
          <div class="guide-config-item"><span class="guide-config-label">Router</span><span class="guide-config-value" style="font-family:monospace;font-size:12px;">0x4752ba5dBc23f44D87826276bf6fd6b1C372aD24</span></div>
          <div class="guide-config-item"><span class="guide-config-label">Router Name</span><span class="guide-config-value">Uniswap V2 Router02</span></div>
          <div class="guide-config-item"><span class="guide-config-label">WETH</span><span class="guide-config-value" style="font-family:monospace;font-size:12px;">0x4200000000000000000000000000000000000006</span></div>
        </div>
        <p class="muted mt-16">Bots read <code>chain_id</code> and <code>rpc_url</code> from <code>/api/status</code> → <code>network_config</code>. Configure in Settings → Base Network Configuration.</p>
      </div>

      <div class="card">
        <div class="card-title">Net Profit Formula</div>
        <pre class="code-block"><code>Net Profit = Gross Profit – (
  DEX fees + Flash-loan fees + Gas cost +
  Slippage cost + Price Impact cost + Competition haircut
)

Gross Profit = amountOut – amountIn</code></pre>
        <p style="margin-top:12px;">Only opportunities with Net Profit above the current minimum threshold are allowed. Opportunities are always sorted by Net Profit (highest first).</p>
      </div>

    </div>
  `);
}

// ── Router ────────────────────────────────────────────────────────────────────
async function render() {
  if (!token) { renderLogin(); return; }
  try {
    switch (currentPage) {
      case 'dashboard':   await renderDashboard(); break;
      case 'active':      await renderActive(); break;
      case 'wallet':      await renderWallet(); break;
      case 'capital':     await renderCapital(); break;
      case 'risk':        await renderRiskMonitor(); break;
      case 'performance': await renderPerformance(); break;
      case 'trades':      await renderTrades(); break;
      case 'compounding': await renderCompounding(); break;
      case 'bots':        await renderBots(); break;
      case 'botlogs':     await renderBotLogs(); break;
      case 'learning':    await renderLearning(); break;
      case 'insights':    await renderInsights(); break;
      case 'notifications': await renderNotifications(); break;
      case 'onboarding':  await renderOnboarding(); break;
      case 'settings':    await renderSettings(); break;
      case 'security':    await renderSecurity(); break;
      case 'tiers':       await renderTiers(); break;
      case 'guide':       renderGuide(); break;
      default:            currentPage = 'dashboard'; await renderDashboard();
    }
    populateTicker();
  } catch (e) {
    if (e.message === 'Unauthorized') return;
    renderLayout(`<div class="empty-state">Error loading page: ${e.message}</div>`);
  }
}

window.addEventListener('hashchange', () => {
  const hash = window.location.hash.slice(1);
  if (navItems.find(n => n.id === hash)) {
    currentPage = hash;
    render();
  }
});

window.addEventListener('load', () => {
  const hash = window.location.hash.slice(1);
  if (navItems.find(n => n.id === hash)) currentPage = hash;
  render();
});
