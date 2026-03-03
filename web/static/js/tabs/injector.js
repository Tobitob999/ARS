/**
 * ARS Web GUI — Injector Tab
 *
 * Prompt-section editor playground. Allows the user to inspect, enable/disable,
 * and hand-edit each section that makes up the AI system prompt, then preview
 * the combined result and optionally send a test message.
 *
 * Sections are loaded from the engine on request, or fall back to placeholder
 * definitions when the engine is not running.
 */

// ── Placeholder sections (used when engine is not running) ───────

const PLACEHOLDER_SECTIONS = [
  {
    id: 'persona',
    label: 'Persona',
    content: '# Persona\nDu bist ein erfahrener Keeper...',
    enabled: true,
  },
  {
    id: 'setting',
    label: 'Setting',
    content: '# Setting\n[Setting-Beschreibung hier]',
    enabled: true,
  },
  {
    id: 'keeper_regeln',
    label: 'Keeper-Regeln',
    content: '# Keeper-Regeln\n- Maximale Satzlaenge: 3 Saetze ohne Spielerhook\n- Tags nach jeder Aktion',
    enabled: true,
  },
  {
    id: 'charakter',
    label: 'Charakter',
    content: '# Charakter\n[Charakter-Stats hier]',
    enabled: true,
  },
  {
    id: 'regelwerk',
    label: 'Regelwerk',
    content: '# Regelwerk\n[Regelwerk-Index hier]',
    enabled: true,
  },
  {
    id: 'abenteuer',
    label: 'Abenteuer',
    content: '# Abenteuer\n[Abenteuer-Hintergrund hier]',
    enabled: false,
  },
  {
    id: 'extras',
    label: 'Extras',
    content: '# Extras\n[Zusaetzliche Kontext-Injektion]',
    enabled: false,
  },
];

// ── Module-level state ───────────────────────────────────────────

/**
 * @type {Array<{id:string, label:string, content:string, enabled:boolean}>}
 * The currently loaded section list.
 */
let _sections = [];

// ── Card builder ─────────────────────────────────────────────────

/**
 * Build a collapsible section card element.
 * Returns the root element and mutates the section object in-place as the
 * user edits the card.
 *
 * @param {{ id:string, label:string, content:string, enabled:boolean }} section
 * @returns {HTMLElement}
 */
function buildSectionCard(section) {
  const card = document.createElement('div');
  card.dataset.sectionId = section.id;
  card.style.cssText = 'border:1px solid var(--bg-button);border-radius:var(--radius);margin-bottom:6px;overflow:hidden;';

  // ── Header row ──────────────────────────────────────────────
  const header = document.createElement('div');
  header.style.cssText =
    'display:flex;align-items:center;gap:8px;padding:6px 8px;' +
    'background:var(--bg-panel);cursor:pointer;user-select:none;';

  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.checked = section.enabled;
  checkbox.title = 'Sektion aktivieren';
  checkbox.addEventListener('change', () => { section.enabled = checkbox.checked; });

  const labelEl = document.createElement('span');
  labelEl.className = 'text-accent text-bold';
  labelEl.style.flex = '1';
  labelEl.textContent = section.label;

  const toggle = document.createElement('span');
  toggle.className = 'text-muted text-sm';
  toggle.textContent = '▼';
  toggle.style.cssText = 'width:16px;text-align:center;';

  header.appendChild(checkbox);
  header.appendChild(labelEl);
  header.appendChild(toggle);

  // ── Body (collapsible) ───────────────────────────────────────
  const body = document.createElement('div');
  body.style.cssText = 'padding:6px 8px;background:var(--bg-dark);';

  const ta = document.createElement('textarea');
  ta.value = section.content;
  ta.style.cssText =
    'width:100%;min-height:80px;resize:vertical;font-size:var(--font-sm);' +
    'font-family:var(--font-family);background:var(--bg-input);' +
    'color:var(--fg-primary);border:1px solid var(--bg-button);' +
    'border-radius:var(--radius);padding:4px 6px;';
  ta.addEventListener('input', () => { section.content = ta.value; });

  body.appendChild(ta);

  // ── Collapse toggle ──────────────────────────────────────────
  let collapsed = false;
  header.addEventListener('click', (e) => {
    // Don't collapse when clicking the checkbox itself
    if (e.target === checkbox) return;
    collapsed = !collapsed;
    body.style.display = collapsed ? 'none' : 'block';
    toggle.textContent = collapsed ? '▶' : '▼';
  });

  card.appendChild(header);
  card.appendChild(body);
  return card;
}

// ── Section rendering ────────────────────────────────────────────

/**
 * Re-render all section cards from the current _sections array.
 */
function renderSections() {
  const container = document.getElementById('injector-sections');
  if (!container) return;

  container.innerHTML = '';
  for (const section of _sections) {
    container.appendChild(buildSectionCard(section));
  }
}

/**
 * Load sections from the engine via /api/prompt_sections.
 * Falls back to placeholder sections on error or 404.
 */
async function loadFromEngine() {
  try {
    const resp = await fetch('/api/prompt_sections');
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();

    if (Array.isArray(data.sections) && data.sections.length > 0) {
      _sections = data.sections.map(s => ({
        id:      s.id || s.name || 'unknown',
        label:   s.label || s.name || s.id || 'Sektion',
        content: s.content || s.text || '',
        enabled: s.enabled !== undefined ? Boolean(s.enabled) : true,
      }));
      ARS.showNotification('Sektionen vom Engine geladen (' + _sections.length + ')');
    } else {
      throw new Error('Keine Sektionen in Antwort');
    }
  } catch (err) {
    // Engine not running or endpoint not implemented — use placeholders
    _sections = PLACEHOLDER_SECTIONS.map(s => ({ ...s }));
    ARS.showNotification('Platzhalter-Sektionen geladen (Engine nicht aktiv)', 'info');
  }
  renderSections();
}

// ── All on / off ─────────────────────────────────────────────────

/**
 * Set all section checkboxes to the given state and update section objects.
 * @param {boolean} enabled
 */
function setAllEnabled(enabled) {
  for (const s of _sections) {
    s.enabled = enabled;
  }
  // Update checkboxes in DOM
  const container = document.getElementById('injector-sections');
  if (container) {
    container.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      cb.checked = enabled;
    });
  }
}

// ── Build preview ─────────────────────────────────────────────────

/**
 * Concatenate all enabled section contents and display in the preview panel.
 */
function buildPreview() {
  const enabled = _sections.filter(s => s.enabled);
  const combined = enabled.map(s => s.content.trim()).join('\n\n---\n\n');

  const preview = document.getElementById('injector-preview');
  if (!preview) return;

  preview.textContent = combined || '(Keine Sektionen aktiviert)';
  preview.scrollTop = 0;
}

// ── Tab interface ─────────────────────────────────────────────────

function init(_container) {
  // Seed with placeholder sections so the tab is immediately usable
  _sections = PLACEHOLDER_SECTIONS.map(s => ({ ...s }));
  renderSections();

  // "Vom Engine laden" button
  const btnLoad = document.getElementById('injector-load');
  if (btnLoad) {
    btnLoad.addEventListener('click', () => { loadFromEngine(); });
  }

  // "Alle ein" button
  const btnAllOn = document.getElementById('injector-all-on');
  if (btnAllOn) {
    btnAllOn.addEventListener('click', () => setAllEnabled(true));
  }

  // "Alle aus" button
  const btnAllOff = document.getElementById('injector-all-off');
  if (btnAllOff) {
    btnAllOff.addEventListener('click', () => setAllEnabled(false));
  }

  // "Zusammenbauen" button
  const btnBuild = document.getElementById('injector-build');
  if (btnBuild) {
    btnBuild.addEventListener('click', () => buildPreview());
  }

  // "Senden" button — send test message (placeholder)
  const btnSend = document.getElementById('injector-send-test');
  if (btnSend) {
    btnSend.addEventListener('click', () => {
      const input = document.getElementById('injector-test-input');
      const output = document.getElementById('injector-test-output');
      if (!output) return;

      const msg = input ? input.value.trim() : '';
      const note = '(Test-Senden ist im Web-Modus nicht verfuegbar. ' +
                   'Im Desktop-Modus wird der Prompt direkt an die Engine uebergeben.)';

      const ts = new Date().toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      output.textContent += '[' + ts + '] Eingabe: ' + (msg || '(leer)') + '\n' + note + '\n\n';
      output.scrollTop = output.scrollHeight;

      if (input) input.value = '';
    });
  }
}

function handleEvent(_eventName, _data) {
  // No live events needed for injector playground
}

function onEngineReady(_discovery) {
  // Optionally auto-load sections from engine when it becomes ready
  // We don't auto-load to avoid overwriting user edits
}

function onActivate() {
  // Nothing to refresh on activation
}

// ── Register ─────────────────────────────────────────────────────

ARS.registerTab('injector', { init, handleEvent, onEngineReady, onActivate });
