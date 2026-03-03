/**
 * ARS Web GUI — Gamestate Tab (Spielstand)
 *
 * Shows:
 *  - Character stat bars (HP, SAN, MP)
 *  - World state as formatted JSON with syntax highlighting
 *  - Filterable event log with timestamps (max 500 entries)
 */

// ── Constants ─────────────────────────────────────────────────────────────────

const MAX_LOG_ENTRIES = 500;

/** Category identifiers for log filter matching */
const CAT_KEEPER    = 'keeper';
const CAT_ARCHIVAR  = 'archivar';
const CAT_ADVENTURE = 'adventure';

/** CSS classes / colors per category */
const CAT_STYLES = {
  [CAT_KEEPER]:    { label: 'Keeper',    color: 'var(--stream-keeper)',   bg: '#2A2015' },
  [CAT_ARCHIVAR]:  { label: 'Archivar',  color: 'var(--stream-archivar)', bg: '#15152A' },
  [CAT_ADVENTURE]: { label: 'Adventure', color: 'var(--green)',           bg: '#152A15' },
};

// ── State ─────────────────────────────────────────────────────────────────────

const _log = [];  // Array of { ts, category, text, id }
let _logIdCounter = 0;

const _char = {
  name: null,
  hp: null, hp_max: null,
  san: null, san_max: null,
  mp: null, mp_max: null,
};

const _worldState = {};  // key -> value

// Filter checkbox state (mirrors DOM checkboxes)
const _filter = {
  [CAT_KEEPER]:    true,
  [CAT_ARCHIVAR]:  true,
  [CAT_ADVENTURE]: true,
};

// ── Timestamps ────────────────────────────────────────────────────────────────

function nowLabel() {
  const d = new Date();
  return [
    String(d.getHours()).padStart(2, '0'),
    String(d.getMinutes()).padStart(2, '0'),
    String(d.getSeconds()).padStart(2, '0'),
  ].join(':');
}

// ── Stat Bar Helpers ──────────────────────────────────────────────────────────

/**
 * Update a single stat bar.
 * @param {string} barId  - DOM id of the fill div
 * @param {string} textId - DOM id of the value span
 * @param {number|null} value
 * @param {number|null} max
 */
function updateStatBar(barId, textId, value, max) {
  const bar  = document.getElementById(barId);
  const text = document.getElementById(textId);
  if (!bar || !text) return;

  if (value === null || value === undefined) {
    bar.style.width = '100%';
    bar.className = 'fill green';
    text.textContent = '-';
    return;
  }

  const safeMax = (max && max > 0) ? max : Math.max(value, 1);
  const pct = Math.max(0, Math.min(100, (value / safeMax) * 100));

  bar.style.width = pct + '%';

  // Color by percentage
  bar.className = 'fill ' + (pct > 50 ? 'green' : pct > 25 ? 'yellow' : 'red');

  text.textContent = max !== null && max !== undefined
    ? `${value}/${max}`
    : String(value);
}

function refreshStatBars() {
  const el = document.getElementById('gs-char-name');
  if (el) el.textContent = _char.name || '-';

  updateStatBar('gs-hp-bar', 'gs-hp-text', _char.hp, _char.hp_max);
  updateStatBar('gs-san-bar', 'gs-san-text', _char.san, _char.san_max);
  updateStatBar('gs-mp-bar', 'gs-mp-text', _char.mp, _char.mp_max);
}

// ── Character Stat Extraction from game.output events ─────────────────────────

/**
 * Attempt to parse character stat data from a game.output event.
 * Handles data payloads with direct stat fields or nested character objects.
 * @param {object} data
 */
function extractCharStats(data) {
  let changed = false;

  // Direct character object
  const char = data.character || data.char || null;
  if (char && typeof char === 'object') {
    if (char.name  !== undefined) { _char.name   = char.name;   changed = true; }
    if (char.hp    !== undefined) { _char.hp      = char.hp;     changed = true; }
    if (char.hp_max !== undefined){ _char.hp_max  = char.hp_max; changed = true; }
    if (char.san   !== undefined) { _char.san     = char.san;    changed = true; }
    if (char.san_max !== undefined){ _char.san_max = char.san_max; changed = true; }
    if (char.mp    !== undefined) { _char.mp      = char.mp;     changed = true; }
    if (char.mp_max !== undefined){ _char.mp_max  = char.mp_max; changed = true; }
  }

  // Flat stat fields at event root
  if (data.hp     !== undefined) { _char.hp      = data.hp;      changed = true; }
  if (data.hp_max !== undefined) { _char.hp_max  = data.hp_max;  changed = true; }
  if (data.san    !== undefined) { _char.san     = data.san;     changed = true; }
  if (data.san_max !== undefined){ _char.san_max = data.san_max; changed = true; }
  if (data.mp     !== undefined) { _char.mp      = data.mp;      changed = true; }
  if (data.mp_max !== undefined) { _char.mp_max  = data.mp_max;  changed = true; }
  if (data.name   !== undefined) { _char.name    = data.name;    changed = true; }

  // stat_changes object (e.g. from STABILITAET_VERLUST processing)
  const changes = data.stat_changes || data.stats || null;
  if (changes && typeof changes === 'object') {
    const keyMap = {
      HP: 'hp', SAN: 'san', SAN_MAX: 'san_max', HP_MAX: 'hp_max',
      MP: 'mp', MP_MAX: 'mp_max',
    };
    for (const [k, v] of Object.entries(changes)) {
      const prop = keyMap[k.toUpperCase()];
      if (prop && typeof v === 'number') {
        _char[prop] = v;
        changed = true;
      }
    }
  }

  if (changed) refreshStatBars();
}

// ── World State Renderer ──────────────────────────────────────────────────────

/**
 * JSON syntax-highlight: keys in accent color, strings in green, numbers in yellow,
 * booleans in orange, null in red.
 * @param {object} obj
 * @returns {string} HTML string
 */
function highlightJson(obj) {
  let json;
  try {
    json = JSON.stringify(obj, null, 2);
  } catch (e) {
    return '<span class="text-muted">[Nicht darstellbar]</span>';
  }

  // Escape HTML first
  json = json
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Apply syntax coloring via regex substitution
  return json.replace(
    /("(\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|-?\d+\.?\d*(?:[eE][+-]?\d+)?|true|false|null)/g,
    (match) => {
      if (/^"/.test(match)) {
        if (/:$/.test(match)) {
          // Key
          return `<span style="color:var(--fg-accent)">${match}</span>`;
        }
        // String value
        return `<span style="color:var(--green)">${match}</span>`;
      }
      if (/true|false/.test(match)) {
        return `<span style="color:var(--orange)">${match}</span>`;
      }
      if (/null/.test(match)) {
        return `<span style="color:var(--red)">${match}</span>`;
      }
      // Number
      return `<span style="color:var(--yellow)">${match}</span>`;
    }
  );
}

function refreshWorldState() {
  const container = document.getElementById('gs-world-state');
  if (!container) return;

  if (Object.keys(_worldState).length === 0) {
    container.innerHTML = '<span class="text-muted">Keine Daten</span>';
    return;
  }

  container.innerHTML = '<pre style="margin:0;white-space:pre-wrap;word-wrap:break-word;">'
    + highlightJson(_worldState) + '</pre>';
}

// ── Event Log ─────────────────────────────────────────────────────────────────

/**
 * Add an entry to the in-memory log and render it.
 * @param {string} category  - CAT_KEEPER | CAT_ARCHIVAR | CAT_ADVENTURE
 * @param {string} text
 */
function addLogEntry(category, text) {
  const entry = {
    id: ++_logIdCounter,
    ts: nowLabel(),
    category,
    text: String(text).slice(0, 1000),  // guard against huge payloads
  };

  _log.push(entry);
  if (_log.length > MAX_LOG_ENTRIES) _log.shift();

  // Render only this new entry (avoid full re-render for performance)
  const container = document.getElementById('gs-event-log');
  if (!container) return;

  const style = CAT_STYLES[category] || { label: category, color: 'var(--fg-muted)', bg: 'transparent' };
  const visible = _filter[category] !== false;

  const row = buildLogRow(entry, style, visible);
  container.appendChild(row);

  // Keep scroll at bottom if already near bottom
  const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 60;
  if (atBottom) container.scrollTop = container.scrollHeight;
}

function buildLogRow(entry, style, visible) {
  const row = document.createElement('div');
  row.dataset.logId   = entry.id;
  row.dataset.category = entry.category;
  row.style.cssText = `
    display:${visible ? 'flex' : 'none'};
    gap:8px;
    padding:2px 4px;
    border-bottom:1px solid var(--bg-button);
    align-items:flex-start;
    font-size:var(--font-sm);
    line-height:1.5;
    background:${style.bg};
  `;

  const ts = document.createElement('span');
  ts.className = 'timestamp';
  ts.style.cssText = 'flex-shrink:0;width:56px;color:var(--fg-muted);';
  ts.textContent = entry.ts;
  row.appendChild(ts);

  const cat = document.createElement('span');
  cat.style.cssText = `flex-shrink:0;width:70px;font-weight:bold;color:${style.color};`;
  cat.textContent = '[' + style.label + ']';
  row.appendChild(cat);

  const msg = document.createElement('span');
  msg.style.cssText = 'flex:1;white-space:pre-wrap;word-wrap:break-word;color:var(--fg-secondary);';
  msg.textContent = entry.text;
  row.appendChild(msg);

  return row;
}

/** Re-render the entire log (called when filter changes). */
function reRenderLog() {
  const container = document.getElementById('gs-event-log');
  if (!container) return;

  container.innerHTML = '';
  for (const entry of _log) {
    const style   = CAT_STYLES[entry.category] || { label: entry.category, color: 'var(--fg-muted)', bg: 'transparent' };
    const visible = _filter[entry.category] !== false;
    container.appendChild(buildLogRow(entry, style, visible));
  }
  container.scrollTop = container.scrollHeight;
}

/** Apply filter visibility to all existing log row DOM nodes (faster than full re-render). */
function applyFilterToDom() {
  const container = document.getElementById('gs-event-log');
  if (!container) return;
  container.querySelectorAll('[data-category]').forEach(row => {
    const cat = row.dataset.category;
    row.style.display = (_filter[cat] !== false) ? 'flex' : 'none';
  });
}

// ── Filter Checkbox Wiring ────────────────────────────────────────────────────

function initFilters() {
  const ids = {
    'gs-filter-keeper':    CAT_KEEPER,
    'gs-filter-archivar':  CAT_ARCHIVAR,
    'gs-filter-adventure': CAT_ADVENTURE,
  };
  for (const [domId, cat] of Object.entries(ids)) {
    const cb = document.getElementById(domId);
    if (!cb) continue;
    cb.checked = _filter[cat];
    cb.addEventListener('change', () => {
      _filter[cat] = cb.checked;
      applyFilterToDom();
    });
  }

  const clearBtn = document.getElementById('gs-clear-log');
  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      _log.length = 0;
      const container = document.getElementById('gs-event-log');
      if (container) container.innerHTML = '';
    });
  }
}

// ── Short event text helpers ──────────────────────────────────────────────────

function shortText(data, maxLen = 200) {
  if (!data || typeof data !== 'object') return String(data).slice(0, maxLen);
  const parts = [];
  if (data.response)  parts.push(data.response.slice(0, 120));
  if (data.text)      parts.push(data.text.slice(0, 120));
  if (data.prompt)    parts.push('Prompt: ' + data.prompt.slice(0, 80));
  if (data.location_name) parts.push('Ort: ' + data.location_name);
  if (data.flag)      parts.push('Flag: ' + data.flag + ' = ' + data.value);
  if (data.message)   parts.push(data.message.slice(0, 120));
  if (data.warning)   parts.push('[WARN] ' + data.warning.slice(0, 100));
  if (parts.length === 0) {
    return JSON.stringify(data).slice(0, maxLen);
  }
  return parts.join(' | ').slice(0, maxLen);
}

// ── Event Handlers ────────────────────────────────────────────────────────────

function handleKeeperEvent(eventName, data) {
  let text = '';
  if (eventName === 'keeper.prompt_sent') {
    const len = (data.prompt || '').length;
    text = `Prompt gesendet (${len} Zeichen)`;
  } else if (eventName === 'keeper.response_complete') {
    const resp = data.response || data.text || '';
    text = resp.slice(0, 160) + (resp.length > 160 ? '…' : '');
  } else if (eventName === 'keeper.usage_update') {
    const total = data.total_tokens || 0;
    const cost  = data.session_cost || 0;
    text = `Tokens: ${total.toLocaleString()} | Session-Kosten: $${cost.toFixed(4)}`;
  }
  if (text) addLogEntry(CAT_KEEPER, `[${eventName}] ${text}`);
}

function handleArchivarEvent(eventName, data) {
  if (eventName === 'archivar.world_state_updated') {
    const ws = data.world_state || data;
    if (ws && typeof ws === 'object') {
      Object.assign(_worldState, ws);
      refreshWorldState();
    }
    addLogEntry(CAT_ARCHIVAR, '[world_state_updated] ' + shortText(data));
  } else if (eventName === 'archivar.chronicle_updated') {
    addLogEntry(CAT_ARCHIVAR, '[chronicle_updated] ' + shortText(data));
  }
}

function handleAdventureEvent(eventName, data) {
  if (eventName === 'adventure.location_changed') {
    const loc = data.location_name || data.location || JSON.stringify(data);
    addLogEntry(CAT_ADVENTURE, `[location_changed] ${loc}`);
  } else if (eventName === 'adventure.flag_changed') {
    const flag = data.flag || '';
    const val  = data.value !== undefined ? data.value : '?';
    addLogEntry(CAT_ADVENTURE, `[flag_changed] ${flag} = ${val}`);
  }
}

function handleGameOutput(data) {
  // Extract character stats from any game.output event
  extractCharStats(data);

  // Log specific game output tags
  const tag = data.tag || '';
  if (tag === 'stat' || tag === 'probe' || tag === 'dice') {
    const text = data.text || data.message || shortText(data);
    addLogEntry(CAT_KEEPER, `[game.output/${tag}] ${text.slice(0, 160)}`);
  }
}

// ── Tab Module ────────────────────────────────────────────────────────────────

const gamestateTab = {
  init(container) {
    initFilters();
    refreshStatBars();
    refreshWorldState();
  },

  handleEvent(eventName, data) {
    // Keeper events
    if (
      eventName === 'keeper.prompt_sent'      ||
      eventName === 'keeper.response_complete' ||
      eventName === 'keeper.usage_update'
    ) {
      handleKeeperEvent(eventName, data);
    }

    // Archivar events
    if (
      eventName === 'archivar.chronicle_updated'  ||
      eventName === 'archivar.world_state_updated'
    ) {
      handleArchivarEvent(eventName, data);
    }

    // Adventure events
    if (
      eventName === 'adventure.location_changed' ||
      eventName === 'adventure.flag_changed'
    ) {
      handleAdventureEvent(eventName, data);
    }

    // Game output — stat updates + selected log entries
    if (eventName === 'game.output') {
      handleGameOutput(data);
    }

    // Engine state changes — update char stats if present
    if (eventName === 'techgui.state_changed' || eventName === 'techgui.engine_ready') {
      if (data.character) extractCharStats(data.character);
    }
  },

  onEngineReady(discovery) {
    // Reset world state and character on new session
    for (const k of Object.keys(_worldState)) delete _worldState[k];
    _char.name    = null;
    _char.hp      = null; _char.hp_max  = null;
    _char.san     = null; _char.san_max = null;
    _char.mp      = null; _char.mp_max  = null;

    refreshStatBars();
    refreshWorldState();

    addLogEntry(CAT_ADVENTURE, '[engine_ready] Engine bereit — Session gestartet');
  },

  onActivate() {
    // Scroll log to bottom when tab becomes visible
    const log = document.getElementById('gs-event-log');
    if (log) log.scrollTop = log.scrollHeight;
  },
};

ARS.registerTab('gamestate', gamestateTab);
