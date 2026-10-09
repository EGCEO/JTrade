// ── Arbitrage Gods – SPA ───────────────────────────────────────────────────
const API = '/api';
let token = localStorage.getItem('acc_token') || '';
let currentPage = 'dashboard';

const navItems = [
  { id: 'dashboard',  label: 'Dashboard',     icon: '📊' },
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
        <h1>🎯 Arbitrage Gods</h1>
        <p>Hybrid Engine — Paper & Real Execution Control Plane</p>
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
        <div class="sidebar-logo">🎯 AG — Hybrid Engine</div>
        ${nav}
        <div class="sidebar-spacer"></div>
        <div class="sidebar-footer">
          <a href="#" onclick="logout();return false;" style="color:var(--text-dim);text-decoration:none;">⏻ Logout</a>
        </div>
      </div>
      <div class="main">
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

// ── Trade History ────────────────────────────────────────────────────────────
let tradeFilter = 'all';
async function renderTrades() {
  let path = '/trades?limit=100';
  if (tradeFilter !== 'all') path += `&mode=${tradeFilter}`;
  const trades = await api(path);
  renderLayout(`
    <div class="filter-bar">
      <select onchange="tradeFilter=this.value;renderTrades()">
        <option value="all" ${tradeFilter==='all'?'selected':''}>All Modes</option>
        <option value="paper" ${tradeFilter==='paper'?'selected':''}>Paper Only</option>
        <option value="real" ${tradeFilter==='real'?'selected':''}>Real Only</option>
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
      case 'settings':    await renderSettings(); break;
      case 'bots':        await renderBots(); break;
      case 'trades':      await renderTrades(); break;
      case 'compounding': await renderCompounding(); break;
      case 'insights':    await renderInsights(); break;
      case 'tiers':       await renderTiers(); break;
      default:            currentPage = 'dashboard'; await renderDashboard();
    }
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
