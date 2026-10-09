// Keep external connectivity distinct from paper replay and dashboard tests.
async function loadBots() {
  const grid = document.getElementById('bot-mini');
  const summary = document.getElementById('bot-status-summary');
  const roles = {
    scanner: ['Scanner', '🔍', 'Opportunity detection'],
    quant: ['Quant', '🧮', 'Scoring & filtering'],
    guardian: ['Guardian', '🛡️', 'Final risk checks'],
    execution: ['Execution', '⚡', 'Trade execution'],
  };
  try {
    const bots = await api('/api/bots');
    grid.replaceChildren();
    let connected = 0;
    for (const [key, [name, icon, role]] of Object.entries(roles)) {
      const bot = bots.find(b => b.bot === key) || {state: 'offline', stale: true};
      const external = Boolean(bot.external_active);
      if (external) connected++;
      const source = bot.heartbeat_source || 'unknown';
      const status = bot.paused ? 'PAUSED' : bot.state === 'error' || bot.last_error ? 'ERROR'
        : bot.stale ? (bot.last_heartbeat ? 'STALE' : 'OFFLINE')
        : source === 'simulation' ? 'PAPER REPLAY'
        : source === 'dashboard_test' ? 'TEST ONLY'
        : external ? 'ACTIVE' : (bot.state || 'offline').toUpperCase();
      const card = document.createElement('article');
      card.className = 'card bot-status-card';
      card.dataset.bot = key;
      const title = document.createElement('h3');
      title.textContent = `${icon} ${name}`;
      const state = document.createElement('strong');
      state.className = 'bot-status-state';
      state.style.color = external ? 'var(--green)' : status === 'ERROR' ? 'var(--red)' : 'var(--amber)';
      state.textContent = status;
      const description = document.createElement('p');
      description.className = 'stat-sub';
      description.textContent = role;
      const connection = document.createElement('p');
      connection.className = 'stat-sub';
      connection.textContent = external ? 'External bot connected' : 'External bot not ready';
      const time = document.createElement('p');
      time.className = 'stat-sub';
      const date = bot.last_heartbeat ? new Date(bot.last_heartbeat + (bot.last_heartbeat.endsWith('Z') ? '' : 'Z')) : null;
      time.textContent = date ? `Last heartbeat: ${date.toLocaleTimeString()}` : 'No heartbeat received';
      const action = document.createElement('p');
      action.className = 'stat-sub';
      action.textContent = bot.last_error || bot.last_action || 'Waiting for bot';
      card.append(title, state, description, connection, time, action);
      grid.append(card);
    }
    summary.textContent = `${connected}/4 external bots active · Refreshes every 15 seconds · Stale after 60 seconds`;
  } catch (error) {
    grid.replaceChildren();
    for (const [key, [name]] of Object.entries(roles)) {
      const card = document.createElement('article');
      card.className = 'card bot-status-card';
      card.dataset.bot = key;
      card.textContent = `${name} — STATUS UNAVAILABLE`;
      grid.append(card);
    }
    summary.textContent = 'Status unavailable — do not assume bots are active.';
  }
}
