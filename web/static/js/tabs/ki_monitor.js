/**
 * ARS Web GUI — KI-Monitor Tab
 *
 * Displays the three phases of KI context construction and response:
 *   Phase 1 — System-Prompt (keeper.prompt_sent)
 *   Phase 2 — Context Injection (keeper.context_injected, rules.section_injected, rules.validation_warning)
 *   Phase 3 — KI Response live stream + token usage
 */

// ── Section Classification ──────────────────────────────────────────────────

/**
 * Map a section name to a CSS class for coloring.
 * @param {string} name
 * @returns {string} CSS class name
 */
function classifySection(name) {
  const n = (name || '').toLowerCase();
  if (n.includes('system') || n.includes('persona') || n.includes('charakter') || n.includes('keeper')) {
    return 'ctx-system';
  }
  if (n.includes('archiv') || n.includes('archivar') || n.includes('lore') || n.includes('wissen')) {
    return 'ctx-archivar';
  }
  if (n.includes('location') || n.includes('ort') || n.includes('szene') || n.includes('umgebung')) {
    return 'ctx-location';
  }
  if (n.includes('history') || n.includes('verlauf') || n.includes('konversation') || n.includes('chat')) {
    return 'ctx-history';
  }
  return '';
}

// ── Text Utilities ──────────────────────────────────────────────────────────

/** Escape HTML special characters for safe textContent insertion via innerHTML. */
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Count characters and tokens (rough estimate: 4 chars per token).
 * @param {string} text
 * @returns {{ chars: number, tokens: number }}
 */
function countStats(text) {
  const chars = (text || '').length;
  return { chars, tokens: Math.round(chars / 4) };
}

/**
 * Render a list of {name, content} sections into a container div.
 * Sections get colored background blocks; plain strings get a default block.
 * @param {HTMLElement} container
 * @param {Array<{name:string,content:string}>} sections
 */
function renderSections(container, sections) {
  container.innerHTML = '';
  let totalText = '';

  sections.forEach(sec => {
    const cssClass = classifySection(sec.name);
    const block = document.createElement('div');
    if (cssClass) block.className = cssClass;
    block.style.marginBottom = '6px';

    // Section header
    if (sec.name) {
      const header = document.createElement('div');
      header.style.cssText = 'font-weight:bold;font-size:var(--font-sm);color:var(--fg-accent);margin-bottom:2px;';
      header.textContent = sec.name;
      block.appendChild(header);
    }

    // Section content
    const body = document.createElement('div');
    body.style.cssText = 'white-space:pre-wrap;word-wrap:break-word;font-size:var(--font-sm);';
    body.textContent = sec.content || '';
    block.appendChild(body);

    container.appendChild(block);
    totalText += (sec.name || '') + '\n' + (sec.content || '') + '\n';
  });

  return totalText;
}

/**
 * Render a plain prompt string into the container.
 * Tries to detect section-like boundaries (e.g. lines starting with "###" or "==").
 * @param {HTMLElement} container
 * @param {string} text
 */
function renderPromptText(container, text) {
  container.innerHTML = '';
  if (!text) return;

  // Split on "### Section" or "=== Section ===" style headers
  const lines = text.split('\n');
  let currentName = '';
  let currentLines = [];

  function flushBlock() {
    if (!currentLines.length) return;
    const cssClass = classifySection(currentName);
    const block = document.createElement('div');
    if (cssClass) block.className = cssClass;
    block.style.marginBottom = '6px';

    if (currentName) {
      const header = document.createElement('div');
      header.style.cssText = 'font-weight:bold;font-size:var(--font-sm);color:var(--fg-accent);margin-bottom:2px;';
      header.textContent = currentName;
      block.appendChild(header);
    }
    const body = document.createElement('div');
    body.style.cssText = 'white-space:pre-wrap;word-wrap:break-word;font-size:var(--font-sm);';
    body.textContent = currentLines.join('\n');
    block.appendChild(body);
    container.appendChild(block);
  }

  for (const line of lines) {
    const sectionMatch = line.match(/^#{2,4}\s+(.+)/) || line.match(/^={3,}\s*(.+?)\s*={3,}/);
    if (sectionMatch) {
      flushBlock();
      currentName = sectionMatch[1].trim();
      currentLines = [];
    } else {
      currentLines.push(line);
    }
  }
  flushBlock();
}

// ── State ──────────────────────────────────────────────────────────────────

// Accumulated content per phase for char/token counting
const _state = {
  phase1Text: '',
  phase2Text: '',
  phase3Text: '',
  streamActive: false,
};

// ── Phase info label updaters ───────────────────────────────────────────────

function updateP1Info(text) {
  const el = document.getElementById('ki-p1-info');
  if (!el) return;
  const { chars, tokens } = countStats(text);
  el.textContent = `${chars.toLocaleString()} Zeichen (~${tokens.toLocaleString()} Tokens)`;
}

function updateP2Info(text) {
  const el = document.getElementById('ki-p2-info');
  if (!el) return;
  const { chars, tokens } = countStats(text);
  el.textContent = `${chars.toLocaleString()} Zeichen (~${tokens.toLocaleString()} Tokens)`;
}

function updateP3Info(promptTokens, outputTokens, totalTokens) {
  const el = document.getElementById('ki-p3-info');
  if (!el) return;
  if (totalTokens !== undefined) {
    el.textContent = `In: ${(promptTokens || 0).toLocaleString()} | Out: ${(outputTokens || 0).toLocaleString()} | Total: ${(totalTokens || 0).toLocaleString()} Tokens`;
  } else {
    const { tokens } = countStats(_state.phase3Text);
    el.textContent = `~${tokens.toLocaleString()} Tokens`;
  }
}

// ── Event Handlers ──────────────────────────────────────────────────────────

function onPromptSent(data) {
  const container = document.getElementById('ki-phase1');
  if (!container) return;

  let totalText = '';

  if (Array.isArray(data.sections) && data.sections.length > 0) {
    totalText = renderSections(container, data.sections);
  } else if (data.prompt) {
    renderPromptText(container, data.prompt);
    totalText = data.prompt;
  } else {
    container.textContent = JSON.stringify(data, null, 2);
    totalText = JSON.stringify(data);
  }

  _state.phase1Text = totalText;
  updateP1Info(totalText);
  container.scrollTop = container.scrollHeight;
}

function onContextInjected(data) {
  const container = document.getElementById('ki-phase2');
  if (!container) return;

  let totalText = '';

  if (Array.isArray(data.sections) && data.sections.length > 0) {
    totalText = renderSections(container, data.sections);
  } else if (data.context) {
    renderPromptText(container, data.context);
    totalText = data.context;
  } else {
    container.textContent = JSON.stringify(data, null, 2);
    totalText = JSON.stringify(data);
  }

  _state.phase2Text = totalText;
  updateP2Info(totalText);
  container.scrollTop = container.scrollHeight;
}

function onSectionInjected(data) {
  // Append a single rules section to phase2
  const container = document.getElementById('ki-phase2');
  if (!container) return;

  const name = data.section_name || data.name || 'Regel-Sektion';
  const content = data.content || data.text || JSON.stringify(data);

  const cssClass = classifySection(name);
  const block = document.createElement('div');
  if (cssClass) block.className = cssClass;
  block.style.marginBottom = '6px';

  const header = document.createElement('div');
  header.style.cssText = 'font-weight:bold;font-size:var(--font-sm);color:var(--fg-accent);margin-bottom:2px;';
  header.textContent = '[Regel] ' + name;
  block.appendChild(header);

  const body = document.createElement('div');
  body.style.cssText = 'white-space:pre-wrap;word-wrap:break-word;font-size:var(--font-sm);';
  body.textContent = content;
  block.appendChild(body);

  container.appendChild(block);

  _state.phase2Text += '\n' + name + '\n' + content;
  updateP2Info(_state.phase2Text);
  container.scrollTop = container.scrollHeight;
}

function onValidationWarning(data) {
  const container = document.getElementById('ki-phase2');
  if (!container) return;

  const msg = data.message || data.warning || data.text || JSON.stringify(data);
  const tag = data.tag || '';

  const block = document.createElement('div');
  block.className = 'warning';
  block.style.cssText = 'padding:4px 8px;border-radius:3px;margin:2px 0;border-left:3px solid var(--yellow);';

  const header = document.createElement('span');
  header.style.cssText = 'font-weight:bold;margin-right:8px;color:var(--yellow);';
  header.textContent = '[WARN]' + (tag ? ` [${tag}]` : '');
  block.appendChild(header);

  const text = document.createElement('span');
  text.textContent = msg;
  block.appendChild(text);

  container.appendChild(block);
  container.scrollTop = container.scrollHeight;
}

function onStreamStart() {
  const container = document.getElementById('ki-phase3');
  if (!container) return;
  container.innerHTML = '';
  _state.phase3Text = '';
  _state.streamActive = true;
  updateP3Info(undefined, undefined, undefined);
}

function onStreamChunk(data) {
  const container = document.getElementById('ki-phase3');
  if (!container) return;

  const chunk = data.chunk || data.text || '';
  if (!chunk) return;

  // Append as text node for safety; detect special spans
  const span = document.createElement('span');

  // Color keeper narrative text distinctly from tags
  if (chunk.startsWith('[') && chunk.includes(':')) {
    span.className = 'probe';
  } else {
    span.className = 'keeper';
  }
  span.textContent = chunk;
  container.appendChild(span);

  _state.phase3Text += chunk;
  updateP3Info(undefined, undefined, undefined);
  container.scrollTop = container.scrollHeight;
}

function onResponseComplete(data) {
  const container = document.getElementById('ki-phase3');
  if (!container) return;

  _state.streamActive = false;
  const response = data.response || data.text || '';

  // If we received the full response (not streamed chunk-by-chunk), render it now
  if (response && !_state.phase3Text) {
    container.innerHTML = '';
    const block = document.createElement('span');
    block.className = 'keeper';
    block.style.whiteSpace = 'pre-wrap';
    block.textContent = response;
    container.appendChild(block);
    _state.phase3Text = response;
  }

  // Add separator line to mark completion
  const sep = document.createElement('div');
  sep.style.cssText = 'border-top:1px solid var(--bg-button);margin:6px 0;';
  container.appendChild(sep);

  updateP3Info(undefined, undefined, undefined);
  container.scrollTop = container.scrollHeight;
}

function onUsageUpdate(data) {
  // Update phase3 info with real token counts from the API
  const prompt  = (data.session && data.session.prompt_tokens)     || data.prompt_tokens     || 0;
  const output  = (data.session && data.session.candidates_tokens) || data.candidates_tokens || 0;
  const total   = (data.session && data.session.total_tokens)      || data.total_tokens      || 0;
  updateP3Info(prompt, output, total);
}

// ── Tab Module ──────────────────────────────────────────────────────────────

const kiMonitorTab = {
  init(container) {
    // Container already has DOM from HTML — nothing to build dynamically.
    // Clear all three phases on init.
    const p1 = document.getElementById('ki-phase1');
    const p2 = document.getElementById('ki-phase2');
    const p3 = document.getElementById('ki-phase3');
    if (p1) { p1.innerHTML = ''; p1.classList.add('text-output'); }
    if (p2) { p2.innerHTML = ''; p2.classList.add('text-output'); }
    if (p3) { p3.innerHTML = ''; p3.classList.add('text-output'); }
  },

  handleEvent(eventName, data) {
    switch (eventName) {
      case 'keeper.prompt_sent':
        onPromptSent(data);
        break;

      case 'keeper.context_injected':
        onContextInjected(data);
        break;

      case 'keeper.response_complete':
        onResponseComplete(data);
        break;

      case 'keeper.usage_update':
        onUsageUpdate(data);
        break;

      case 'rules.section_injected':
        onSectionInjected(data);
        break;

      case 'rules.validation_warning':
        onValidationWarning(data);
        break;

      case 'game.output':
        if (data.tag === 'stream_start') {
          onStreamStart();
        } else if (data.tag === 'stream_chunk') {
          onStreamChunk(data);
        }
        break;

      default:
        break;
    }
  },

  onEngineReady(discovery) {
    // Clear phases when a new engine session starts
    const p1 = document.getElementById('ki-phase1');
    const p2 = document.getElementById('ki-phase2');
    const p3 = document.getElementById('ki-phase3');
    if (p1) p1.innerHTML = '';
    if (p2) p2.innerHTML = '';
    if (p3) p3.innerHTML = '';
    _state.phase1Text = '';
    _state.phase2Text = '';
    _state.phase3Text = '';
    _state.streamActive = false;
    updateP1Info('');
    updateP2Info('');
    updateP3Info(0, 0, 0);
  },

  onActivate() {
    // Scroll all panels to bottom when tab becomes visible
    ['ki-phase1', 'ki-phase2', 'ki-phase3'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.scrollTop = el.scrollHeight;
    });
  },
};

ARS.registerTab('ki-monitor', kiMonitorTab);
