/**
 * ARS Web GUI — Responder Tab
 *
 * Response-parsing playground. Paste a raw KI response and let the parser
 * highlight recognised ARS tags with colour-coded output. Also shows a
 * live feed of events as they arrive from the engine.
 */

// ── ARS tag definitions ──────────────────────────────────────────

/**
 * Tag descriptor: pattern to match one tag family, display label, and
 * the CSS class (from theme.css text-output classes) to apply.
 *
 * Patterns use named group `value` for the tag payload.
 *
 * @type {Array<{id:string, label:string, pattern:RegExp, cssClass:string}>}
 */
const TAG_DEFS = [
  {
    id: 'probe',
    label: 'Probe',
    pattern: /\[PROBE:\s*(?<value>[^\]]+)\]/g,
    cssClass: 'probe',
  },
  {
    id: 'hp_verlust',
    label: 'HP-Verlust',
    pattern: /\[HP_VERLUST:\s*(?<value>[^\]]+)\]/g,
    cssClass: 'stat',
  },
  {
    id: 'hp_heilung',
    label: 'HP-Heilung',
    pattern: /\[HP_HEILUNG:\s*(?<value>[^\]]+)\]/g,
    cssClass: 'stat',
  },
  {
    id: 'stabilitaet',
    label: 'Stabilitaet',
    pattern: /\[STABILITAET_VERLUST:\s*(?<value>[^\]]+)\]/g,
    cssClass: 'stat',
  },
  {
    id: 'sanity_check',
    label: 'Sanity Check',
    pattern: /\[SANITY_CHECK:\s*(?<value>[^\]]+)\]/g,
    cssClass: 'stat',
  },
  {
    id: 'san_loss',
    label: 'SAN-Verlust',
    pattern: /\[SAN_LOSS:\s*(?<value>[^\]]+)\]/g,
    cssClass: 'stat',
  },
  {
    id: 'inventar_plus',
    label: 'Inventar+',
    pattern: /\[INVENTAR:\s*\+(?<value>[^\]]+)\]/g,
    cssClass: 'text-green',
  },
  {
    id: 'inventar_minus',
    label: 'Inventar-',
    pattern: /\[INVENTAR:\s*-(?<value>[^\]]+)\]/g,
    cssClass: 'text-red',
  },
  {
    id: 'inventar_neutral',
    label: 'Inventar',
    // Catch any INVENTAR not preceded by +/-
    pattern: /\[INVENTAR:\s*(?![+-])(?<value>[^\]]+)\]/g,
    cssClass: 'fact',
  },
  {
    id: 'fakt',
    label: 'Fakt',
    pattern: /\[FAKT:\s*(?<value>[^\]]+)\]/g,
    cssClass: 'fact',
  },
  {
    id: 'stimme',
    label: 'Stimme',
    pattern: /\[STIMME:\s*(?<value>[^\]]+)\]/g,
    cssClass: 'archivar',
  },
  {
    id: 'zeit_vergeht',
    label: 'Zeit',
    pattern: /\[ZEIT_VERGEHT:\s*(?<value>[^\]]+)\]/g,
    cssClass: 'text-muted',
  },
  {
    id: 'tageszeit',
    label: 'Tageszeit',
    pattern: /\[TAGESZEIT:\s*(?<value>[^\]]+)\]/g,
    cssClass: 'text-muted',
  },
  {
    id: 'wetter',
    label: 'Wetter',
    pattern: /\[WETTER:\s*(?<value>[^\]]+)\]/g,
    cssClass: 'text-muted',
  },
  {
    id: 'angriff',
    label: 'Angriff',
    pattern: /\[ANGRIFF:\s*(?<value>[^\]]+)\]/g,
    cssClass: 'combat',
  },
  {
    id: 'rettungswurf',
    label: 'Rettungswurf',
    pattern: /\[RETTUNGSWURF:\s*(?<value>[^\]]+)\]/g,
    cssClass: 'combat',
  },
];

// ── Sample response ───────────────────────────────────────────────

const SAMPLE_RESPONSE =
  'Die alten Dielen knarren unter Euren Schritten, waehrend Ihr den Korridor entlanggeht. ' +
  'Eine schwache Gasflamme flackert in einer Wandhalterung und wirft zitternde Schatten an die verrotteten Tapeten. ' +
  'Ploetzlich hoert Ihr ein schabendes Geraeusch hinter der verriegelten Tuere am Ende des Ganges — ' +
  'etwas bewegt sich dort drinnen. Was tut Ihr? ' +
  '[PROBE: Lauschen 45] ' +
  '[FAKT: Korridor_Gasflamme=true] ' +
  '[ZEIT_VERGEHT: 2 Minuten] ' +
  '[TAGESZEIT: Nacht] ' +
  '[WETTER: Regen]';

// ── Parse logic ───────────────────────────────────────────────────

/**
 * Parse an ARS KI response string and return structured results.
 *
 * @param {string} text  Raw KI response.
 * @returns {{ cleanText:string, tags:Array<{id:string, label:string, value:string, cssClass:string}> }}
 */
function parseResponse(text) {
  const tags = [];

  // Collect all tag matches across all definitions
  for (const def of TAG_DEFS) {
    // Reset lastIndex for reuse of the global regex
    def.pattern.lastIndex = 0;
    let match;
    while ((match = def.pattern.exec(text)) !== null) {
      tags.push({
        id:       def.id,
        label:    def.label,
        value:    (match.groups && match.groups.value) ? match.groups.value.trim() : match[0],
        cssClass: def.cssClass,
      });
    }
  }

  // Strip all bracketed tags to produce the clean narrative text
  const cleanText = text.replace(/\[[^\]]+\]/g, '').replace(/\s{2,}/g, ' ').trim();

  return { cleanText, tags };
}

// ── Result renderer ───────────────────────────────────────────────

/**
 * Render parse results into the #responder-results panel.
 * @param {string} rawText
 */
function renderResults(rawText) {
  const panel = document.getElementById('responder-results');
  if (!panel) return;

  panel.innerHTML = '';

  if (!rawText.trim()) {
    panel.textContent = '(Kein Text zum Analysieren)';
    return;
  }

  const { cleanText, tags } = parseResponse(rawText);

  // ── Clean text section ───────────────────────────────────────
  const cleanHeader = document.createElement('div');
  cleanHeader.className = 'text-accent text-bold';
  cleanHeader.style.marginBottom = '4px';
  cleanHeader.textContent = 'Bereinigter Text:';
  panel.appendChild(cleanHeader);

  const cleanEl = document.createElement('div');
  cleanEl.className = 'keeper';
  cleanEl.style.cssText = 'white-space:pre-wrap;margin-bottom:10px;border-left:3px solid var(--stream-keeper);padding-left:6px;';
  cleanEl.textContent = cleanText || '(leer)';
  panel.appendChild(cleanEl);

  // ── Tag summary ──────────────────────────────────────────────
  const tagHeader = document.createElement('div');
  tagHeader.className = 'text-accent text-bold';
  tagHeader.style.marginBottom = '4px';
  tagHeader.textContent = 'Gefundene Tags (' + tags.length + '):';
  panel.appendChild(tagHeader);

  if (tags.length === 0) {
    const none = document.createElement('div');
    none.className = 'text-muted';
    none.textContent = '(keine Tags gefunden)';
    panel.appendChild(none);
    return;
  }

  // Count by label
  const counts = {};
  for (const t of tags) {
    counts[t.label] = (counts[t.label] || 0) + 1;
  }

  // Summary line
  const summaryLine = document.createElement('div');
  summaryLine.className = 'text-muted text-sm';
  summaryLine.style.marginBottom = '6px';
  summaryLine.textContent =
    Object.entries(counts)
      .map(([label, n]) => label + (n > 1 ? ' x' + n : ''))
      .join('  |  ');
  panel.appendChild(summaryLine);

  // Individual tag entries
  for (const t of tags) {
    const row = document.createElement('div');
    row.style.cssText = 'margin-bottom:3px;display:flex;gap:8px;align-items:baseline;';

    const badge = document.createElement('span');
    badge.className = 'text-sm text-muted';
    badge.style.cssText = 'min-width:120px;flex-shrink:0;';
    badge.textContent = '[' + t.label + ']';

    const value = document.createElement('span');
    value.className = t.cssClass;
    value.textContent = t.value;

    row.appendChild(badge);
    row.appendChild(value);
    panel.appendChild(row);
  }
}

// ── Live feed ─────────────────────────────────────────────────────

/**
 * Append a formatted entry to the live feed panel.
 * @param {string} cssClass  CSS class for colour.
 * @param {string} prefix    Short label (e.g. "Keeper", "Probe").
 * @param {string} text      Content text.
 */
function appendLive(cssClass, prefix, text) {
  const feed = document.getElementById('responder-live');
  if (!feed) return;

  const ts = new Date().toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  const line = document.createElement('div');
  line.style.marginBottom = '4px';

  const stamp = document.createElement('span');
  stamp.className = 'timestamp';
  stamp.textContent = '[' + ts + '] ';

  const labelEl = document.createElement('span');
  labelEl.className = 'text-muted text-sm';
  labelEl.textContent = prefix + ': ';

  const body = document.createElement('span');
  body.className = cssClass;
  body.textContent = text;

  line.appendChild(stamp);
  line.appendChild(labelEl);
  line.appendChild(body);
  feed.appendChild(line);

  feed.scrollTop = feed.scrollHeight;
}

// ── Tab interface ─────────────────────────────────────────────────

function init(_container) {
  // "Analysieren" button
  const btnAnalyze = document.getElementById('responder-analyze');
  if (btnAnalyze) {
    btnAnalyze.addEventListener('click', () => {
      const ta = document.getElementById('responder-input');
      renderResults(ta ? ta.value : '');
    });
  }

  // "Beispiel laden" button
  const btnExample = document.getElementById('responder-example');
  if (btnExample) {
    btnExample.addEventListener('click', () => {
      const ta = document.getElementById('responder-input');
      if (ta) {
        ta.value = SAMPLE_RESPONSE;
        // Auto-analyze after loading
        renderResults(ta.value);
      }
    });
  }

  // "Leeren" button
  const btnClear = document.getElementById('responder-clear');
  if (btnClear) {
    btnClear.addEventListener('click', () => {
      const ta = document.getElementById('responder-input');
      if (ta) ta.value = '';
      const results = document.getElementById('responder-results');
      if (results) results.innerHTML = '';
      const feed = document.getElementById('responder-live');
      if (feed) feed.innerHTML = '';
    });
  }

  // Allow Ctrl+Enter in the textarea to trigger analysis
  const ta = document.getElementById('responder-input');
  if (ta) {
    ta.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.key === 'Enter') {
        renderResults(ta.value);
      }
    });
  }
}

function handleEvent(eventName, data) {
  switch (eventName) {

    // Full KI response — append to live feed
    case 'keeper.response_complete': {
      const text = data.response || data.text || '';
      if (text) appendLive('keeper', 'Keeper', text.substring(0, 200) + (text.length > 200 ? '...' : ''));
      break;
    }

    // Structured tag events from the engine
    case 'game.output': {
      const tag = data.tag || '';
      switch (tag) {
        case 'probe': {
          const detail = data.skill ? data.skill + ' / Ziel ' + (data.target || '?') : (data.text || '');
          appendLive('probe', 'Probe', detail);
          break;
        }
        case 'dice': {
          const diceText = data.result || data.text || JSON.stringify(data);
          appendLive('dice', 'Wurfel', diceText);
          break;
        }
        case 'stat': {
          const statText = (data.stat || '') + ': ' + (data.old_value ?? '?') + ' -> ' + (data.new_value ?? '?');
          appendLive('stat', 'Stat', statText);
          break;
        }
        case 'fact': {
          appendLive('fact', 'Fakt', data.key + '=' + data.value);
          break;
        }
        default:
          break;
      }
      break;
    }

    // Warning from the validator
    case 'keeper.response_warning': {
      appendLive('warning', 'Warning', data.message || data.warning || '');
      break;
    }

    default:
      break;
  }
}

function onEngineReady(_discovery) {
  appendLive('system', 'System', 'Engine gestartet — Live-Feed aktiv');
}

function onActivate() {
  // Nothing needed on activation
}

// ── Register ─────────────────────────────────────────────────────

ARS.registerTab('responder', { init, handleEvent, onEngineReady, onActivate });
