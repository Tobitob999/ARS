/**
 * ARS Web GUI — Game Tab
 *
 * Main gameplay interface: streaming keeper output, player input,
 * stat bars (HP/SAN/MP), dice history visualization, inventory,
 * location display, and engine control shortcuts.
 *
 * Streaming model:
 *   stream_start  → record a "current stream block" node in the output
 *   stream_chunk  → append text to that node
 *   stream_end    → finalize (replace chunk node with complete text)
 *
 * Dice parsing covers:
 *   - d100 probes:  [PROBE: Skill | Roll/Target] or "PROBE: Skill: Roll gegen Target"
 *   - d20 probes:   similar pattern, target expressed as target value
 *   - d6 pools:     "d6-Pool [N]: Wuerfel: 2,5,6,1,4 -> N Hits (Schwelle: N)"
 */

// ── Constants ───────────────────────────────────────────────────

const MAX_DICE_CARDS  = 5;
const MAX_OUTPUT_LINES = 800;  // prune oldest lines to prevent DOM bloat
const SCROLL_THROTTLE_MS = 80; // minimum ms between forced scrolls

// Regex patterns for dice parsing
const RE_PROBE_TAG     = /\[PROBE:\s*([^\|]+?)\s*\|\s*(\d+)\s*\/\s*(\d+)\s*\]/i;
const RE_PROBE_TEXT    = /PROBE:\s*([^:]+):\s*(\d+)\s+gegen\s+(\d+)/i;
const RE_DICE_LINE     = /Wurf:\s*(\d+)\s*\|\s*Ziel:\s*(\d+)\s*\|\s*(.+)/i;
const RE_D6_POOL       = /d6-Pool\s*\[(\d+)\]:\s*Wuerfel:\s*([\d,\s]+)\s*->\s*(\d+)\s*Hits?\s*\(Schwelle:\s*(\d+)\)/i;
const RE_STAT_UPDATE   = /\[STAT:\s*(\w+)\s*([+\-]\d+|=\d+)\]/i;
const RE_INVENTAR_ADD  = /\[INVENTAR:\s*\+([^\]]+)\]/i;
const RE_INVENTAR_DEL  = /\[INVENTAR:\s*-([^\]]+)\]/i;

// Success level labels (used when we get a structured dice event)
const SUCCESS_LEVELS = {
  'extreme':          { label: 'Extremer Erfolg',   cls: 'success'          },
  'hard':             { label: 'Schwieriger Erfolg', cls: 'success'          },
  'regular':          { label: 'Erfolg',             cls: 'success'          },
  'success':          { label: 'Erfolg',             cls: 'success'          },
  'critical':         { label: 'Kritischer Erfolg',  cls: 'critical-success' },
  'failure':          { label: 'Fehlschlag',         cls: 'failure'          },
  'fumble':           { label: 'Patzer!',            cls: 'critical-failure' },
};

// ── Module state ────────────────────────────────────────────────

let _outputEl        = null;   // #game-output
let _inputEl         = null;   // #game-input
let _sendBtn         = null;   // #game-btn-send
let _diceContainer   = null;   // #game-dice-history
let _inventoryEl     = null;   // #game-inventory
let _locationEl      = null;   // #game-location

let _streamNode      = null;   // current <span> being filled during streaming
let _streamBuffer    = '';     // accumulated stream text

let _waitingForInput = false;
let _engineRunning   = false;
let _enginePaused    = false;

/** @type {Array<Object>} dice card data objects, newest first */
let _diceHistory     = [];

/** @type {Set<string>} current inventory items */
let _inventory       = new Set();

/** Throttle scroll: timestamp of last forced scroll */
let _lastScrollTime  = 0;

// ── Stat bar state ──────────────────────────────────────────────

const _stats = {
  hp:  { cur: null, max: null },
  san: { cur: null, max: null },
  mp:  { cur: null, max: null },
};

// ── Scroll helper ────────────────────────────────────────────────

function scrollToBottom() {
  if (!_outputEl) return;
  const now = Date.now();
  if (now - _lastScrollTime < SCROLL_THROTTLE_MS) return;
  _lastScrollTime = now;
  _outputEl.scrollTop = _outputEl.scrollHeight;
}

// ── Output append helpers ────────────────────────────────────────

/**
 * Append a line of text to the output as a <div> with a CSS class.
 * @param {string} text
 * @param {string} cssClass
 * @param {boolean} addNewline - whether to append a trailing newline div
 */
function appendLine(text, cssClass, addNewline = true) {
  if (!_outputEl || !text) return;

  const div = document.createElement('div');
  div.className = cssClass;
  div.textContent = text;
  _outputEl.appendChild(div);

  if (addNewline) {
    const spacer = document.createElement('div');
    spacer.style.height = '2px';
    _outputEl.appendChild(spacer);
  }

  // Prune output to prevent unbounded DOM growth
  while (_outputEl.childElementCount > MAX_OUTPUT_LINES) {
    _outputEl.removeChild(_outputEl.firstElementChild);
  }

  scrollToBottom();
}

/**
 * Append a separator line.
 */
function appendSeparator() {
  if (!_outputEl) return;
  const hr = document.createElement('hr');
  hr.style.cssText = 'border:none;border-top:1px solid var(--bg-button);margin:4px 0;';
  _outputEl.appendChild(hr);
}

// ── Streaming ───────────────────────────────────────────────────

function onStreamStart() {
  if (!_outputEl) return;
  appendSeparator();

  // Create a streaming span that we'll fill incrementally
  _streamNode = document.createElement('span');
  _streamNode.className = 'keeper';
  _streamBuffer = '';

  const wrapper = document.createElement('div');
  wrapper.appendChild(_streamNode);
  _outputEl.appendChild(wrapper);

  scrollToBottom();
}

function onStreamChunk(text) {
  if (!_streamNode || !text) return;
  _streamBuffer += text;
  _streamNode.textContent = _streamBuffer;
  scrollToBottom();
}

function onStreamEnd(fullText) {
  // If we have a stream node, finalize it with the complete authoritative text.
  // (The server sends the truncated/validated full text in stream_end.text.)
  if (_streamNode) {
    const final = fullText || _streamBuffer;
    _streamNode.textContent = final;
    _streamNode = null;
    _streamBuffer = '';
  }
  scrollToBottom();
}

// ── Input handling ───────────────────────────────────────────────

function setInputEnabled(enabled) {
  if (_inputEl) _inputEl.disabled = !enabled;
  if (_sendBtn) _sendBtn.disabled = !enabled;
  if (enabled && _inputEl) _inputEl.focus();
}

function sendPlayerInput() {
  if (!_waitingForInput) return;
  const text = (_inputEl?.value || '').trim();
  if (!text) return;

  // Show in output
  appendLine('> ' + text, 'player');

  // Send over WebSocket
  ARS.sendWS({ type: 'player_input', text });

  // Clear and disable until next waiting_for_input
  if (_inputEl) _inputEl.value = '';
  _waitingForInput = false;
  setInputEnabled(false);
}

// ── Stat bars ────────────────────────────────────────────────────

/**
 * Update a stat bar.
 * @param {string} key - 'hp' | 'san' | 'mp'
 * @param {number|null} cur
 * @param {number|null} max
 */
function updateStatBar(key, cur, max) {
  if (cur === null || cur === undefined) return;
  if (max === null || max === undefined || max === 0) max = cur || 1;

  _stats[key].cur = cur;
  _stats[key].max = max;

  const pct = Math.max(0, Math.min(100, (cur / max) * 100));

  const barEl  = document.getElementById(`game-${key}-bar`);
  const textEl = document.getElementById(`game-${key}-text`);

  if (barEl) {
    barEl.style.width = pct.toFixed(1) + '%';
    barEl.className = 'fill ' + barColorClass(pct);
  }
  if (textEl) {
    textEl.textContent = `${cur}/${max}`;
  }
}

function barColorClass(pct) {
  if (pct > 50) return 'green';
  if (pct > 25) return 'yellow';
  return 'red';
}

/**
 * Parse a [STAT: KEY +/-N] tag string and update the appropriate bar.
 * @param {string} text
 */
function parseAndApplyStat(text) {
  const m = text.match(RE_STAT_UPDATE);
  if (!m) return;

  const statKey = m[1].toUpperCase();
  const expr    = m[2];

  let key = null;
  if (statKey === 'HP')  key = 'hp';
  if (statKey === 'SAN') key = 'san';
  if (statKey === 'MP')  key = 'mp';
  if (!key) return;

  const current = _stats[key].cur ?? 0;
  const max     = _stats[key].max ?? 10;

  let newVal;
  if (expr.startsWith('=')) {
    newVal = parseInt(expr.slice(1), 10);
  } else {
    newVal = current + parseInt(expr, 10);
  }

  updateStatBar(key, newVal, max);
}

/**
 * Sync all stat bars from a character object.
 * @param {Object} char
 */
function syncCharacter(char) {
  if (!char) return;

  const nameEl = document.getElementById('game-char-name');
  if (nameEl && char.name) nameEl.textContent = char.name;

  if (char.hp !== undefined)  updateStatBar('hp',  char.hp,  char.hp_max  || char.hp);
  if (char.san !== undefined) updateStatBar('san', char.san, char.san_max || char.san);
  if (char.mp !== undefined)  updateStatBar('mp',  char.mp,  char.mp_max  || char.mp);
}

// ── Inventory ────────────────────────────────────────────────────

function renderInventory() {
  if (!_inventoryEl) return;
  if (_inventory.size === 0) {
    _inventoryEl.textContent = '(leer)';
    return;
  }
  _inventoryEl.textContent = Array.from(_inventory).join('\n');
}

function parseInventoryTag(text) {
  const addMatch = text.match(RE_INVENTAR_ADD);
  if (addMatch) {
    _inventory.add(addMatch[1].trim());
    renderInventory();
    return;
  }
  const delMatch = text.match(RE_INVENTAR_DEL);
  if (delMatch) {
    _inventory.delete(delMatch[1].trim());
    renderInventory();
  }
}

// ── Dice visualization ───────────────────────────────────────────

/**
 * Attempt to parse a dice text string into a dice card data object.
 * Handles three formats:
 *   1. [PROBE: Skill | Roll/Target] tag
 *   2. "PROBE: Skill: Roll gegen Target" natural text
 *   3. d6-Pool line (Shadowrun)
 *
 * Returns null if text cannot be parsed.
 *
 * @param {string} text
 * @returns {Object|null}
 */
function parseDiceText(text) {
  if (!text) return null;

  // Format 1: [PROBE: Skill | Roll/Target]
  let m = text.match(RE_PROBE_TAG);
  if (m) {
    const skill  = m[1].trim();
    const roll   = parseInt(m[2], 10);
    const target = parseInt(m[3], 10);
    return buildD100Card(skill, roll, target);
  }

  // Format 2: PROBE: Skill: Roll gegen Target (from mechanics.py formatted output)
  m = text.match(RE_PROBE_TEXT);
  if (m) {
    const skill  = m[1].trim();
    const roll   = parseInt(m[2], 10);
    const target = parseInt(m[3], 10);
    return buildD100Card(skill, roll, target);
  }

  // Format 3: "Wurf: N | Ziel: N | [OK]/[!!] Level" (from _format_result)
  m = text.match(RE_DICE_LINE);
  if (m) {
    const roll        = parseInt(m[1], 10);
    const target      = parseInt(m[2], 10);
    const resultLabel = m[3].trim();
    const success     = !resultLabel.includes('[!!]') && !resultLabel.toLowerCase().includes('fehlschlag') && !resultLabel.toLowerCase().includes('patzer');
    const isCrit      = resultLabel.toLowerCase().includes('kritisch');
    const isFumble    = resultLabel.toLowerCase().includes('patzer');
    return {
      type:    'd100',
      skill:   null,
      roll,
      target,
      success,
      isCrit,
      isFumble,
      label:   resultLabel,
      dice:    null,
    };
  }

  // Format 4: d6-Pool line (Shadowrun)
  m = text.match(RE_D6_POOL);
  if (m) {
    const poolSize  = parseInt(m[1], 10);
    const diceVals  = m[2].split(',').map(s => parseInt(s.trim(), 10)).filter(n => !isNaN(n));
    const hits      = parseInt(m[3], 10);
    const threshold = parseInt(m[4], 10);
    const success   = hits >= threshold;
    return {
      type:      'd6pool',
      skill:     null,
      poolSize,
      dice:      diceVals,
      hits,
      threshold,
      success,
      isCrit:    false,
      isFumble:  false,
      label:     success ? `${hits} Hits (Schwelle: ${threshold})` : `${hits} Hits — Fehlschlag`,
    };
  }

  return null;
}

/**
 * Build a d100 card data object with success classification.
 * @param {string} skill
 * @param {number} roll
 * @param {number} target
 * @returns {Object}
 */
function buildD100Card(skill, roll, target) {
  // CoC 7E success levels
  // Critical: 01 (or 1)
  // Extreme:  <= floor(target/5)
  // Hard:     <= floor(target/2)
  // Regular:  <= target
  // Fumble:   96-100 (or >target if target<50: >=96)
  const isFumble  = roll >= 96 || (target < 50 && roll >= 100);
  const isCrit    = roll === 1;
  const isExtreme = !isFumble && !isCrit && roll <= Math.floor(target / 5);
  const isHard    = !isFumble && !isCrit && !isExtreme && roll <= Math.floor(target / 2);
  const isReg     = !isFumble && !isCrit && !isExtreme && !isHard && roll <= target;
  const success   = isCrit || isExtreme || isHard || isReg;

  let levelKey, label;
  if (isFumble)       { levelKey = 'fumble';   label = 'Patzer!'; }
  else if (isCrit)    { levelKey = 'critical';  label = 'Kritischer Erfolg'; }
  else if (isExtreme) { levelKey = 'extreme';   label = 'Extremer Erfolg'; }
  else if (isHard)    { levelKey = 'hard';      label = 'Schwieriger Erfolg'; }
  else if (isReg)     { levelKey = 'regular';   label = 'Erfolg'; }
  else                { levelKey = 'failure';   label = 'Fehlschlag'; }

  return {
    type:     'd100',
    skill,
    roll,
    target,
    success,
    isCrit,
    isFumble,
    label,
    levelKey,
    dice:     null,
  };
}

/**
 * Also handle structured keeper/dice_roll events (emitted by ai_backend.py)
 * which carry a clean payload.
 *
 * @param {Object} data
 */
function handleDiceRollEvent(data) {
  if (!data) return;

  // Structured payload: { skill, roll, target, success_level, dice_type }
  if (data.dice_type === 'd6pool') {
    const card = {
      type:      'd6pool',
      skill:     data.skill || null,
      poolSize:  data.pool_size || 0,
      dice:      data.dice_values || [],
      hits:      data.hits || 0,
      threshold: data.threshold || 1,
      success:   data.success !== false,
      isCrit:    false,
      isFumble:  false,
      label:     data.result_label || '',
    };
    pushDiceCard(card);
    return;
  }

  const level   = (data.success_level || '').toLowerCase();
  const levelInfo = SUCCESS_LEVELS[level] || SUCCESS_LEVELS['failure'];
  const card = {
    type:     data.dice_type || 'd100',
    skill:    data.skill || null,
    roll:     data.roll || 0,
    target:   data.target || 0,
    success:  data.success !== false,
    isCrit:   level === 'critical',
    isFumble: level === 'fumble',
    label:    levelInfo.label,
    levelKey: level,
    dice:     null,
  };
  pushDiceCard(card);
}

/**
 * Add a dice card to history (newest first) and re-render.
 * @param {Object} card
 */
function pushDiceCard(card) {
  if (!card) return;
  _diceHistory.unshift(card);
  if (_diceHistory.length > MAX_DICE_CARDS) {
    _diceHistory.length = MAX_DICE_CARDS;
  }
  renderDiceHistory();
}

/**
 * Rebuild the dice history panel from _diceHistory.
 */
function renderDiceHistory() {
  if (!_diceContainer) return;
  _diceContainer.innerHTML = '';

  if (_diceHistory.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'text-muted text-sm';
    empty.textContent = 'Noch keine Wuerfe';
    _diceContainer.appendChild(empty);
    return;
  }

  for (let i = 0; i < _diceHistory.length; i++) {
    const card = _diceHistory[i];
    const el = buildDiceCardElement(card, i === 0);
    _diceContainer.appendChild(el);
  }
}

/**
 * Build a dice card DOM element.
 * @param {Object} card
 * @param {boolean} isLatest - true for the newest card (gets highlighted border)
 * @returns {HTMLElement}
 */
function buildDiceCardElement(card, isLatest) {
  const el = document.createElement('div');
  el.className = 'dice-card';

  if (isLatest) {
    // Highlight newest card
    const borderColor = card.success ? 'var(--green)' : 'var(--red)';
    el.style.borderColor = borderColor;
    el.style.background  = 'var(--bg-panel)';
  }

  // Header: skill name (left) + result label (right)
  const header = document.createElement('div');
  header.className = 'dice-header';

  const skillSpan = document.createElement('span');
  skillSpan.textContent = card.skill || (card.type === 'd6pool' ? 'W6-Pool' : 'Wurf');

  const labelSpan = document.createElement('span');
  labelSpan.textContent = card.label || '';

  header.appendChild(skillSpan);
  header.appendChild(labelSpan);
  el.appendChild(header);

  // Result line
  if (card.type === 'd6pool') {
    // Show "Hits / Schwelle" as the big number
    const result = document.createElement('div');
    result.className = 'dice-result ' + (card.success ? 'success' : 'failure');
    result.textContent = `${card.hits} / ${card.threshold} Hits`;
    el.appendChild(result);

    // Individual dice boxes
    if (card.dice && card.dice.length > 0) {
      const pool = document.createElement('div');
      pool.className = 'dice-pool';
      for (const val of card.dice) {
        const die = document.createElement('div');
        die.className = 'die ' + (val >= 5 ? 'hit' : 'miss');
        die.textContent = val;
        pool.appendChild(die);
      }
      el.appendChild(pool);
    }
  } else {
    // d100 / d20 — show Roll vs Target
    const result = document.createElement('div');
    let resultClass = 'dice-result ';
    if (card.isFumble)    resultClass += 'critical-failure';
    else if (card.isCrit) resultClass += 'critical-success';
    else if (card.success) resultClass += 'success';
    else                   resultClass += 'failure';

    result.className  = resultClass;
    result.textContent = `${card.roll} / ${card.target}`;
    el.appendChild(result);
  }

  return el;
}

// ── Engine button management ─────────────────────────────────────

function setEngineRunning(running, paused = false) {
  _engineRunning = running;
  _enginePaused  = paused;

  const btnStart = document.getElementById('game-btn-start');
  const btnPause = document.getElementById('game-btn-pause');
  const btnStop  = document.getElementById('game-btn-stop');

  if (!btnStart || !btnPause || !btnStop) return;

  if (running) {
    btnStart.disabled = true;
    btnPause.disabled = false;
    btnStop.disabled  = false;
    btnPause.textContent = paused ? 'Fortsetzen' : 'Pause';
  } else {
    btnStart.disabled = false;
    btnPause.disabled = true;
    btnStop.disabled  = true;
    btnPause.textContent = 'Pause';
    setInputEnabled(false);
    _waitingForInput = false;
  }
}

// ── Tab init ─────────────────────────────────────────────────────

function init(container) {
  _outputEl      = document.getElementById('game-output');
  _inputEl       = document.getElementById('game-input');
  _sendBtn       = document.getElementById('game-btn-send');
  _diceContainer = document.getElementById('game-dice-history');
  _inventoryEl   = document.getElementById('game-inventory');
  _locationEl    = document.getElementById('game-location');

  // Initial dice panel state
  renderDiceHistory();

  // Send button
  if (_sendBtn) {
    _sendBtn.addEventListener('click', sendPlayerInput);
  }

  // Enter key in input
  if (_inputEl) {
    _inputEl.addEventListener('keydown', (evt) => {
      if (evt.key === 'Enter' && !evt.shiftKey) {
        evt.preventDefault();
        sendPlayerInput();
      }
    });
  }

  // Engine control buttons (mirrored from session tab)
  const btnStart = document.getElementById('game-btn-start');
  const btnPause = document.getElementById('game-btn-pause');
  const btnStop  = document.getElementById('game-btn-stop');

  if (btnStart) {
    btnStart.addEventListener('click', () => {
      // Navigate to session tab for full config, or start with defaults
      ARS.switchTab('session');
    });
  }

  if (btnPause) {
    btnPause.addEventListener('click', () => {
      const action = _enginePaused ? 'resume' : 'pause';
      ARS.sendWS({ type: 'engine_control', action });
    });
  }

  if (btnStop) {
    btnStop.addEventListener('click', () => {
      ARS.sendWS({ type: 'engine_control', action: 'stop' });
    });
  }

  // Reflect current engine state
  const state = ARS.getEngineState();
  setEngineRunning(state === 'running' || state === 'paused', state === 'paused');
}

// ── handleEvent ──────────────────────────────────────────────────

function handleEvent(eventName, data) {
  switch (eventName) {

    // ── Streaming output ──────────────────────────────────────
    case 'game.output': {
      const tag  = data.tag  || '';
      const text = data.text || '';

      switch (tag) {
        case 'stream_start':
          onStreamStart();
          break;

        case 'stream_chunk':
          onStreamChunk(text);
          break;

        case 'stream_end':
          onStreamEnd(text);
          break;

        case 'player':
          appendLine('> ' + text, 'player');
          break;

        case 'probe': {
          appendLine(text, 'probe');
          // Try to parse a dice card from the probe text
          const card = parseDiceText(text);
          if (card) pushDiceCard(card);
          break;
        }

        case 'dice': {
          appendLine(text, 'dice');
          // Try to parse d6-pool or dice result line
          const dCard = parseDiceText(text);
          if (dCard) pushDiceCard(dCard);
          break;
        }

        case 'combat':
          appendLine(text, 'combat');
          break;

        case 'initiative':
          appendLine(text, 'combat');
          break;

        case 'combat_state':
          appendLine(text, 'combat');
          break;

        case 'stat':
          appendLine(text, 'stat');
          parseAndApplyStat(text);
          // Also try inventory tags embedded in stat events
          parseInventoryTag(text);
          break;

        case 'fact':
          appendLine(text, 'fact');
          break;

        case 'rules_warning':
          appendLine('[Regel] ' + text, 'warning');
          break;

        case 'system':
          appendLine('[System] ' + text, 'system');
          break;

        default:
          // Unknown tags: show as system message if non-empty
          if (text) appendLine(text, 'system');
          break;
      }

      // Always scan all text for inventory tags
      if (data.text) parseInventoryTag(data.text);
      break;
    }

    // ── Input gate ────────────────────────────────────────────
    case 'game.waiting_for_input':
      _waitingForInput = true;
      setInputEnabled(true);
      break;

    // ── Engine lifecycle ──────────────────────────────────────
    case 'techgui.state_changed': {
      const s = data.state || '';
      const running = (s === 'running' || s === 'paused');
      setEngineRunning(running, s === 'paused');
      if (data.character) syncCharacter(data.character);
      break;
    }

    case 'techgui.engine_ready':
      setEngineRunning(true, false);
      if (data.character) syncCharacter(data.character);
      if (data.module) {
        appendLine(`[Engine gestartet: ${data.module}]`, 'system');
      }
      break;

    // ── Structured dice roll (from keeper/dice_roll) ──────────
    case 'keeper.dice_roll':
      handleDiceRollEvent(data);
      break;

    // ── STT passthrough ───────────────────────────────────────
    case 'audio.stt_text':
      if (data.text && _inputEl && !_inputEl.disabled) {
        _inputEl.value = data.text;
        _inputEl.focus();
      }
      break;

    // ── Location ──────────────────────────────────────────────
    case 'adventure.location_changed':
      if (_locationEl && data.location_name) {
        _locationEl.textContent = data.location_name;
      }
      appendLine(`[Ort: ${data.location_name || '?'}]`, 'system');
      break;

    // ── World state / facts ───────────────────────────────────
    case 'archivar.world_state_updated':
      // No direct game-tab display needed; Spielstand tab handles this.
      break;

    // ── Usage (no display in this tab) ───────────────────────
    case 'keeper.usage_update':
      break;

    // ── Response complete ─────────────────────────────────────
    case 'keeper.response_complete':
      // Nothing extra needed; stream_end already finalized text.
      break;

    default:
      break;
  }
}

// ── onEngineReady ────────────────────────────────────────────────

function onEngineReady(discovery) {
  setEngineRunning(true, false);
  appendLine('[Engine bereit]', 'system');
}

// ── onActivate ───────────────────────────────────────────────────

function onActivate() {
  // Scroll to bottom when user switches to game tab
  scrollToBottom();
  // If engine is running and waiting, make sure input is enabled
  if (_engineRunning && _waitingForInput) {
    setInputEnabled(true);
  }
}

// ── Register ─────────────────────────────────────────────────────

ARS.registerTab('game', { init, handleEvent, onEngineReady, onActivate });
