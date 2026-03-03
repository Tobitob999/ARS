/**
 * ARS Web GUI — Audio Tab
 *
 * Displays server-side TTS/STT backend info (read-only) and shows the
 * most recent speech transcription received via the WebSocket event stream.
 * Audio itself is processed entirely server-side; this tab is informational.
 */

// ── Module-level state ──────────────────────────────────────────

/** @type {string|null} Last known TTS backend name */
let _ttsBackend = null;

/** @type {string|null} Last known STT backend name */
let _sttBackend = null;

// ── DOM helpers ─────────────────────────────────────────────────

/**
 * Write text into a DOM element by id.
 * @param {string} id
 * @param {string} text
 * @param {string|null} className  Optional CSS class to set on the element.
 */
function setText(id, text, className = null) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  if (className !== null) el.className = className;
}

/**
 * Append a transcription entry to the last-STT output panel.
 * Each entry gets a timestamp prefix.
 * @param {string} text    Transcribed text.
 * @param {string} [lang]  Optional language hint (e.g. "de").
 */
function appendTranscription(text, lang) {
  const el = document.getElementById('audio-last-stt');
  if (!el) return;

  const now = new Date().toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  // Clear the placeholder dash shown on first load
  if (el.textContent === '-') el.textContent = '';

  const line = document.createElement('div');
  line.style.marginBottom = '4px';

  const ts = document.createElement('span');
  ts.className = 'timestamp';
  ts.textContent = '[' + now + '] ';

  const body = document.createElement('span');
  body.className = 'player';
  body.textContent = text || '(leer)';

  if (lang) {
    const langBadge = document.createElement('span');
    langBadge.className = 'text-muted text-sm';
    langBadge.textContent = ' (' + lang + ')';
    body.appendChild(langBadge);
  }

  line.appendChild(ts);
  line.appendChild(body);
  el.appendChild(line);

  // Auto-scroll to bottom
  el.scrollTop = el.scrollHeight;
}

// ── Backend info rendering ───────────────────────────────────────

/**
 * Render backend info rows.
 * Called on init (from cached engine state) and on engine_ready event.
 * @param {object} info  Object with optional .tts_backend / .stt_backend keys.
 */
function applyBackendInfo(info) {
  if (!info) return;

  if (info.tts_backend) {
    _ttsBackend = info.tts_backend;
    setText('audio-tts-backend', _ttsBackend, 'text-accent');
  }
  if (info.stt_backend) {
    _sttBackend = info.stt_backend;
    setText('audio-stt-backend', _sttBackend, 'text-accent');
  }
}

// ── Tab interface ────────────────────────────────────────────────

/**
 * init() — called once after DOMContentLoaded when app.js sets up all tabs.
 * @param {HTMLElement} _container  The tab panel element (unused here).
 */
function init(_container) {
  // Apply any engine state already available from discovery or server push
  const discovery = ARS.getDiscovery();
  if (discovery && discovery.audio) {
    applyBackendInfo(discovery.audio);
  }

  // Show the current engine state's backend info if it is embedded
  // (server sends it in the initial 'state' message)
  const state = ARS.getEngineState();
  if (state === 'running' && discovery && discovery.audio) {
    applyBackendInfo(discovery.audio);
  }
}

/**
 * handleEvent() — receives every WebSocket event forwarded by app.js.
 * @param {string} eventName
 * @param {object} data
 */
function handleEvent(eventName, data) {
  switch (eventName) {

    // Latest speech-to-text transcription
    case 'audio.stt_text': {
      const text = data.text || data.transcript || String(data);
      appendTranscription(text, data.lang || null);
      break;
    }

    // Engine state changes sometimes carry backend names
    case 'techgui.state_changed': {
      if (data.audio) applyBackendInfo(data.audio);
      break;
    }

    // Engine ready — discovery carries backend metadata
    case 'techgui.engine_ready': {
      if (data.audio) applyBackendInfo(data.audio);
      break;
    }

    default:
      break;
  }
}

/**
 * onEngineReady() — called after engine starts and discovery is refreshed.
 * @param {object} discovery  Full discovery payload from /api/discovery.
 */
function onEngineReady(discovery) {
  if (discovery && discovery.audio) {
    applyBackendInfo(discovery.audio);
  }
}

/**
 * onActivate() — called whenever the user switches to this tab.
 */
function onActivate() {
  // Re-apply in case the engine started while the tab was not visible
  const discovery = ARS.getDiscovery();
  if (discovery && discovery.audio) {
    applyBackendInfo(discovery.audio);
  }
}

// ── Register ─────────────────────────────────────────────────────

ARS.registerTab('audio', { init, handleEvent, onEngineReady, onActivate });
