/**
 * ARS Web GUI — Conversion Monitor Tab
 *
 * Shows the status of the lore conversion pipeline. The actual PDF scanner
 * and file converter run as desktop-side processes; this tab provides a
 * read-only view of the lore directory inventory fetched from /api/discovery.
 *
 * "Workload" = raw source directories (PDFs yet to be processed, estimated
 * from discovery metadata if available).
 * "Fertiggestellt" = per-system lore directories with their file counts.
 */

// ── Module-level state ───────────────────────────────────────────

/** @type {object} Cached discovery payload */
let _lastDiscovery = {};

// ── Rendering helpers ─────────────────────────────────────────────

/**
 * Clear a tbody and show a single "no data" row.
 * @param {string} tbodyId
 * @param {number} colSpan
 * @param {string} message
 */
function showEmptyRow(tbodyId, colSpan, message) {
  const tbody = document.getElementById(tbodyId);
  if (!tbody) return;
  tbody.innerHTML = '';
  const tr = document.createElement('tr');
  const td = document.createElement('td');
  td.colSpan = colSpan;
  td.className = 'text-muted';
  td.style.textAlign = 'center';
  td.textContent = message;
  tr.appendChild(td);
  tbody.appendChild(tr);
}

/**
 * Render the "Workload" table.
 * If the discovery data contains a `conversion` key with a `workload` array,
 * use that. Otherwise show a placeholder row indicating the desktop pipeline
 * is the authoritative source.
 *
 * @param {object} discovery
 */
function renderWorkload(discovery) {
  const tbody = document.getElementById('conv-workload');
  if (!tbody) return;
  tbody.innerHTML = '';

  const items = (discovery.conversion && Array.isArray(discovery.conversion.workload))
    ? discovery.conversion.workload
    : [];

  if (items.length === 0) {
    showEmptyRow('conv-workload', 2, 'Keine offenen Dateien — Konvertierung laeuft auf dem Desktop');
    return;
  }

  for (const item of items) {
    const tr = document.createElement('tr');

    const tdName = document.createElement('td');
    tdName.textContent = item.file || item.path || String(item);
    tdName.style.fontFamily = 'var(--font-family)';

    const tdSize = document.createElement('td');
    tdSize.style.textAlign = 'right';
    tdSize.className = 'text-muted text-sm';
    if (item.size_bytes !== undefined) {
      tdSize.textContent = _formatBytes(item.size_bytes);
    } else if (item.size !== undefined) {
      tdSize.textContent = item.size;
    } else {
      tdSize.textContent = '-';
    }

    tr.appendChild(tdName);
    tr.appendChild(tdSize);
    tbody.appendChild(tr);
  }
}

/**
 * Render the "Fertiggestellt" table from discovery lore_stats.
 * Falls back to building a summary from the rulesets list if lore_stats is absent.
 *
 * @param {object} discovery
 */
function renderFinished(discovery) {
  const tbody = document.getElementById('conv-finished');
  if (!tbody) return;
  tbody.innerHTML = '';

  // Try lore_stats first (a dict: system_id -> { dirs, files })
  const loreStats = discovery.lore_stats || null;

  if (loreStats && typeof loreStats === 'object' && Object.keys(loreStats).length > 0) {
    for (const [systemId, info] of Object.entries(loreStats)) {
      const tr = document.createElement('tr');

      const tdSystem = document.createElement('td');
      tdSystem.className = 'text-accent';
      tdSystem.textContent = systemId;

      const tdDirs = document.createElement('td');
      tdDirs.style.textAlign = 'right';
      tdDirs.textContent = info.dirs !== undefined ? String(info.dirs) : '-';

      const tdFiles = document.createElement('td');
      tdFiles.style.textAlign = 'right';
      tdFiles.className = 'text-green';
      tdFiles.textContent = info.files !== undefined ? String(info.files) : '-';

      tr.appendChild(tdSystem);
      tr.appendChild(tdDirs);
      tr.appendChild(tdFiles);
      tbody.appendChild(tr);
    }
    return;
  }

  // Fall back: one row per ruleset with "?" file counts
  const rulesets = discovery.rulesets || [];
  if (rulesets.length > 0) {
    for (const rs of rulesets) {
      const tr = document.createElement('tr');

      const tdSystem = document.createElement('td');
      tdSystem.className = 'text-accent';
      tdSystem.textContent = rs.id || rs.name || String(rs);

      const tdDirs = document.createElement('td');
      tdDirs.style.textAlign = 'right';
      tdDirs.className = 'text-muted';
      tdDirs.textContent = '?';

      const tdFiles = document.createElement('td');
      tdFiles.style.textAlign = 'right';
      tdFiles.className = 'text-muted';
      tdFiles.textContent = '?';

      tr.appendChild(tdSystem);
      tr.appendChild(tdDirs);
      tr.appendChild(tdFiles);
      tbody.appendChild(tr);
    }

    // Note below the table
    const noteTr = document.createElement('tr');
    const noteTd = document.createElement('td');
    noteTd.colSpan = 3;
    noteTd.className = 'text-muted text-sm';
    noteTd.textContent = 'Genaue Datei-Zahlen nur ueber Desktop-GUI oder /api/lore_stats verfuegbar.';
    noteTr.appendChild(noteTd);
    tbody.appendChild(noteTr);
    return;
  }

  showEmptyRow('conv-finished', 3, 'Keine Daten — Engine noch nicht gestartet');
}

/**
 * Fetch fresh discovery data and re-render both tables.
 */
async function refresh() {
  try {
    const resp = await fetch('/api/discovery');
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    _lastDiscovery = await resp.json();
  } catch (err) {
    ARS.showNotification('Abruf fehlgeschlagen: ' + err.message, 'error');
  }
  renderWorkload(_lastDiscovery);
  renderFinished(_lastDiscovery);
}

// ── Utilities ─────────────────────────────────────────────────────

/**
 * Human-readable byte size.
 * @param {number} bytes
 * @returns {string}
 */
function _formatBytes(bytes) {
  if (bytes < 1024)        return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// ── Tab interface ─────────────────────────────────────────────────

function init(_container) {
  // Refresh button
  const btnRefresh = document.getElementById('conv-refresh');
  if (btnRefresh) {
    btnRefresh.addEventListener('click', () => { refresh(); });
  }

  // Use already-cached discovery from ARS if available
  const cached = ARS.getDiscovery();
  if (cached && Object.keys(cached).length > 0) {
    _lastDiscovery = cached;
    renderWorkload(_lastDiscovery);
    renderFinished(_lastDiscovery);
  } else {
    // Fetch fresh data on init
    refresh();
  }
}

function handleEvent(eventName, data) {
  // Re-render if the conversion pipeline reports progress
  if (eventName === 'conversion.progress' || eventName === 'conversion.done') {
    // Update workload table with event data if present
    if (data && (data.file || data.status)) {
      refresh();
    }
  }
}

function onEngineReady(discovery) {
  _lastDiscovery = discovery || {};
  renderWorkload(_lastDiscovery);
  renderFinished(_lastDiscovery);
}

function onActivate() {
  // Refresh on tab activation so counts are always current
  refresh();
}

// ── Register ─────────────────────────────────────────────────────

ARS.registerTab('conversion', { init, handleEvent, onEngineReady, onActivate });
