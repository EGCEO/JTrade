// ── Arbitrage Gods – SPA ───────────────────────────────────────────────────
const API = '/api';
let token = localStorage.getItem('acc_token') || '';
let currentPage = 'dashboard';

const navItems = [
  { id: 'dashboard',  label: 'Dashboard',     icon: '📊' },
  { id: 'active',     label: 'Active Trades',  icon: '⚡' },
  { id: 'settings',   label: 'Settings',      icon: '⚙️' },
  { id: 'bots',       label: 'Bot Control',   icon: '🤖' },
  { id: 'trades',     label: 'Trade History',  icon: '📋' },
  { id: 'compounding',label: 'Compounding',   icon: '📈' },
  { id: 'insights',   label: 'Insights',      icon: '💡' },
  { id: 'tiers',      label: 'Levels & Unlocks', icon: '🏆' },
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
        ${nav}
        <div class="sidebar-spacer"></div>
        <div class="sidebar-footer">
          <a href="#" onclick="logout();return false;" style="color:var(--text-dim);text-decoration:none;">⏻ Logout</a>
        </div>
      </div>
      <div class="main">
        <div class="ticker-bar"><div class="ticker-track" id="tickerTrack"></div></div>
        <div class="topbar" id="topbar"><h2>${navItems.find(n => n.id === currentPage)?.label || ''}</h2></div>
        <div class="content" id="page-content">${content}</div>
      </div>
    </div>`;
}

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
    <div class="disclaimer">
      <strong>⚠️ Risk Disclaimer:</strong> Not financial advice. Cryptocurrency trading and arbitrage involve
      substantial risk of loss. Past performance does not guarantee future results. Only trade with capital you can afford to lose.
      Paper Trading Mode is strongly recommended until the system is fully understood.
    </div>
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
  `);
  updateTopbar(mode, config);

  // Render real-time profit & activity chart
  renderRealtimeChart();
}

let dashChartInstance = null;
let dashChartInterval = null;

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
  const bots = await api('/bots');
  renderLayout(`
    <div class="card">
      <div class="card-title">Three-Bot Team Control Panel</div>
      <p class="muted" style="margin-bottom:16px;">
        The dashboard manages three specialized external bots. Use pause/resume to control them.
        Heartbeats are pushed by the bots via webhook.
      </p>
      <div class="bot-grid">
        ${bots.map(b => `
          <div class="bot-card">
            <h3>${b.bot_name.charAt(0).toUpperCase() + b.bot_name.slice(1)} Bot
              <span class="pill pill-${b.status}">${b.status}</span>
            </h3>
            <div class="bot-info"><strong>Last action:</strong> ${b.last_action || '—'}</div>
            <div class="bot-info"><strong>Heartbeat:</strong> ${b.last_heartbeat ? new Date(b.last_heartbeat).toLocaleString() : 'Never'}</div>
            ${b.error_message ? `<div class="bot-info" style="color:var(--danger);"><strong>Error:</strong> ${b.error_message}</div>` : ''}
            <div class="bot-actions">
              <button class="btn btn-sm" onclick="pauseBot('${b.bot_name}')">⏸ Pause</button>
              <button class="btn btn-sm" onclick="resumeBot('${b.bot_name}')">▶ Resume</button>
            </div>
          </div>`).join('')}
      </div>
    </div>
    <div class="card">
      <div class="card-title">Webhook Endpoints (for external bots)</div>
      <table>
        <thead><tr><th>Method</th><th>Endpoint</th><th>Purpose</th></tr></thead>
        <tbody>
          <tr><td>GET</td><td><code>/api/mode</code></td><td>Read current mode, thresholds, unlocked networks</td></tr>
          <tr><td>POST</td><td><code>/api/opportunities</code></td><td>Scanner pushes discovered opportunities</td></tr>
          <tr><td>POST</td><td><code>/api/trades</code></td><td>Execution bot logs results</td></tr>
          <tr><td>POST</td><td><code>/api/bots/{name}/heartbeat</code></td><td>Push bot heartbeat</td></tr>
          <tr><td>POST</td><td><code>/api/account/balance</code></td><td>Update paper/real balance</td></tr>
          <tr><td>GET</td><td><code>/api/config</code></td><td>Read all settings (auth required)</td></tr>
        </tbody>
      </table>
      <p class="muted mt-16">All POST endpoints require <code>X-API-Key</code> header.</p>
    </div>
  `);
}

async function pauseBot(name) {
  try { await api(`/bots/${name}/pause`, 'POST'); renderBots(); } catch (e) { alert(e.message); }
}
async function resumeBot(name) {
  try { await api(`/bots/${name}/resume`, 'POST'); renderBots(); } catch (e) { alert(e.message); }
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
      ${data.waiting_confirmation.length === 0 ? '<div class="empty-state">No opportunities awaiting confirmation.</div>' : `
      <table>
        <thead><tr><th>Pair</th><th>Network</th><th>Style</th><th>Net Profit</th><th>Confidence</th><th>Priority</th><th>Created</th><th>Status</th></tr></thead>
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
  const [account, tiers, snapshots] = await Promise.all([
    api('/account'), api('/tiers'), api('/account/snapshots?limit=50'),
  ]);
  renderLayout(`
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

// ── Router ────────────────────────────────────────────────────────────────────
async function render() {
  if (!token) { renderLogin(); return; }
  try {
    switch (currentPage) {
      case 'dashboard':   await renderDashboard(); break;
      case 'active':      await renderActive(); break;
      case 'settings':    await renderSettings(); break;
      case 'bots':        await renderBots(); break;
      case 'trades':      await renderTrades(); break;
      case 'compounding': await renderCompounding(); break;
      case 'insights':    await renderInsights(); break;
      case 'tiers':       await renderTiers(); break;
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
