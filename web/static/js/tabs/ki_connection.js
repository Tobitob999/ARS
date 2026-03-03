/**
 * ARS Web GUI — KI-Connection Tab
 *
 * Displays real-time token usage, session totals, per-turn history,
 * and a canvas line chart of prompt vs. output tokens over time.
 */

// ── Chart State ─────────────────────────────────────────────────────────────

const CHART_MAX_POINTS = 50;

const _chart = {
  canvas: null,
  ctx: null,
  promptData: [],   // array of { turn, tokens }
  outputData: [],   // array of { turn, tokens }
};

// ── Session State ────────────────────────────────────────────────────────────

const _session = {
  turnCount: 0,
  promptTotal: 0,
  cachedTotal: 0,
  outputTotal: 0,
  thinkingTotal: 0,
  totalTokens: 0,
  sessionCost: 0,
  model: '-',
};

// ── Number Formatters ────────────────────────────────────────────────────────

function fmtNum(n) {
  return (n || 0).toLocaleString();
}

function fmtCost(n) {
  return '$' + (n || 0).toFixed(4);
}

// ── DOM helpers ──────────────────────────────────────────────────────────────

function setCell(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

// ── Chart Rendering ──────────────────────────────────────────────────────────

/**
 * Draw a two-line token trend chart on the canvas.
 * Colors: Prompt = #89B4FA (blue), Output = #A6E3A1 (green).
 */
function drawChart() {
  const canvas = _chart.canvas;
  if (!canvas) return;
  const ctx = _chart.ctx;

  // Determine actual pixel dimensions (account for devicePixelRatio)
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const W = rect.width  || canvas.offsetWidth  || 600;
  const H = rect.height || canvas.offsetHeight || 180;

  // Sync canvas pixel buffer to display size
  if (canvas.width !== Math.round(W * dpr) || canvas.height !== Math.round(H * dpr)) {
    canvas.width  = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    ctx.scale(dpr, dpr);
  }

  ctx.clearRect(0, 0, W, H);

  const PAD_LEFT   = 58;
  const PAD_RIGHT  = 16;
  const PAD_TOP    = 12;
  const PAD_BOTTOM = 28;

  const plotW = W - PAD_LEFT - PAD_RIGHT;
  const plotH = H - PAD_TOP  - PAD_BOTTOM;

  // Background
  ctx.fillStyle = '#1E1E2E';
  ctx.fillRect(0, 0, W, H);

  const allData = [..._chart.promptData, ..._chart.outputData];
  const maxTokens = allData.length > 0
    ? Math.max(...allData.map(d => d.tokens), 1)
    : 1;

  // Compute a nice rounded Y-axis maximum
  const rawMax = maxTokens;
  const magnitude = Math.pow(10, Math.floor(Math.log10(rawMax)));
  const yMax = Math.ceil(rawMax / magnitude) * magnitude || 1;

  const numTurns = Math.max(
    _chart.promptData.length > 0 ? _chart.promptData[_chart.promptData.length - 1].turn : 1,
    1
  );

  // ── Grid lines ────────────────────────────────────────────────
  ctx.strokeStyle = '#45475A';
  ctx.lineWidth = 0.5;
  ctx.setLineDash([3, 4]);

  const gridRows = 4;
  for (let i = 0; i <= gridRows; i++) {
    const y = PAD_TOP + plotH - (i / gridRows) * plotH;
    ctx.beginPath();
    ctx.moveTo(PAD_LEFT, y);
    ctx.lineTo(PAD_LEFT + plotW, y);
    ctx.stroke();

    // Y axis labels
    const labelVal = Math.round((i / gridRows) * yMax);
    ctx.fillStyle = '#6C7086';
    ctx.font = '10px Consolas, monospace';
    ctx.textAlign = 'right';
    ctx.fillText(labelVal >= 1000 ? (labelVal / 1000).toFixed(1) + 'k' : labelVal, PAD_LEFT - 4, y + 3);
  }

  ctx.setLineDash([]);

  // ── Axes ──────────────────────────────────────────────────────
  ctx.strokeStyle = '#6C7086';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(PAD_LEFT, PAD_TOP);
  ctx.lineTo(PAD_LEFT, PAD_TOP + plotH);
  ctx.lineTo(PAD_LEFT + plotW, PAD_TOP + plotH);
  ctx.stroke();

  // ── Helper to map data point to canvas coords ──────────────────
  function mapX(turn) {
    // Map turn number across the plot width
    const minTurn = _chart.promptData.length > 0 ? _chart.promptData[0].turn : 1;
    const range = Math.max(numTurns - minTurn, 1);
    return PAD_LEFT + ((turn - minTurn) / range) * plotW;
  }

  function mapY(tokens) {
    return PAD_TOP + plotH - (tokens / yMax) * plotH;
  }

  // ── X axis turn labels (sparse) ────────────────────────────────
  ctx.fillStyle = '#6C7086';
  ctx.font = '10px Consolas, monospace';
  ctx.textAlign = 'center';
  const labelStep = Math.max(1, Math.floor(_chart.promptData.length / 6));
  _chart.promptData.forEach((d, idx) => {
    if (idx % labelStep === 0 || idx === _chart.promptData.length - 1) {
      const x = mapX(d.turn);
      ctx.fillText(d.turn, x, PAD_TOP + plotH + 16);
    }
  });

  // ── Draw a line series ─────────────────────────────────────────
  function drawLine(data, color) {
    if (data.length < 1) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    data.forEach((d, i) => {
      const x = mapX(d.turn);
      const y = mapY(d.tokens);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Dots at each point (only if few points, or last point)
    if (data.length <= 20) {
      ctx.fillStyle = color;
      data.forEach(d => {
        ctx.beginPath();
        ctx.arc(mapX(d.turn), mapY(d.tokens), 3, 0, Math.PI * 2);
        ctx.fill();
      });
    } else {
      // Always mark the last point
      const last = data[data.length - 1];
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(mapX(last.turn), mapY(last.tokens), 3, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  drawLine(_chart.promptData, '#89B4FA');   // blue — Prompt
  drawLine(_chart.outputData, '#A6E3A1');   // green — Output

  // ── Legend ────────────────────────────────────────────────────
  const legendX = PAD_LEFT + plotW - 120;
  const legendY = PAD_TOP + 8;

  ctx.font = '10px Consolas, monospace';
  ctx.textAlign = 'left';

  ctx.fillStyle = '#89B4FA';
  ctx.fillRect(legendX, legendY, 14, 3);
  ctx.fillStyle = '#A6ADCA';
  ctx.fillText('Prompt', legendX + 18, legendY + 4);

  ctx.fillStyle = '#A6E3A1';
  ctx.fillRect(legendX, legendY + 12, 14, 3);
  ctx.fillStyle = '#A6ADCA';
  ctx.fillText('Output', legendX + 18, legendY + 16);
}

// ── History Table ─────────────────────────────────────────────────────────────

function addHistoryRow(turn, promptTok, outputTok, costReq) {
  const tbody = document.getElementById('kic-history');
  if (!tbody) return;

  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td style="text-align:right">${turn}</td>
    <td style="text-align:right">${fmtNum(promptTok)}</td>
    <td style="text-align:right">${fmtNum(outputTok)}</td>
    <td style="text-align:right;color:var(--yellow)">${fmtCost(costReq)}</td>
  `;

  // Prepend so newest is at top
  if (tbody.firstChild) {
    tbody.insertBefore(tr, tbody.firstChild);
  } else {
    tbody.appendChild(tr);
  }

  // Keep history table bounded — remove old rows beyond 100
  while (tbody.rows.length > 100) {
    tbody.deleteRow(tbody.rows.length - 1);
  }
}

// ── Event Handlers ────────────────────────────────────────────────────────────

function onPromptSent(data) {
  // Track turn count — each prompt sent is a new turn
  _session.turnCount += 1;
  setCell('kic-status', 'Anfrage gesendet...');
  const statusEl = document.getElementById('kic-status');
  if (statusEl) statusEl.className = 'text-yellow';
}

function onUsageUpdate(data) {
  // Update model name
  if (data.model && data.model !== _session.model) {
    _session.model = data.model;
    setCell('kic-model', data.model);
  }

  // Update status indicator
  const statusEl = document.getElementById('kic-status');
  if (statusEl) {
    statusEl.textContent = 'Verbunden';
    statusEl.className = 'text-green';
  }

  // Prefer session-level cumulative totals if present
  const sess = data.session || {};
  _session.promptTotal   = sess.prompt_tokens     || data.prompt_tokens     || _session.promptTotal;
  _session.cachedTotal   = sess.cached_tokens     || data.cached_tokens     || _session.cachedTotal;
  _session.outputTotal   = sess.candidates_tokens || data.candidates_tokens || _session.outputTotal;
  _session.thinkingTotal = sess.thoughts_tokens   || data.thoughts_tokens   || _session.thinkingTotal;
  _session.totalTokens   = sess.total_tokens      || data.total_tokens      || _session.totalTokens;
  _session.sessionCost   = data.session_cost      || _session.sessionCost;

  // Update usage table cells
  setCell('kic-prompt',   fmtNum(_session.promptTotal));
  setCell('kic-cached',   fmtNum(_session.cachedTotal));
  setCell('kic-output',   fmtNum(_session.outputTotal));
  setCell('kic-thinking', fmtNum(_session.thinkingTotal));
  setCell('kic-total',    fmtNum(_session.totalTokens));

  // Per-request tokens for chart and history row
  const reqPrompt = data.prompt_tokens     || 0;
  const reqOutput = data.candidates_tokens || 0;
  const reqCost   = data.cost_request      || 0;
  const turnNum   = _session.turnCount;

  // Add chart data points — trim to CHART_MAX_POINTS
  _chart.promptData.push({ turn: turnNum, tokens: reqPrompt });
  _chart.outputData.push({ turn: turnNum, tokens: reqOutput });
  if (_chart.promptData.length > CHART_MAX_POINTS) _chart.promptData.shift();
  if (_chart.outputData.length > CHART_MAX_POINTS) _chart.outputData.shift();

  // Redraw chart
  drawChart();

  // Add history table row
  addHistoryRow(turnNum, reqPrompt, reqOutput, reqCost);
}

// ── ResizeObserver for chart canvas ──────────────────────────────────────────

let _resizeObserver = null;

function watchCanvasResize() {
  const canvas = document.getElementById('token-chart');
  if (!canvas || _resizeObserver) return;

  _resizeObserver = new ResizeObserver(() => {
    // Reset canvas dimensions so drawChart recalculates
    _chart.canvas = canvas;
    _chart.ctx = canvas.getContext('2d');
    canvas.width = 0;
    canvas.height = 0;
    drawChart();
  });
  _resizeObserver.observe(canvas);
}

// ── Tab Module ────────────────────────────────────────────────────────────────

const kiConnectionTab = {
  init(container) {
    // Grab canvas reference
    const canvas = document.getElementById('token-chart');
    if (canvas) {
      _chart.canvas = canvas;
      _chart.ctx = canvas.getContext('2d');
      watchCanvasResize();
    }

    // Initial status
    setCell('kic-model', '-');
    const statusEl = document.getElementById('kic-status');
    if (statusEl) {
      statusEl.textContent = 'Warte...';
      statusEl.className = 'text-muted';
    }
  },

  handleEvent(eventName, data) {
    switch (eventName) {
      case 'keeper.prompt_sent':
        onPromptSent(data);
        break;

      case 'keeper.usage_update':
        onUsageUpdate(data);
        break;

      default:
        break;
    }
  },

  onEngineReady(discovery) {
    // Reset session state for a new engine run
    _session.turnCount     = 0;
    _session.promptTotal   = 0;
    _session.cachedTotal   = 0;
    _session.outputTotal   = 0;
    _session.thinkingTotal = 0;
    _session.totalTokens   = 0;
    _session.sessionCost   = 0;
    _session.model         = '-';

    _chart.promptData = [];
    _chart.outputData = [];

    // Clear table cells
    ['kic-prompt', 'kic-cached', 'kic-output', 'kic-thinking', 'kic-total'].forEach(id => setCell(id, '0'));
    setCell('kic-model', '-');

    const statusEl = document.getElementById('kic-status');
    if (statusEl) {
      statusEl.textContent = 'Engine bereit';
      statusEl.className = 'text-green';
    }

    // Clear history
    const tbody = document.getElementById('kic-history');
    if (tbody) tbody.innerHTML = '';

    drawChart();
  },

  onActivate() {
    // Redraw chart in case canvas was invisible (zero size) before activation
    if (_chart.canvas) {
      _chart.canvas.width = 0;
      _chart.canvas.height = 0;
    }
    drawChart();
  },
};

ARS.registerTab('ki-connection', kiConnectionTab);
