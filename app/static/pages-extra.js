// ── Extra Pages: Wallet, Capital, Risk, Notifications, Onboarding, Security, BotLogs ──

// ── Wallet Connect ──────────────────────────────────────────────────────────
async function renderWallet() {
  const [execStatus, config] = await Promise.all([
    api('/execution/status').catch(() => null),
    api('/config'),
  ]);
  renderLayout(`
    <div class="card">
      <div class="card-title">Wallet Connection</div>
      <p class="muted" style="margin-bottom:16px;">
        Connect a wallet for real execution on Base (Chain ID 8453). The dashboard never holds private keys —
        credentials are stored securely in Secrets and used only by the execution engine.
      </p>
      <div class="stat-grid" style="margin-bottom:0;">
        <div class="stat-card">
          <div class="stat-label">Wallet Address</div>
          <div class="stat-value" style="font-size:13px;font-family:monospace;word-break:break-all;">
            ${execStatus?.wallet_address || 'Not configured'}
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Chain</div>
          <div class="stat-value" style="font-size:16px;">${execStatus?.network || 'Unknown'}</div>
          <div class="stat-sub muted">Chain ID: ${execStatus?.chain_id || '—'}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Wallet Balance (ETH)</div>
          <div class="stat-value">${execStatus?.balance?.toFixed(6) || '0.000000'}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Private Key</div>
          <div class="stat-value" style="font-size:16px;">${execStatus?.private_key_set ? '✅ Set' : '❌ Missing'}</div>
          <div class="stat-sub muted">Via Secrets</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Base Network Configuration</div>
      <div class="guide-config-grid">
        <div class="guide-config-item"><span class="guide-config-label">Chain ID</span><span class="guide-config-value">8453</span></div>
        <div class="guide-config-item"><span class="guide-config-label">RPC URL</span><span class="guide-config-value" style="font-family:monospace;font-size:12px;">${config.base_rpc_url || 'https://mainnet.base.org'}</span></div>
        <div class="guide-config-item"><span class="guide-config-label">Base Router</span><span class="guide-config-value" style="font-family:monospace;font-size:12px;">${config.base_router || '—'}</span></div>
        <div class="guide-config-item"><span class="guide-config-label">WETH</span><span class="guide-config-value" style="font-family:monospace;font-size:12px;">0x4200…0006</span></div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">MetaMask Connection</div>
      <p class="muted" style="margin-bottom:12px;">
        This dashboard is a control plane — it does not sign transactions. External bots handle execution.
        To connect MetaMask for read-only balance checks, use the button below (browser-dependent).
      </p>
      <button class="btn btn-primary" onclick="connectMetaMask()">🦊 Connect MetaMask</button>
      <div id="mm-status" style="margin-top:12px;"></div>
    </div>

    ${!execStatus?.configured ? `
    <div class="exec-warning">
      ⚠️ Real execution requires <code>PRIVATE_KEY</code> and <code>WALLET_ADDRESS</code> set in Secrets.
      The wallet address must match the private key owner. Paper mode works without a wallet.
    </div>` : ''}

    <div class="disclaimer">
      <strong>⚠️ Risk Disclaimer:</strong> Not financial advice. Flash-loan and arbitrage strategies carry real risk of loss,
      including gas fees on failed transactions. Only use capital you can afford to lose. Paper Trading Mode is strongly
      recommended until the system is fully understood and tested.
    </div>
  `);
}

async function connectMetaMask() {
  const status = document.getElementById('mm-status');
  if (typeof window.ethereum === 'undefined') {
    status.innerHTML = '<span style="color:var(--danger);">MetaMask not detected in this browser.</span>';
    return;
  }
  try {
    const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
    const chainId = await window.ethereum.request({ method: 'eth_chainId' });
    status.innerHTML = `<span style="color:var(--success);">Connected: ${accounts[0]}<br>Chain: ${chainId}</span>`;
  } catch (e) {
    status.innerHTML = `<span style="color:var(--danger);">Connection failed: ${e.message}</span>`;
  }
}

// ── Capital & Balances ───────────────────────────────────────────────────────
async function renderCapital() {
  const [account, txns, config] = await Promise.all([
    api('/account'), api('/capital/transactions?limit=50'), api('/config'),
  ]);
  const isCompounding = config.compounding_mode;
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
      <div class="stat-card">
        <div class="stat-label">Compounding</div>
        <div class="stat-value" style="font-size:16px;">${isCompounding ? '📈 ON' : '⏸ OFF'}</div>
        <div class="stat-sub muted">${isCompounding ? 'Reinvesting profits' : 'Profits withdrawable'}</div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Capital Actions</div>
      <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;">
        <button class="btn btn-primary" onclick="openDepositModal()">💰 Deposit</button>
        <button class="btn" onclick="openWithdrawModal()">💸 Withdraw</button>
        <button class="btn" onclick="manualCompound()">📈 Manual Compound</button>
      </div>
      <div style="display:flex;gap:24px;flex-wrap:wrap;align-items:center;">
        <div style="display:flex;align-items:center;gap:10px;">
          <div class="toggle ${isCompounding?'on':''}" onclick="toggleCompounding(${!isCompounding})"></div>
          <span>Auto-Compound ${isCompounding?'(ON)':'(OFF)'}</span>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Capital Transaction History</div>
      ${txns.length === 0 ? '<div class="empty-state">No capital transactions yet.</div>' : `
      <table>
        <thead><tr><th>Time</th><th>Type</th><th>Mode</th><th>Amount</th><th>Balance After</th><th>Notes</th></tr></thead>
        <tbody>
          ${txns.map(t => `
            <tr>
              <td>${t.created_at ? new Date(t.created_at).toLocaleString() : '—'}</td>
              <td><span class="pill ${t.type==='deposit'?'pill-approved':t.type==='withdraw'?'pill-error':'pill-running'}">${t.type}</span></td>
              <td>${t.mode}</td>
              <td class="${t.amount>=0?'profit-high':'profit-neg'}">$${Math.abs(t.amount).toFixed(2)}</td>
              <td>$${t.balance_after.toFixed(2)}</td>
              <td class="muted">${t.notes}</td>
            </tr>`).join('')}
        </tbody>
      </table>`}
    </div>
  `);
}

function openDepositModal() {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal-card">
      <div class="modal-header">
        <span class="modal-title">Deposit Capital</span>
        <button class="modal-close" onclick="this.closest('.modal-overlay').remove()">✕</button>
      </div>
      <div class="form-group">
        <label>Mode</label>
        <select id="dep-mode"><option value="paper">Paper</option><option value="real">Real</option></select>
      </div>
      <div class="form-group">
        <label>Amount ($)</label>
        <input type="number" id="dep-amount" placeholder="0.00" step="0.01" min="0">
      </div>
      <button class="btn btn-primary" onclick="submitDeposit()">Deposit</button>
    </div>`;
  document.body.appendChild(overlay);
}

async function submitDeposit() {
  const mode = document.getElementById('dep-mode').value;
  const amount = parseFloat(document.getElementById('dep-amount').value);
  if (!amount || amount <= 0) { alert('Enter a valid amount'); return; }
  try {
    await api('/capital/deposit', 'POST', { mode, amount });
    document.querySelector('.modal-overlay').remove();
    renderCapital();
  } catch (e) { alert(e.message); }
}

function openWithdrawModal() {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal-card">
      <div class="modal-header">
        <span class="modal-title">Withdraw Capital</span>
        <button class="modal-close" onclick="this.closest('.modal-overlay').remove()">✕</button>
      </div>
      <div class="form-group">
        <label>Mode</label>
        <select id="wd-mode"><option value="paper">Paper</option><option value="real">Real</option></select>
      </div>
      <div class="form-group">
        <label>Amount ($)</label>
        <input type="number" id="wd-amount" placeholder="0.00" step="0.01" min="0">
      </div>
      <button class="btn btn-danger" onclick="submitWithdraw()">Withdraw</button>
    </div>`;
  document.body.appendChild(overlay);
}

async function submitWithdraw() {
  const mode = document.getElementById('wd-mode').value;
  const amount = parseFloat(document.getElementById('wd-amount').value);
  if (!amount || amount <= 0) { alert('Enter a valid amount'); return; }
  try {
    await api('/capital/withdraw', 'POST', { mode, amount });
    document.querySelector('.modal-overlay').remove();
    renderCapital();
  } catch (e) { alert(e.message); }
}

async function manualCompound() {
  try {
    const result = await api('/capital/compound', 'POST', { mode: 'paper', amount: 0 });
    alert(`Compounded $${result.amount.toFixed(2)} in paper balance.`);
    renderCapital();
  } catch (e) { alert(e.message); }
}

// ── Live Risk Monitor ────────────────────────────────────────────────────────
let riskMonitorInterval = null;

async function renderRiskMonitor() {
  const risk = await api('/risk-monitor');
  const alerts = risk.alerts;
  const rl = risk.risk_limits;

  renderLayout(`
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">Current Mode</div>
        <div class="stat-value" style="font-size:16px;">${risk.mode === 'real' ? '🔴 REAL' : '🟢 PAPER'}</div>
        <div class="stat-sub muted">${risk.is_aggressive ? 'Aggressive' : 'Normal'} · ${risk.is_running ? 'Running' : 'Stopped'}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Account Balance</div>
        <div class="stat-value">$${risk.balance.toFixed(2)}</div>
        <div class="stat-sub muted">Started: $${risk.starting_capital.toFixed(2)}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Today's P&L</div>
        <div class="stat-value ${risk.today_pnl>=0?'profit-high':'profit-neg'}">${risk.today_pnl>=0?'+':''}$${risk.today_pnl.toFixed(2)}</div>
        <div class="stat-sub muted">${risk.today_trades} trades today</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Current Drawdown</div>
        <div class="stat-value ${risk.current_drawdown>5?'profit-neg':'profit-low'}">${risk.current_drawdown.toFixed(1)}%</div>
        <div class="stat-sub muted">Max: ${risk.max_drawdown.toFixed(1)}%</div>
      </div>
    </div>

    ${alerts.kill_switch_active ? '<div class="exec-warning">🛑 KILL SWITCH IS ACTIVE — All trading is stopped.</div>' : ''}
    ${alerts.daily_loss_limit_hit ? '<div class="exec-warning">⚠️ Daily loss limit has been reached. No further trades should execute.</div>' : ''}
    ${alerts.exposure_limit_hit ? '<div class="exec-warning">⚠️ Maximum open exposure limit reached.</div>' : ''}

    <div class="card">
      <div class="card-title">Risk Limits (Active)</div>
      <table>
        <thead><tr><th>Limit</th><th>Value</th><th>USD</th><th>Status</th></tr></thead>
        <tbody>
          <tr>
            <td>Max Risk per Trade</td>
            <td>${rl.max_risk_per_trade_pct.toFixed(0)}%</td>
            <td>$${rl.max_risk_per_trade_usd.toFixed(2)}</td>
            <td><span class="pill pill-approved">Active</span></td>
          </tr>
          <tr>
            <td>Daily Loss Limit</td>
            <td>${rl.daily_loss_limit_pct.toFixed(0)}%</td>
            <td>$${rl.daily_loss_limit_usd.toFixed(2)}</td>
            <td><span class="pill ${alerts.daily_loss_limit_hit?'pill-error':'pill-approved'}">${alerts.daily_loss_limit_hit?'HIT':'OK'}</span></td>
          </tr>
          <tr>
            <td>Max Open Exposure</td>
            <td>${rl.max_open_exposure_pct.toFixed(0)}%</td>
            <td>$${rl.max_open_exposure_usd.toFixed(2)}</td>
            <td><span class="pill ${alerts.exposure_limit_hit?'pill-error':'pill-approved'}">${alerts.exposure_limit_hit?'HIT':'OK'}</span></td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="card">
      <div class="card-title">Current Exposure</div>
      <div class="stat-grid" style="margin-bottom:0;">
        <div class="stat-card">
          <div class="stat-label">Open Opportunities</div>
          <div class="stat-value">${risk.open_opportunities}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Total Open Exposure</div>
          <div class="stat-value">$${risk.open_exposure.toFixed(2)}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Today's Losses</div>
          <div class="stat-value profit-neg">$${risk.today_losses.toFixed(2)}</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Emergency Controls</div>
      <div style="display:flex;gap:12px;flex-wrap:wrap;">
        <button class="btn btn-danger" style="font-size:16px;padding:14px 32px;" onclick="activateKillSwitch()">🛑 EMERGENCY KILL SWITCH</button>
        <button class="btn btn-primary" onclick="masterStart()">▶ Start</button>
        <button class="btn" onclick="masterPause()">⏸ Pause</button>
        <button class="btn" onclick="masterStop()">⏹ Stop</button>
      </div>
    </div>

    <div class="disclaimer">
      <strong>⚠️ Risk Disclaimer:</strong> Not financial advice. Flash-loan and arbitrage strategies carry real risk of loss,
      including gas fees on failed transactions. Only use capital you can afford to lose. Paper Trading Mode is strongly
      recommended until the system is fully understood and tested.
    </div>
  `);

  if (riskMonitorInterval) clearInterval(riskMonitorInterval);
  riskMonitorInterval = setInterval(async () => {
    if (currentPage === 'risk') renderRiskMonitor();
    else clearInterval(riskMonitorInterval);
  }, 5000);
}

async function activateKillSwitch() {
  if (!confirm('🛑 ACTIVATE KILL SWITCH?\n\nThis will immediately stop ALL trading, disable real mode, and pause all bots.')) return;
  try {
    await api('/kill-switch', 'POST');
    alert('Kill switch activated. All trading stopped.');
    renderRiskMonitor();
  } catch (e) { alert(e.message); }
}

async function masterStart() {
  try { await api('/master/start', 'POST'); renderRiskMonitor(); } catch (e) { alert(e.message); }
}
async function masterPause() {
  try { await api('/master/pause', 'POST'); renderRiskMonitor(); } catch (e) { alert(e.message); }
}
async function masterStop() {
  try { await api('/master/stop', 'POST'); renderRiskMonitor(); } catch (e) { alert(e.message); }
}

// ── Notifications Center ──────────────────────────────────────────────────────
async function renderNotifications() {
  const notifs = await api('/notifications?limit=50');
  renderLayout(`
    <div class="card">
      <div class="flex-between mb-0">
        <div class="card-title mb-0">Notifications Center</div>
        <button class="btn btn-sm" onclick="markAllRead()">✓ Mark All Read</button>
      </div>
      ${notifs.length === 0 ? '<div class="empty-state">No notifications.</div>' : `
      <div style="display:flex;flex-direction:column;gap:8px;margin-top:16px;">
        ${notifs.map(n => `
          <div style="display:flex;gap:12px;align-items:flex-start;padding:14px 16px;background:var(--bg-input);border:1px solid var(--border);border-radius:8px;${n.read?'opacity:.5;':''}">
            <span style="font-size:18px;flex-shrink:0;">${n.type==='error'?'🛑':n.type==='warning'?'⚠️':n.type==='success'?'✅':'ℹ️'}</span>
            <div style="flex:1;">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <strong>${n.title}</strong>
                <span class="muted" style="font-size:11px;">${n.created_at ? new Date(n.created_at).toLocaleString() : ''}</span>
              </div>
              <div class="muted" style="font-size:13px;margin-top:4px;">${n.message}</div>
            </div>
            ${!n.read ? `<button class="btn btn-sm" onclick="markOneRead(${n.id})">✓</button>` : ''}
          </div>`).join('')}
      </div>`}
    </div>
  `);
}

async function markOneRead(id) {
  try { await api(`/notifications/${id}/read`, 'POST'); renderNotifications(); } catch (e) { alert(e.message); }
}
async function markAllRead() {
  try { await api('/notifications/read-all', 'POST'); renderNotifications(); } catch (e) { alert(e.message); }
}

// ── Onboarding Checklist ─────────────────────────────────────────────────────
async function renderOnboarding() {
  const data = await api('/onboarding');
  renderLayout(`
    <div class="card">
      <div class="card-title">Onboarding Checklist</div>
      <p class="muted" style="margin-bottom:16px;">Complete these steps to get your Arbitrage Gods system fully operational.</p>
      <div class="progress-bar" style="margin-bottom:20px;"><div class="progress-fill" style="width:${data.pct}%"></div></div>
      <div style="display:flex;flex-direction:column;gap:12px;">
        ${data.steps.map(s => `
          <div style="display:flex;gap:14px;align-items:flex-start;padding:16px;background:var(--bg-input);border:1px solid var(--border);border-radius:8px;${s.done?'border-color:var(--accent) !important;':''}">
            <span style="font-size:20px;flex-shrink:0;">${s.done?'✅':'⬜'}</span>
            <div>
              <strong>${s.label}</strong>
              <div class="muted" style="font-size:13px;margin-top:4px;">${s.detail}</div>
            </div>
          </div>`).join('')}
      </div>
      <div style="margin-top:20px;text-align:center;">
        <span class="pill ${data.pct===100?'pill-approved':'pill-pending'}">${data.completed}/${data.total} Complete (${data.pct}%)</span>
      </div>
    </div>
  `);
}

// ── Security Settings ────────────────────────────────────────────────────────
async function renderSecurity() {
  const config = await api('/config');
  renderLayout(`
    <div class="card">
      <div class="card-title">BOT_SECRET (API Key)</div>
      <p class="muted" style="margin-bottom:12px;">
        External bots use this secret in the <code>Authorization: Bearer BOT_SECRET</code> header to push data.
        Keep it secure. Regenerating will invalidate the old key — update all bots immediately.
      </p>
      <div class="form-group">
        <label>Current BOT_SECRET</label>
        <input type="text" value="${config.webhook_api_key || ''}" readonly style="font-family:monospace;">
      </div>
      <button class="btn btn-danger" onclick="regenerateSecret()">🔄 Regenerate BOT_SECRET</button>
    </div>

    <div class="card">
      <div class="card-title">Admin Credentials</div>
      <p class="muted" style="margin-bottom:12px;">Admin username and password are set via Secrets (<code>ADMIN_USERNAME</code>, <code>ADMIN_PASSWORD</code>).</p>
      <div class="form-group">
        <label>Admin Username</label>
        <input type="text" value="${config.session_token ? 'configured' : 'not set'}" readonly>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Wallet Credentials</div>
      <p class="muted" style="margin-bottom:12px;">Wallet credentials are set via Secrets (<code>PRIVATE_KEY</code>, <code>WALLET_ADDRESS</code>). The dashboard never displays these values.</p>
      <div class="form-group">
        <label>Wallet Address</label>
        <input type="text" value="${config.wallet_address || 'Not set'}" readonly style="font-family:monospace;">
      </div>
    </div>

    <div class="card">
      <div class="card-title">Session Security</div>
      <p class="muted">Session tokens are generated on login and stored in the dashboard config. Logout to invalidate.</p>
      <button class="btn" onclick="logout()">⏻ Logout & Invalidate Session</button>
    </div>

    <div class="disclaimer">
      <strong>⚠️ Risk Disclaimer:</strong> Not financial advice. Flash-loan and arbitrage strategies carry real risk of loss,
      including gas fees on failed transactions. Only use capital you can afford to lose. Paper Trading Mode is strongly
      recommended until the system is fully understood and tested.
    </div>
  `);
}

async function regenerateSecret() {
  if (!confirm('Regenerate BOT_SECRET? This will invalidate the old key. All external bots must be updated immediately.')) return;
  try {
    const result = await api('/regenerate-secret', 'POST');
    alert('New BOT_SECRET generated. Update all external bots now.');
    renderSecurity();
  } catch (e) { alert(e.message); }
}

// ── Bot Logs Viewer ──────────────────────────────────────────────────────────
let botLogFilter = 'all';
let botLogBotFilter = 'all';

async function renderBotLogs() {
  let path = '/logs?limit=100';
  if (botLogBotFilter !== 'all') path += `&bot=${botLogBotFilter}`;
  if (botLogFilter !== 'all') path += `&level=${botLogFilter}`;
  const logs = await api(path).catch(() => []);
  renderLayout(`
    <div class="filter-bar">
      <select onchange="botLogBotFilter=this.value;renderBotLogs()">
        <option value="all" ${botLogBotFilter==='all'?'selected':''}>All Bots</option>
        <option value="scanner" ${botLogBotFilter==='scanner'?'selected':''}>Scanner</option>
        <option value="quant" ${botLogBotFilter==='quant'?'selected':''}>Quant</option>
        <option value="guardian" ${botLogBotFilter==='guardian'?'selected':''}>Guardian</option>
        <option value="execution" ${botLogBotFilter==='execution'?'selected':''}>Execution</option>
      </select>
      <select onchange="botLogFilter=this.value;renderBotLogs()">
        <option value="all" ${botLogFilter==='all'?'selected':''}>All Levels</option>
        <option value="info" ${botLogFilter==='info'?'selected':''}>Info</option>
        <option value="warning" ${botLogFilter==='warning'?'selected':''}>Warning</option>
        <option value="error" ${botLogFilter==='error'?'selected':''}>Error</option>
      </select>
    </div>
    <div class="card">
      <div class="card-title">Bot Log Viewer</div>
      ${logs.length === 0 ? '<div class="empty-state">No bot logs yet. Logs appear when external bots push them via /api/logs.</div>' : `
      <table>
        <thead><tr><th>Time</th><th>Bot</th><th>Level</th><th>Message</th><th>Meta</th></tr></thead>
        <tbody>
          ${logs.map(l => `
            <tr>
              <td>${l.timestamp ? new Date(l.timestamp).toLocaleString() : '—'}</td>
              <td><strong>${l.bot}</strong></td>
              <td><span class="log-level-${l.level}">${l.level.toUpperCase()}</span></td>
              <td>${l.message}</td>
              <td class="muted" style="font-size:11px;">${l.meta ? JSON.stringify(l.meta).slice(0,80) : '—'}</td>
            </tr>`).join('')}
        </tbody>
      </table>`}
    </div>
  `);
}

// ── Trade Log (all attempts incl. risk validation failures) ──────────────────
let tradeLogFilter = 'all';
async function renderTradeLog() {
  let path = '/trades?limit=200';
  if (tradeLogFilter !== 'all') path += `&status=${tradeLogFilter}`;
  const trades = await api(path);
  const successCount = trades.filter(t => t.status === 'success').length;
  const failedCount = trades.filter(t => t.status === 'failed').length;
  renderLayout(`
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">Total Attempts</div>
        <div class="stat-value">${trades.length}</div>
        <div class="stat-sub muted">All trade entries</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Succeeded</div>
        <div class="stat-value profit-high">${successCount}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Failed / Rejected</div>
        <div class="stat-value profit-neg">${failedCount}</div>
        <div class="stat-sub muted">Risk validation + execution failures</div>
      </div>
    </div>
    <div class="filter-bar">
      <select onchange="tradeLogFilter=this.value;renderTradeLog()">
        <option value="all" ${tradeLogFilter==='all'?'selected':''}>All Attempts</option>
        <option value="success" ${tradeLogFilter==='success'?'selected':''}>Success Only</option>
        <option value="failed" ${tradeLogFilter==='failed'?'selected':''}>Failed Only</option>
      </select>
    </div>
    <div class="card">
      <div class="card-title">Trade Attempt Log</div>
      <p class="muted" style="margin-bottom:12px;font-size:12px;">
        Every trade attempt is logged here — including opportunities that failed risk validation before execution.
      </p>
      ${trades.length === 0 ? '<div class="empty-state">No trade attempts logged yet.</div>' : `
      <div style="overflow-x:auto;">
      <table>
        <thead><tr>
          <th>Time</th><th>Pair</th><th>Network</th><th>Mode</th>
          <th>Entry Price</th><th>Exit Price</th><th>Status</th><th>Net Result</th><th>Notes</th>
        </tr></thead>
        <tbody>
          ${trades.map(t => `
            <tr>
              <td style="white-space:nowrap;">${t.created_at ? new Date(t.created_at).toLocaleString() : '—'}</td>
              <td><strong>${t.pair || '—'}</strong></td>
              <td>${t.network}</td>
              <td><span class="pill pill-${t.mode}">${t.mode}</span></td>
              <td>${t.entry_price ? '$' + t.entry_price.toFixed(6) : '—'}</td>
              <td>${t.exit_price ? '$' + t.exit_price.toFixed(6) : '—'}</td>
              <td><span class="pill pill-${t.status==='success'?'executed':t.status==='failed'?'error':'pending'}">${t.status}</span></td>
              <td class="profit-cell ${t.net_result>0?'profit-high':t.net_result<0?'profit-neg':'profit-low'}">${t.net_result ? '$' + t.net_result.toFixed(4) : '—'}</td>
              <td class="muted" style="font-size:11px;max-width:200px;overflow:hidden;text-overflow:ellipsis;">${t.notes || ''}</td>
            </tr>`).join('')}
        </tbody>
      </table>
      </div>`}
    </div>
  `);
}
