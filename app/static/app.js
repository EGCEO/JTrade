const api = async (path, opts = {}) => {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
};

const fmt = (n, d = 2) => (n == null || n === '' ? '—' : Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }));
const tag = (cls, txt) => `<span class="tag tag-${cls}">${txt}</span>`;

async function logout() {
  await api('/logout', { method: 'POST' });
  location.href = '/login';
}

async function loadTopbar() {
  try {
    const cfg = await api('/api/config');
    const badge = document.getElementById('modeBadge');
    if (cfg.is_real_execution) {
      badge.textContent = 'REAL EXECUTION';
      badge.className = 'badge badge-real';
    } else {
      badge.textContent = 'PAPER';
      badge.className = 'badge badge-paper';
    }
    const aggr = document.getElementById('aggrBadge');
    if (aggr) aggr.style.display = cfg.is_aggressive ? '' : 'none';
    const runBadge = document.getElementById('runBadge');
    if (runBadge) {
      runBadge.textContent = cfg.is_running ? 'RUNNING' : 'STOPPED';
      runBadge.className = cfg.is_running ? 'badge badge-running' : 'badge badge-stopped';
    }
    const bal = document.getElementById('balancePill');
    const b = cfg.is_real_execution ? cfg.current_balance_real : cfg.current_balance_paper;
    bal.textContent = `$${fmt(b)}`;
  } catch (e) { /* not logged in */ }

  // Notification count
  try {
    const n = await api('/api/notifications?limit=1');
    const cnt = document.getElementById('notifCount');
    if (cnt) {
      cnt.textContent = n.unread || '';
      cnt.style.display = n.unread > 0 ? '' : 'none';
    }
  } catch (e) {}
}
loadTopbar();

// Chart.js default theme
if (typeof Chart !== 'undefined') {
  Chart.defaults.color = '#8b95a7';
  Chart.defaults.borderColor = '#1f2a40';
  Chart.defaults.font.family = "'Inter',system-ui,sans-serif";
}
