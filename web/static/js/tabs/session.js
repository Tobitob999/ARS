/**
 * ARS Web GUI — Session Setup Tab
 *
 * Handles session configuration: ruleset/adventure/character selection,
 * difficulty, sliders, extras checkboxes, and engine start/pause/stop.
 */

// ── Module-level state ──────────────────────────────────────────

/** @type {Object} Full discovery data, cached on init */
let _discovery = {};

/** @type {boolean} Whether the engine is running/paused */
let _engineRunning = false;

/** @type {boolean} Whether the engine is paused specifically */
let _enginePaused = false;

// ── DOM helpers ─────────────────────────────────────────────────

/**
 * Populate a <select> element with options from an array.
 * @param {string} id - DOM element id
 * @param {Array<{id:string, name:string}>} items - items to list
 * @param {string} emptyLabel - first "none" option label
 * @param {boolean} required - if true, no empty option is prepended
 */
function populateSelect(id, items, emptyLabel = '-- Keins --', required = false) {
  const el = document.getElementById(id);
  if (!el) return;

  const prev = el.value;
  el.innerHTML = '';

  if (!required) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = emptyLabel;
    el.appendChild(opt);
  }

  for (const item of items) {
    const opt = document.createElement('option');
    opt.value = item.id;
    opt.textContent = item.name || item.id;
    el.appendChild(opt);
  }

  // Restore previous selection if still valid
  if (prev && el.querySelector(`option[value="${CSS.escape(prev)}"]`)) {
    el.value = prev;
  }
}

/** Get the selected value of a radio group by name. */
function getRadio(name) {
  const el = document.querySelector(`input[name="${name}"]:checked`);
  return el ? el.value : null;
}

// ── Filter helpers ──────────────────────────────────────────────

/**
 * Return discovery items that are compatible with the given module id.
 * Items without a `module` field (or with `compatible_rulesets`) are
 * tested against both fields; items with no restriction are included.
 *
 * @param {Array} items
 * @param {string} moduleId
 * @returns {Array}
 */
function filterByModule(items, moduleId) {
  if (!moduleId) return items;
  return items.filter(item => {
    // Explicit module match
    if (item.module === moduleId) return true;
    // compatible_rulesets array (adventures, scenarios)
    if (Array.isArray(item.compatible_rulesets)) {
      return item.compatible_rulesets.includes(moduleId);
    }
    // No restriction field → include everywhere
    if (!item.module && !item.compatible_rulesets) return true;
    return false;
  });
}

// ── Extras checkboxes ───────────────────────────────────────────

const EXTRAS_DEFINITIONS = [
  { id: 'voice',       label: 'Voice I/O',       default: false },
  { id: 'no_barge_in', label: 'Kein Barge-In',   default: false },
  { id: 'debug_tags',  label: 'Tag-Debug',        default: false },
  { id: 'metrics',     label: 'Metriken',         default: true  },
  { id: 'auto_scroll', label: 'Auto-Scroll',      default: true  },
];

/**
 * Build the extras checkbox panel.
 * @param {HTMLElement} container
 */
function buildExtras(container) {
  container.innerHTML = '';
  for (const def of EXTRAS_DEFINITIONS) {
    const label = document.createElement('label');
    label.className = 'flex items-center gap-sm text-sm';
    label.style.marginRight = '12px';

    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.id = 'cfg-extra-' + def.id;
    cb.checked = def.default;

    label.appendChild(cb);
    label.append(def.label);
    container.appendChild(label);
  }
}

/** Collect all extra flags as a plain object. */
function getExtras() {
  const result = {};
  for (const def of EXTRAS_DEFINITIONS) {
    const el = document.getElementById('cfg-extra-' + def.id);
    if (el) result[def.id] = el.checked;
  }
  return result;
}

// ── Engine button state management ──────────────────────────────

function setEngineRunning(running, paused = false) {
  _engineRunning = running;
  _enginePaused = paused;

  const btnStart = document.getElementById('btn-start-engine');
  const btnPause = document.getElementById('btn-pause-engine');
  const btnStop  = document.getElementById('btn-stop-engine');

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
  }
}

// ── Config collection ───────────────────────────────────────────

/** Gather all config values from the form into a plain object. */
function collectConfig() {
  return {
    module:       document.getElementById('cfg-module')?.value       || null,
    adventure:    document.getElementById('cfg-adventure')?.value    || null,
    character:    document.getElementById('cfg-character')?.value    || null,
    party:        document.getElementById('cfg-party')?.value        || null,
    setting:      document.getElementById('cfg-setting')?.value      || null,
    keeper:       document.getElementById('cfg-keeper')?.value       || null,
    preset:       document.getElementById('cfg-preset')?.value       || null,
    difficulty:   getRadio('difficulty')                             || 'normal',
    speech_style: document.getElementById('cfg-speech-style')?.value || 'normal',
    temperature:  parseFloat(document.getElementById('cfg-temperature')?.value ?? 1.0),
    lore_budget:  parseInt(document.getElementById('cfg-lore-budget')?.value  ?? 50, 10),
    extras:       getExtras(),
  };
}

// ── Module change handler ───────────────────────────────────────

function onModuleChange() {
  const moduleId = document.getElementById('cfg-module')?.value || '';

  const adventures  = filterByModule(_discovery.adventures  || [], moduleId);
  const characters  = filterByModule(_discovery.characters  || [], moduleId);
  const parties     = filterByModule(_discovery.parties     || [], moduleId);
  const settings    = filterByModule(_discovery.settings    || [], moduleId);
  const keepers     = filterByModule(_discovery.keepers     || [], moduleId);

  populateSelect('cfg-adventure', adventures,  '-- Keins --');
  populateSelect('cfg-character', characters,  '-- Zufall --');
  populateSelect('cfg-party',     parties,     '-- Keine --');
  populateSelect('cfg-setting',   settings,    '-- Standard --');
  populateSelect('cfg-keeper',    keepers,     '-- Standard --');
}

// ── Dropdown population ─────────────────────────────────────────

function populateDropdowns(discovery) {
  _discovery = discovery || {};

  // Rulesets — always show all, required (no empty option)
  const rulesets = _discovery.rulesets || [];
  populateSelect('cfg-module', rulesets, '', true);

  // Presets — not filtered by module
  populateSelect('cfg-preset', _discovery.presets || [], '-- Manuell --');

  // Now populate the filtered dropdowns for the current module
  onModuleChange();
}

// ── Tab init ────────────────────────────────────────────────────

function init(container) {
  // Build extras checkboxes
  const extrasContainer = document.getElementById('cfg-extras');
  if (extrasContainer) buildExtras(extrasContainer);

  // Slider live value labels
  const tempSlider   = document.getElementById('cfg-temperature');
  const tempVal      = document.getElementById('cfg-temperature-val');
  const loreSlider   = document.getElementById('cfg-lore-budget');
  const loreVal      = document.getElementById('cfg-lore-budget-val');

  if (tempSlider && tempVal) {
    tempSlider.addEventListener('input', () => {
      tempVal.textContent = parseFloat(tempSlider.value).toFixed(1);
    });
  }

  if (loreSlider && loreVal) {
    loreSlider.addEventListener('input', () => {
      const v = parseInt(loreSlider.value, 10);
      loreVal.textContent = v + '%';
      // Notify server live
      ARS.sendWS({ type: 'lore_budget', value: v });
    });
  }

  // Module change → re-filter all dependent dropdowns
  const moduleSelect = document.getElementById('cfg-module');
  if (moduleSelect) {
    moduleSelect.addEventListener('change', onModuleChange);
  }

  // Start button
  const btnStart = document.getElementById('btn-start-engine');
  if (btnStart) {
    btnStart.addEventListener('click', () => {
      const config = collectConfig();
      ARS.sendWS({ type: 'engine_control', action: 'start', config });
    });
  }

  // Pause button
  const btnPause = document.getElementById('btn-pause-engine');
  if (btnPause) {
    btnPause.addEventListener('click', () => {
      const action = _enginePaused ? 'resume' : 'pause';
      ARS.sendWS({ type: 'engine_control', action });
    });
  }

  // Stop button
  const btnStop = document.getElementById('btn-stop-engine');
  if (btnStop) {
    btnStop.addEventListener('click', () => {
      ARS.sendWS({ type: 'engine_control', action: 'stop' });
    });
  }

  // Load initial discovery data if already available
  const existing = ARS.getDiscovery();
  if (existing && Object.keys(existing).length > 0) {
    populateDropdowns(existing);
  }

  // Reflect current engine state
  const state = ARS.getEngineState();
  setEngineRunning(state === 'running' || state === 'paused', state === 'paused');
}

// ── handleEvent ─────────────────────────────────────────────────

function handleEvent(eventName, data) {
  switch (eventName) {
    case 'techgui.state_changed': {
      const s = data.state || '';
      setEngineRunning(s === 'running' || s === 'paused', s === 'paused');
      break;
    }
    case 'techgui.engine_ready': {
      setEngineRunning(true, false);
      break;
    }
    default:
      break;
  }
}

// ── onEngineReady ───────────────────────────────────────────────

function onEngineReady(discovery) {
  populateDropdowns(discovery);
  setEngineRunning(true, false);
}

// ── onActivate ──────────────────────────────────────────────────

function onActivate() {
  // Re-sync discovery in case it was updated while tab was hidden
  const discovery = ARS.getDiscovery();
  if (discovery && Object.keys(discovery).length > 0) {
    populateDropdowns(discovery);
  }
}

// ── Register ────────────────────────────────────────────────────

ARS.registerTab('session', { init, handleEvent, onEngineReady, onActivate });
