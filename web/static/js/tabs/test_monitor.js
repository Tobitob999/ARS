/**
 * ARS Web GUI — Test Monitor Tab
 *
 * Runs automated virtual-player test series against the engine via a REST
 * API. Displays active runs with live progress and a log of completed runs
 * with pass/fail scores.
 *
 * API endpoints used:
 *   POST /api/test/start  { module, case, turns, runs }
 *   POST /api/test/stop
 *   GET  /api/test/status  -> { active: [...], done: [...] }
 *
 * All endpoints may return 404 if the server-side test runner is not yet
 * implemented. In that case a user-visible notification is shown and the
 * tab degrades gracefully.
 */

// ── Module-level state ───────────────────────────────────────────

/** @type {number|null} setInterval handle for the status poller */
let _pollTimer = null;

/** @type {boolean} True while at least one test run is active */
let _testsRunning = false;

/** @type {number} Total completed run count (for display badge) */
let _doneCount = 0;

/** @type {number|null} setInterval handle for the live-view poller */
let _liveViewTimer = null;

/** @type {string|null} filename of the currently open live-view */
let _liveViewFile = null;

// ── API helpers ───────────────────────────────────────────────────

/**
 * POST to a test API endpoint.
 * Handles 404 gracefully by showing a notification rather than throwing.
 *
 * @param {string} path    e.g. '/api/test/start'
 * @param {object} [body]  JSON body (omit for empty POST).
 * @returns {Promise<object|null>}  Parsed JSON response, or null on error/404.
 */
async function postTestApi(path, body) {
  try {
    const resp = await fetch(path, {
      method: 'POST',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });

    if (resp.status === 404) {
      ARS.showNotification('Test-API nicht verfuegbar (404: ' + path + ')', 'error');
      return null;
    }
    if (!resp.ok) {
      ARS.showNotification('Test-API Fehler ' + resp.status + ': ' + path, 'error');
      return null;
    }
    return await resp.json();
  } catch (err) {
    ARS.showNotification('Test-API nicht erreichbar: ' + err.message, 'error');
    return null;
  }
}

/**
 * GET from a test API endpoint.
 * @param {string} path
 * @returns {Promise<object|null>}
 */
async function getTestApi(path) {
  try {
    const resp = await fetch(path);
    if (resp.status === 404) {
      // Silent: 404 just means polling while server has no test API yet.
      stopPolling();
      return null;
    }
    if (!resp.ok) return null;
    return await resp.json();
  } catch {
    return null;
  }
}

// ── Status polling ─────────────────────────────────────────────────

/** Start polling /api/test/status every 2 seconds. */
function startPolling() {
  if (_pollTimer !== null) return;
  _pollTimer = setInterval(() => { fetchStatus(); }, 2000);
}

/** Stop polling. */
function stopPolling() {
  if (_pollTimer !== null) {
    clearInterval(_pollTimer);
    _pollTimer = null;
  }
}

/** Fetch current status and update both tables. */
async function fetchStatus() {
  const data = await getTestApi('/api/test/status');
  if (!data) return;

  const allRuns = data.active || [];
  const activeRuns = allRuns.filter(r => !r.stale);
  renderActiveTable(activeRuns);

  // Stop polling automatically if no active runs remain
  const hasActive = activeRuns.length > 0;
  if (!hasActive && _testsRunning) {
    _testsRunning = false;
    stopPolling();
    setRunningState(false);
    ARS.showNotification('Alle Test-Runs abgeschlossen.');
  }
}

// ── Button state ──────────────────────────────────────────────────

/**
 * Update Start/Stop button enabled state.
 * @param {boolean} running
 */
function setRunningState(running) {
  _testsRunning = running;
  const btnStart   = document.getElementById('tm-start');
  const btnStopAll = document.getElementById('tm-stop-all');
  if (btnStart)   btnStart.disabled   = running;
  if (btnStopAll) btnStopAll.disabled = !running;
}

// ── Table renderers ───────────────────────────────────────────────

/**
 * Render active-runs rows.
 *
 * Expected item shape:
 *   { run_id, module, case, turn, total_turns, status, avg_latency_ms }
 *
 * @param {Array<object>} items
 */
function renderActiveTable(items) {
  const tbody = document.getElementById('tm-active');
  if (!tbody) return;
  tbody.innerHTML = '';

  if (items.length === 0) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 6;
    td.className = 'text-muted';
    td.style.textAlign = 'center';
    td.textContent = 'Keine aktiven Runs';
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  for (const item of items) {
    const tr = document.createElement('tr');

    const label = item.file || item.run_id || '-';
    const filename = String(label).replace(/\.json$/, '');
    const tdId     = _td(filename);
    const tdModule = _td(item.module || '-');
    const tdCase   = _td(item.case_name || String(item.case_id ?? item.case ?? '-'));

    const turn       = item.current_turn ?? item.turn ?? 0;
    const totalTurns = item.total_turns ?? item.turns ?? '?';
    const tdTurn = _td(turn + '/' + totalTurns);

    const status = item.status || 'running';
    const tdStatus = _td(status);
    tdStatus.className = status === 'running' ? 'text-green'
                       : status === 'error'   ? 'text-red'
                       : 'text-muted';

    const latMs = item.avg_latency_ms ?? item.latency ?? null;
    const tdLat = _td(latMs !== null ? Math.round(latMs) + ' ms' : '-');
    tdLat.style.textAlign = 'right';

    // Click to open live view
    tr.style.cursor = 'pointer';
    tr.title = 'Klicken fuer Live-View';
    tr.addEventListener('click', () => openLiveView(filename, item));

    tr.appendChild(tdId);
    tr.appendChild(tdModule);
    tr.appendChild(tdCase);
    tr.appendChild(tdTurn);
    tr.appendChild(tdStatus);
    tr.appendChild(tdLat);
    tbody.appendChild(tr);
  }
}

/**
 * Render done-runs rows and update the count badge.
 *
 * Expected item shape:
 *   { run_id, score, passed, avg_latency_ms, error_count }
 *
 * @param {Array<object>} items
 */
function renderDoneTable(items) {
  const tbody = document.getElementById('tm-done');
  if (!tbody) return;

  // Only re-render when the count changed (avoids thrashing)
  if (items.length === _doneCount && _doneCount > 0) return;
  _doneCount = items.length;

  // Update badge
  const countEl = document.getElementById('tm-done-count');
  if (countEl) countEl.textContent = _doneCount + ' Run' + (_doneCount !== 1 ? 's' : '');

  tbody.innerHTML = '';

  if (items.length === 0) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 5;
    td.className = 'text-muted';
    td.style.textAlign = 'center';
    td.textContent = 'Noch keine abgeschlossenen Runs';
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  // Show newest first
  const sorted = [...items].reverse();

  for (const item of sorted) {
    const tr = document.createElement('tr');

    const tdId = _td(String(item.run_id ?? '-'));

    const score = item.score ?? null;
    const tdScore = _td(score !== null ? score.toFixed(2) : '-');

    const passed = item.passed ?? (score !== null ? score >= 0.5 : null);
    const tdPass = _td(passed === null ? '-' : passed ? 'PASS' : 'FAIL');
    tdPass.className = passed === null ? 'text-muted'
                     : passed          ? 'text-green text-bold'
                     :                   'text-red text-bold';

    const latMs = item.avg_latency_ms ?? item.latency ?? null;
    const tdLat = _td(latMs !== null ? latMs.toFixed(0) + ' ms' : '-');
    tdLat.style.textAlign = 'right';

    const errors = item.error_count ?? item.errors ?? 0;
    const tdErr = _td(String(errors));
    tdErr.className = errors > 0 ? 'text-red' : 'text-muted';

    tr.appendChild(tdId);
    tr.appendChild(tdScore);
    tr.appendChild(tdPass);
    tr.appendChild(tdLat);
    tr.appendChild(tdErr);
    tbody.appendChild(tr);
  }
}

// ── DOM utility ───────────────────────────────────────────────────

/**
 * Create a <td> with text content.
 * @param {string} text
 * @returns {HTMLTableCellElement}
 */
function _td(text) {
  const td = document.createElement('td');
  td.textContent = text;
  return td;
}

// ── Live-View Modal ───────────────────────────────────────────

/**
 * Open a live-view modal for a specific test run.
 * @param {string} filename  Progress file name (without .json)
 * @param {object} item      Row data from the active table
 */
function openLiveView(filename, item) {
  // Close any existing modal first
  closeLiveView();

  _liveViewFile = filename;

  // Build modal DOM
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.id = 'live-view-overlay';
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closeLiveView();
  });

  const modal = document.createElement('div');
  modal.className = 'modal-live';

  // Header
  const header = document.createElement('div');
  header.className = 'modal-live-header';

  const titleDiv = document.createElement('div');
  const titleSpan = document.createElement('span');
  titleSpan.className = 'modal-title';
  titleSpan.textContent = 'Live-View: ' + filename;
  titleDiv.appendChild(titleSpan);

  const subtitle = document.createElement('span');
  subtitle.className = 'modal-subtitle';
  subtitle.id = 'lv-subtitle';
  const mod = item.module || '?';
  const cs = item.case_name || item.case_id || '?';
  const turn = item.current_turn ?? 0;
  const total = item.total_turns ?? '?';
  subtitle.textContent = mod + ' / ' + cs + ' — Turn ' + turn + '/' + total;
  titleDiv.appendChild(subtitle);

  const closeBtn = document.createElement('button');
  closeBtn.className = 'modal-close';
  closeBtn.innerHTML = '&#x2715;';
  closeBtn.title = 'Schliessen (Esc)';
  closeBtn.addEventListener('click', closeLiveView);

  header.appendChild(titleDiv);
  header.appendChild(closeBtn);

  // Body: two panels
  const body = document.createElement('div');
  body.className = 'modal-live-body';

  const chatPanel = document.createElement('div');
  chatPanel.className = 'live-chat';
  chatPanel.id = 'lv-chat';
  const chatTitle = document.createElement('div');
  chatTitle.className = 'live-panel-title';
  chatTitle.textContent = 'Chat-Verlauf';
  chatPanel.appendChild(chatTitle);

  const techPanel = document.createElement('div');
  techPanel.className = 'live-techlog';
  techPanel.id = 'lv-techlog';
  const techTitle = document.createElement('div');
  techTitle.className = 'live-panel-title';
  techTitle.textContent = 'Technisches Log';
  techPanel.appendChild(techTitle);

  body.appendChild(chatPanel);
  body.appendChild(techPanel);

  modal.appendChild(header);
  modal.appendChild(body);
  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  // Keyboard handler for Esc
  document.addEventListener('keydown', _onLiveViewKey);

  // Initial fetch + start polling
  fetchLiveView();
  _liveViewTimer = setInterval(fetchLiveView, 3000);
}

/**
 * Close the live-view modal and stop its polling.
 */
function closeLiveView() {
  if (_liveViewTimer !== null) {
    clearInterval(_liveViewTimer);
    _liveViewTimer = null;
  }
  _liveViewFile = null;

  const overlay = document.getElementById('live-view-overlay');
  if (overlay) overlay.remove();

  document.removeEventListener('keydown', _onLiveViewKey);
}

/**
 * Esc key handler for the live-view modal.
 * @param {KeyboardEvent} e
 */
function _onLiveViewKey(e) {
  if (e.key === 'Escape') closeLiveView();
}

/**
 * Fetch live data for the open modal and render both panels.
 */
async function fetchLiveView() {
  if (!_liveViewFile) return;

  const data = await getTestApi('/api/test/run/' + encodeURIComponent(_liveViewFile));
  if (!data || data.ok === false) return;

  // Update subtitle
  const subtitle = document.getElementById('lv-subtitle');
  if (subtitle) {
    const mod = data.module || '?';
    const cs = data.case_name || data.case_id || '?';
    const turn = data.current_turn ?? data.total_turns ?? '?';
    const total = data.total_turns ?? '?';
    const status = data.status || '?';
    subtitle.textContent = mod + ' / ' + cs + ' — Turn ' + turn + '/' + total + ' [' + status + ']';
  }

  const turns = data.turns || [];
  renderChat(turns);
  renderTechlog(turns);

  // Stop polling if test is no longer running
  const status = data.status || '';
  if (status !== 'running' && _liveViewTimer !== null) {
    clearInterval(_liveViewTimer);
    _liveViewTimer = null;
  }
}

/**
 * Render chat messages in the left panel.
 * @param {Array<object>} turns
 */
function renderChat(turns) {
  const panel = document.getElementById('lv-chat');
  if (!panel) return;

  // Preserve the title element
  const titleEl = panel.querySelector('.live-panel-title');

  // Check if we can do incremental update
  const existingCount = panel.querySelectorAll('.chat-turn-group').length;
  if (existingCount === turns.length) return;  // No new turns

  // Clear and rebuild (keep title)
  panel.innerHTML = '';
  if (titleEl) panel.appendChild(titleEl);

  if (turns.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'text-muted';
    empty.style.textAlign = 'center';
    empty.style.padding = '20px';
    empty.textContent = 'Warte auf ersten Turn...';
    panel.appendChild(empty);
    return;
  }

  for (const t of turns) {
    const group = document.createElement('div');
    group.className = 'chat-turn-group';

    // Player message
    if (t.player_input) {
      const msg = document.createElement('div');
      msg.className = 'chat-msg player';
      const label = document.createElement('div');
      label.className = 'chat-label';
      label.textContent = 'Spieler (Turn ' + t.turn + ')';
      const text = document.createElement('div');
      text.textContent = t.player_input;
      msg.appendChild(label);
      msg.appendChild(text);
      group.appendChild(msg);
    }

    // Keeper response
    if (t.keeper_response) {
      const msg = document.createElement('div');
      msg.className = 'chat-msg keeper';
      const label = document.createElement('div');
      label.className = 'chat-label';
      label.textContent = 'Keeper (Turn ' + t.turn + ')';
      const text = document.createElement('div');
      // Strip tags for display, show clean text
      text.textContent = t.keeper_response.replace(/\[[^\]]+\]/g, '').trim();
      msg.appendChild(label);
      msg.appendChild(text);
      group.appendChild(msg);
    }

    // Error
    if (t.error) {
      const msg = document.createElement('div');
      msg.className = 'chat-msg error';
      msg.textContent = 'FEHLER: ' + t.error;
      group.appendChild(msg);
    }

    panel.appendChild(group);
  }

  // Auto-scroll to bottom
  panel.scrollTop = panel.scrollHeight;
}

/**
 * Render technical log entries in the right panel.
 * @param {Array<object>} turns
 */
function renderTechlog(turns) {
  const panel = document.getElementById('lv-techlog');
  if (!panel) return;

  const titleEl = panel.querySelector('.live-panel-title');
  const existingCount = panel.querySelectorAll('.techlog-entry').length;
  if (existingCount === turns.length) return;

  panel.innerHTML = '';
  if (titleEl) panel.appendChild(titleEl);

  if (turns.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'text-muted';
    empty.style.textAlign = 'center';
    empty.style.padding = '20px';
    empty.textContent = 'Warte auf ersten Turn...';
    panel.appendChild(empty);
    return;
  }

  for (const t of turns) {
    const entry = document.createElement('div');
    entry.className = 'techlog-entry';

    // Turn number + latency
    let html = '<span class="tl-turn">Turn ' + t.turn + '</span>';
    html += ' <span class="tl-latency">' + Math.round(t.latency_ms || 0) + 'ms</span>';

    // Tags
    const tags = t.tags_found || [];
    if (tags.length > 0) {
      html += ' <span class="tl-tags">[' + tags.join(', ') + ']</span>';
    }

    // Probes + Combat
    const details = [];
    if (t.probes > 0) details.push('Probes:' + t.probes);
    if (t.combat_tags > 0) details.push('Combat:' + t.combat_tags);
    if (t.stat_changes > 0) details.push('Stats:' + t.stat_changes);
    if (details.length > 0) {
      html += ' <span class="tl-latency">(' + details.join(', ') + ')</span>';
    }

    // Warnings
    const warnings = t.rules_warnings || [];
    for (const w of warnings) {
      html += '<br><span class="tl-warnings">WARN: ' + _escapeHtml(w) + '</span>';
    }

    // Error
    if (t.error) {
      html += '<br><span class="tl-error">ERROR: ' + _escapeHtml(t.error) + '</span>';
    }

    entry.innerHTML = html;
    panel.appendChild(entry);
  }

  panel.scrollTop = panel.scrollHeight;
}

/**
 * Escape HTML special characters.
 * @param {string} s
 * @returns {string}
 */
function _escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

// ── Tab interface ─────────────────────────────────────────────────

function init(_container) {
  // "Starten" button
  const btnStart = document.getElementById('tm-start');
  if (btnStart) {
    btnStart.addEventListener('click', async () => {
      const module = document.getElementById('tm-module')?.value || 'cthulhu_7e';
      const testCase = document.getElementById('tm-case')?.value  || '1';
      const turns  = parseInt(document.getElementById('tm-turns')?.value ?? '5', 10);
      const runs   = parseInt(document.getElementById('tm-runs')?.value  ?? '3', 10);

      const result = await postTestApi('/api/test/start', { module, case: testCase, turns, runs });
      if (result) {
        setRunningState(true);
        _doneCount = 0;
        ARS.showNotification('Test gestartet: ' + runs + 'x ' + module + ' / Case ' + testCase);
        startPolling();
        // Immediate status fetch so the table fills before next poll
        fetchStatus();
      }
    });
  }

  // "Alle Stoppen" button
  const btnStop = document.getElementById('tm-stop-all');
  if (btnStop) {
    btnStop.addEventListener('click', async () => {
      const result = await postTestApi('/api/test/stop');
      if (result !== null) {
        setRunningState(false);
        stopPolling();
        ARS.showNotification('Alle Tests gestoppt.');
        fetchStatus();
      }
    });
  }

  // Initial render of empty tables
  renderActiveTable([]);
  renderDoneTable([]);
}

function handleEvent(eventName, data) {
  // If the test runner emits WebSocket events, handle them here
  if (eventName === 'test.run_complete' || eventName === 'test.turn_done') {
    // Trigger a status refresh without waiting for the next poll cycle
    fetchStatus();
  }
}

function onEngineReady(_discovery) {
  // Nothing needed; test runs are independent of the game engine session
}

async function onActivate() {
  // Refresh and start polling if active runs found
  const data = await getTestApi('/api/test/status');
  if (!data) return;
  renderActiveTable(data.active || []);
  const hasActive = (data.active || []).filter(r => !r.stale).length > 0;
  if (hasActive) {
    _testsRunning = true;
    setRunningState(true);
    startPolling();
  }
}

// ── Register ─────────────────────────────────────────────────────

ARS.registerTab('test-monitor', { init, handleEvent, onEngineReady, onActivate });
