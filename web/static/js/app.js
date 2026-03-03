/**
 * ARS Web GUI — Main Application
 *
 * Manages WebSocket connection, tab navigation, and event dispatch to tabs.
 */

import bus from './eventbus.js';

// ── Tab Registry ───────────────────────────────────────────────

const tabs = {};          // tabId -> { init, handleEvent, onEngineReady }
const tabButtons = [];    // DOM buttons
let activeTab = null;
let ws = null;
let reconnectTimer = null;
let engineState = 'stopped';
let discoveryData = {};

// ── WebSocket ──────────────────────────────────────────────────

function connectWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${proto}//${location.host}/ws`;

  ws = new WebSocket(url);

  ws.onopen = () => {
    console.log('WebSocket connected');
    updateConnectionIndicator(true);
    if (reconnectTimer) {
      clearInterval(reconnectTimer);
      reconnectTimer = null;
    }
  };

  ws.onclose = () => {
    console.log('WebSocket disconnected');
    updateConnectionIndicator(false);
    scheduleReconnect();
  };

  ws.onerror = (err) => {
    console.error('WebSocket error:', err);
  };

  ws.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      handleServerMessage(msg);
    } catch (e) {
      console.error('WS parse error:', e);
    }
  };
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setInterval(() => {
    if (!ws || ws.readyState === WebSocket.CLOSED) {
      console.log('Reconnecting WebSocket...');
      connectWebSocket();
    }
  }, 3000);
}

function sendWS(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
  }
}

function updateConnectionIndicator(connected) {
  const el = document.getElementById('ws-status');
  if (el) {
    el.textContent = connected ? 'WS' : 'WS!';
    el.className = connected ? 'text-green' : 'text-red';
  }
}

// ── Server Message Handler ─────────────────────────────────────

function handleServerMessage(msg) {
  if (msg.type === 'state') {
    // Initial state on connect
    updateEngineState(msg.data);
  } else if (msg.type === 'event') {
    const event = msg.event || '';
    const data = msg.data || {};

    // Update internal state
    if (event === 'techgui.state_changed') {
      updateEngineState(data);
    } else if (event === 'techgui.engine_ready') {
      engineState = 'running';
      updateStatusBar(data);
      // Fetch fresh discovery data
      fetchDiscovery().then(() => {
        dispatchToTabs('onEngineReady', discoveryData);
      });
      // Switch to game tab
      switchTab('game');
    } else if (event === 'techgui.engine_error') {
      engineState = 'error';
      showNotification(data.error || 'Engine Fehler', 'error');
    } else if (event === 'game.player_dead') {
      engineState = 'dead';
      showDeathDialog(data);
    }

    // Forward to client EventBus
    bus.emit(event, data);

    // Dispatch to all tabs
    dispatchToTabs('handleEvent', event, data);

    // Update status bar on key events
    if (event === 'keeper.usage_update') {
      updateCost(data);
    } else if (event === 'keeper.response_complete') {
      updateTurn(data);
    } else if (event === 'adventure.location_changed') {
      updateLocation(data);
    }
  }
}

// ── Engine State ───────────────────────────────────────────────

function updateEngineState(data) {
  if (data.state) engineState = data.state;
  const el = document.getElementById('engine-state');
  if (el) {
    const labels = {
      stopped: 'Stopped', initializing: 'Init...', running: 'Running',
      paused: 'Paused', error: 'Error', dead: 'Dead',
    };
    const classes = {
      stopped: 'state-stopped', initializing: 'state-init', running: 'state-running',
      paused: 'state-paused', error: 'state-error', dead: 'state-dead',
    };
    el.textContent = labels[engineState] || engineState;
    el.className = 'value ' + (classes[engineState] || '');
  }

  // Update character stats if present
  if (data.character) {
    updateCharacterStatus(data.character);
  }
}

// ── Status Bar ─────────────────────────────────────────────────

let sessionTimer = null;
let sessionStartTime = null;

function updateStatusBar(data) {
  if (data.module) {
    const el = document.getElementById('status-module');
    if (el) el.textContent = data.module;
  }
  // Start session timer
  startSessionTimer();
}

function updateTurn(data) {
  const el = document.getElementById('status-turn');
  if (el) {
    const turn = Math.floor((data.history_len || 0) / 2);
    el.textContent = turn;
  }
}

function updateLocation(data) {
  const el = document.getElementById('status-location');
  if (el) el.textContent = data.location_name || '';
}

function updateCost(data) {
  const el = document.getElementById('status-cost');
  if (el) {
    const cost = data.session_cost || 0;
    el.textContent = '$' + cost.toFixed(4);
  }
}

function updateCharacterStatus(char) {
  const el = document.getElementById('status-character');
  if (el) {
    const parts = [char.name || ''];
    if (char.hp !== undefined) parts.push(`HP:${char.hp}/${char.hp_max}`);
    if (char.san !== undefined && char.san !== null) parts.push(`SAN:${char.san}/${char.san_max}`);
    el.textContent = parts.join(' | ');
  }
}

function startSessionTimer() {
  sessionStartTime = Date.now();
  if (sessionTimer) clearInterval(sessionTimer);
  sessionTimer = setInterval(() => {
    const el = document.getElementById('status-duration');
    if (el && sessionStartTime) {
      const s = Math.floor((Date.now() - sessionStartTime) / 1000);
      const m = Math.floor(s / 60);
      const h = Math.floor(m / 60);
      el.textContent = `${h}:${String(m % 60).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
    }
  }, 1000);
}

// ── Tab Navigation ─────────────────────────────────────────────

function initTabs() {
  const bar = document.getElementById('tab-bar');
  if (!bar) return;

  bar.querySelectorAll('button[data-tab]').forEach(btn => {
    tabButtons.push(btn);
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  // Init all tab modules
  for (const [id, tab] of Object.entries(tabs)) {
    const container = document.getElementById('tab-' + id);
    if (container && tab.init) {
      try { tab.init(container); } catch (e) { console.error(`Tab init [${id}]:`, e); }
    }
  }

  // Activate default tab
  switchTab('session');
}

function switchTab(tabId) {
  // Deactivate all
  tabButtons.forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));

  // Activate target
  const btn = tabButtons.find(b => b.dataset.tab === tabId);
  const panel = document.getElementById('tab-' + tabId);
  if (btn) btn.classList.add('active');
  if (panel) panel.classList.add('active');
  activeTab = tabId;

  // Notify tab
  if (tabs[tabId] && tabs[tabId].onActivate) {
    tabs[tabId].onActivate();
  }
}

function dispatchToTabs(method, ...args) {
  for (const tab of Object.values(tabs)) {
    if (tab[method]) {
      try { tab[method](...args); } catch (e) { console.error(`Tab ${method}:`, e); }
    }
  }
}

// ── Tab Registration ───────────────────────────────────────────

function registerTab(id, tabModule) {
  tabs[id] = tabModule;
}

// ── Discovery ──────────────────────────────────────────────────

async function fetchDiscovery() {
  try {
    const resp = await fetch('/api/discovery');
    discoveryData = await resp.json();
  } catch (e) {
    console.error('Discovery fetch failed:', e);
  }
}

// ── Death Dialog ───────────────────────────────────────────────

function showDeathDialog(data) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal" style="text-align:center;">
      <div style="font-size:48px;margin-bottom:12px;">&#9760;</div>
      <div class="modal-header">Dein Charakter ist gestorben</div>
      <p class="mb">${data.message || 'Das Abenteuer endet hier.'}</p>
      <div class="flex gap justify-center" style="justify-content:center;">
        <button class="btn-accent" onclick="this.closest('.modal-overlay').remove()">Weiter zusehen</button>
        <button class="btn-danger" id="death-quit">Beenden</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.querySelector('#death-quit')?.addEventListener('click', () => {
    sendWS({ type: 'engine_control', action: 'stop' });
    overlay.remove();
  });
}

// ── Notifications ──────────────────────────────────────────────

function showNotification(text, level = 'info') {
  const el = document.createElement('div');
  el.style.cssText = `
    position: fixed; top: 40px; right: 16px; z-index: 2000;
    padding: 10px 16px; border-radius: 6px;
    background: var(--bg-panel); border: 1px solid var(--bg-button);
    color: ${level === 'error' ? 'var(--red)' : 'var(--fg-primary)'};
    font-family: var(--font-family); font-size: var(--font-size);
    box-shadow: 0 4px 12px rgba(0,0,0,0.4);
    animation: fadeIn 0.2s ease;
  `;
  el.textContent = text;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

// ── Public API ─────────────────────────────────────────────────

window.ARS = {
  bus,
  sendWS,
  registerTab,
  switchTab,
  fetchDiscovery,
  showNotification,
  getEngineState: () => engineState,
  getDiscovery: () => discoveryData,
};

// ── Boot ───────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  await fetchDiscovery();
  initTabs();
  connectWebSocket();
  console.log('ARS Web GUI ready');
});

export { registerTab, sendWS, bus };
