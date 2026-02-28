/* ─── app.js v3: Sparklines + Heatmap + Sorting + Fast Refresh ─── */

const WS_URL = `ws://${location.host}/ws`;
const API_BASE = `${location.protocol}//${location.host}/api`;

// ── Utilities ─────────────────────────────────────
function fmtSpeed(bps) {
    if (!bps || bps <= 0) return '0 bps';
    if (bps >= 1e9) return (bps / 1e9).toFixed(2) + ' Gbps';
    if (bps >= 1e6) return (bps / 1e6).toFixed(2) + ' Mbps';
    if (bps >= 1e3) return (bps / 1e3).toFixed(1) + ' Kbps';
    return Math.round(bps) + ' bps';
}
function fmtBytes(bytes) {
    if (!bytes || bytes <= 0) return '0 B';
    if (bytes >= 1e12) return (bytes / 1e12).toFixed(2) + ' TB';
    if (bytes >= 1e9) return (bytes / 1e9).toFixed(2) + ' GB';
    if (bytes >= 1e6) return (bytes / 1e6).toFixed(2) + ' MB';
    if (bytes >= 1e3) return (bytes / 1e3).toFixed(1) + ' KB';
    return Math.round(bytes) + ' B';
}
function escHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function platformIcon(p) {
    const pl = (p || '').toLowerCase();
    if (pl === 'darwin') return '🍎';
    if (pl === 'windows') return '🪟';
    return '🐧';
}
function parseSpeedText(text) {
    if (!text) return 0;
    const m = text.match(/([\d.]+)\s*(Gbps|Mbps|Kbps|bps)/);
    if (!m) return 0;
    const n = parseFloat(m[1]);
    switch (m[2]) {
        case 'Gbps': return n * 1e9;
        case 'Mbps': return n * 1e6;
        case 'Kbps': return n * 1e3;
        default: return n;
    }
}

// ── Clock ─────────────────────────────────────────
function startClock() {
    const el = document.getElementById('headerTime');
    function tick() { el.textContent = new Date().toLocaleString('zh-CN', { hour12: false }); }
    tick(); setInterval(tick, 1000);
}

// ═══════════════════════════════════════════════════
// PEAK CHART (top right, all-device aggregate)
// ═══════════════════════════════════════════════════
const PEAK_MAX = 300;
const peakUpData = Array(PEAK_MAX).fill(null);
const peakDownData = Array(PEAK_MAX).fill(null);
const peakLabels = Array(PEAK_MAX).fill('');
let peakChart = null;
let sessionPeakUp = 0, sessionPeakDown = 0;

function initPeakChart() {
    const ctx = document.getElementById('peakChart').getContext('2d');
    peakChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: peakLabels,
            datasets: [
                { label: '上传', data: peakUpData, borderColor: '#22d3ee', borderWidth: 1.5, fill: true, backgroundColor: 'rgba(34,211,238,0.07)', tension: 0.4, pointRadius: 0 },
                { label: '下载', data: peakDownData, borderColor: '#a78bfa', borderWidth: 1.5, fill: true, backgroundColor: 'rgba(167,139,250,0.07)', tension: 0.4, pointRadius: 0 }
            ]
        },
        options: {
            animation: false,
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: c => `${c.dataset.label}: ${fmtSpeed(c.raw)}` } }
            },
            scales: {
                x: { display: false },
                y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#94a3b8', font: { size: 10 }, callback: v => fmtSpeed(v) } }
            }
        }
    });
}

function pushPeakPoint(totalUp, totalDown) {
    peakUpData.push(totalUp); peakDownData.push(totalDown); peakLabels.push('');
    if (peakUpData.length > PEAK_MAX) { peakUpData.shift(); peakDownData.shift(); peakLabels.shift(); }
    peakChart.update('none');
    sessionPeakUp = Math.max(sessionPeakUp, totalUp);
    sessionPeakDown = Math.max(sessionPeakDown, totalDown);
    document.getElementById('kpiPeakUp').textContent = fmtSpeed(sessionPeakUp);
    document.getElementById('kpiPeakDown').textContent = fmtSpeed(sessionPeakDown);
}

// ═══════════════════════════════════════════════════
// SPARKLINES (per-device, canvas-drawn, no Chart.js)
// ═══════════════════════════════════════════════════
const SPARK_MAX = 10800;  // 3小时 × 3600秒
const sparkBuffers = {}; // device_id → { up: [], down: [] }

function getSparkBuf(id) {
    if (!sparkBuffers[id]) {
        sparkBuffers[id] = { up: Array(SPARK_MAX).fill(0), down: Array(SPARK_MAX).fill(0) };
    }
    return sparkBuffers[id];
}

function pushSparkData(id, up, down) {
    const buf = getSparkBuf(id);
    buf.up.push(up); buf.down.push(down);
    if (buf.up.length > SPARK_MAX) { buf.up.shift(); buf.down.shift(); }
    drawSparkline(id);
}

async function preloadSparkHistory(id) {
    try {
        const res = await fetch(`${API_BASE}/realtime/${id}?seconds=10800`);
        const json = await res.json();
        const pts = json.data || [];
        if (!pts.length) return;
        const buf = getSparkBuf(id);
        pts.forEach(p => { buf.up.push(p.upload_bps || 0); buf.down.push(p.download_bps || 0); });
        // Trim to max
        while (buf.up.length > SPARK_MAX) { buf.up.shift(); buf.down.shift(); }
        drawSparkline(id);
    } catch (e) { /* silently ignore */ }
}

function drawSparkline(id) {
    const canvas = document.getElementById(`spark-${id}`);
    if (!canvas) return;
    const W = canvas.width, H = canvas.height;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, W, H);
    const buf = getSparkBuf(id);
    if (!buf.up.length) return;
    const max = Math.max(...buf.up, ...buf.down, 1);
    const N = buf.up.length;

    function drawLine(data, color, fill) {
        ctx.beginPath();
        data.forEach((v, i) => {
            const x = (i / (N - 1)) * W;
            const y = H - (v / max) * (H - 2) - 1;
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        if (fill) {
            ctx.lineTo(W, H); ctx.lineTo(0, H); ctx.closePath();
            ctx.fillStyle = fill; ctx.fill();
        }
        ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke();
    }

    drawLine(buf.down, '#a78bfa', 'rgba(167,139,250,0.12)');
    drawLine(buf.up, '#22d3ee', 'rgba(34,211,238,0.15)');
}

// ═══════════════════════════════════════════════════
// SORTING
// ═══════════════════════════════════════════════════
let sortKey = null;      // 'name' | 'up' | 'down' | null
let sortDir = 1;         // 1=asc, -1=desc
let dynSortEnabled = false;

function getSortValue(id, key) {
    if (key === 'name') {
        const el = document.querySelector(`#row-${id} .device-row-name`);
        return el ? el.textContent.toLowerCase() : '';
    }
    const upEl = document.getElementById(`up-${id}`);
    const downEl = document.getElementById(`down-${id}`);
    if (key === 'up') return parseSpeedText(upEl?.textContent);
    if (key === 'down') return parseSpeedText(downEl?.textContent);
    return 0;
}

function applySort() {
    if (!sortKey) return;
    const tbody = document.getElementById('deviceTableBody');
    const rows = Array.from(tbody.querySelectorAll('tr.device-row'));
    rows.sort((a, b) => {
        const id_a = a.id.replace('row-', '');
        const id_b = b.id.replace('row-', '');
        const va = getSortValue(id_a, sortKey);
        const vb = getSortValue(id_b, sortKey);
        if (va < vb) return -sortDir;
        if (va > vb) return sortDir;
        return 0;
    });
    rows.forEach(r => tbody.appendChild(r));
    updateRanks();
}

function updateRanks() {
    document.querySelectorAll('tr.device-row').forEach((row, i) => {
        const rankEl = row.querySelector('.col-rank');
        if (rankEl) rankEl.textContent = i + 1;
    });
}

// Sort by column header click
document.querySelectorAll('th.sortable').forEach(th => {
    th.addEventListener('click', () => {
        const key = th.dataset.sort;
        if (sortKey === key) { sortDir *= -1; }
        else { sortKey = key; sortDir = key === 'name' ? 1 : -1; }
        // Update icons
        document.querySelectorAll('th.sortable .sort-icon').forEach(ic => ic.textContent = '⇅');
        th.querySelector('.sort-icon').textContent = sortDir === 1 ? '↑' : '↓';
        applySort();
    });
});

// Dynamic sort toggle
document.getElementById('dynSortToggle').addEventListener('change', e => {
    dynSortEnabled = e.target.checked;
    if (dynSortEnabled && !sortKey) {
        sortKey = 'down'; sortDir = -1;
    }
});

// ═══════════════════════════════════════════════════
// DEVICE TABLE
// ═══════════════════════════════════════════════════
const deviceMap = {};

function getOrCreateRow(device) {
    const id = device.id;
    let row = document.getElementById(`row-${id}`);
    if (!row) {
        row = document.createElement('tr');
        row.id = `row-${id}`;
        row.className = 'device-row';
        row.style.cursor = 'pointer';
        row.onclick = () => { location.href = `/device/${id}`; };
        row.innerHTML = `
      <td class="col-rank">—</td>
      <td class="col-name">
        <span class="plat-icon">${platformIcon(device.platform)}</span>
        <span class="device-row-name">${escHtml(device.name)}</span>
      </td>
      <td class="col-status"><span class="status-pill" id="pill-${id}">离线</span></td>
      <td class="col-speed up"  id="up-${id}">0 bps</td>
      <td class="col-speed down" id="down-${id}">0 bps</td>
      <td class="col-spark" onclick="event.stopPropagation()">
        <canvas id="spark-${id}" width="320" height="36"></canvas>
      </td>
    `;
        document.getElementById('deviceTableBody').appendChild(row);
    }
    return row;
}

function setOnlineStatus(id, online) {
    const pill = document.getElementById(`pill-${id}`);
    if (!pill) return;
    pill.textContent = online ? '在线' : '离线';
    pill.className = `status-pill ${online ? 'online' : ''}`;
    const row = document.getElementById(`row-${id}`);
    if (row) row.classList.toggle('offline-row', !online);
}

function updateSpeedCells(id, up, down) {
    const upEl = document.getElementById(`up-${id}`);
    const downEl = document.getElementById(`down-${id}`);
    if (upEl) upEl.textContent = fmtSpeed(up);
    if (downEl) downEl.textContent = fmtSpeed(down);
    pushSparkData(id, up, down);
}


function initDevices(devices) {
    const tbody = document.getElementById('deviceTableBody');
    tbody.innerHTML = '';

    if (!devices || devices.length === 0) {
        tbody.innerHTML = `<tr><td colspan="14" style="text-align:center;padding:48px;color:#475569;">暂无设备——请在电脑上启动 Agent</td></tr>`;
        document.getElementById('kpiOnline').textContent = '0';
        return;
    }

    const now = Date.now() / 1000;
    devices.forEach(d => {
        deviceMap[d.id] = { data: d };
        getOrCreateRow(d);
        const online = d.online || (d.last_seen && d.last_seen > now - 10);
        setOnlineStatus(d.id, online);
        const l = d.latest || {};
        updateSpeedCells(d.id, l.upload_bps || 0, l.download_bps || 0);
        preloadSparkHistory(d.id);  // 预加载 3h 历史
    });

    updateKpi();
    updateRanks();
    loadHeatmap();
}

// ── KPI Aggregation ───────────────────────────────
function updateKpi() {
    let online = 0, totalUp = 0, totalDown = 0;
    for (const id of Object.keys(deviceMap)) {
        const pill = document.getElementById(`pill-${id}`);
        if (pill?.classList.contains('online')) {
            online++;
            totalUp += parseSpeedText(document.getElementById(`up-${id}`)?.textContent);
            totalDown += parseSpeedText(document.getElementById(`down-${id}`)?.textContent);
        }
    }
    document.getElementById('kpiOnline').textContent = online;
    document.getElementById('kpiTotalUp').textContent = fmtSpeed(totalUp);
    document.getElementById('kpiTotalDown').textContent = fmtSpeed(totalDown);
    pushPeakPoint(totalUp, totalDown);
}

// ═══════════════════════════════════════════════════
// WEEKLY HEATMAP (7 rows × 24 columns)
// Each cell: top half = upload (cyan), bottom half = download (violet)
// ═══════════════════════════════════════════════════
const DOW_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

function buildHourAxis() {
    const ax = document.getElementById('hmHourAxis');
    ax.innerHTML = '<div class="hm-dow-label"></div>'; // spacer
    for (let h = 0; h < 24; h++) {
        const d = document.createElement('div');
        d.className = 'hm-hour-label';
        d.textContent = `${h}`;
        ax.appendChild(d);
    }
}

function heatmapColor(value, max, type) {
    if (!max) return 'transparent';
    const t = Math.min(value / max, 1);
    if (type === 'up') {
        // cyan: rgba(34,211,238, t)
        return `rgba(34,211,238,${(t * 0.85 + 0.05).toFixed(2)})`;
    } else {
        // violet: rgba(167,139,250, t)
        return `rgba(167,139,250,${(t * 0.85 + 0.05).toFixed(2)})`;
    }
}

async function loadHeatmap() {
    const grid = document.getElementById('hmGrid');
    grid.innerHTML = '<div class="loading-state" style="padding:40px;grid-column:1/-1"><div class="spinner"></div><span>加载热力图...</span></div>';
    try {
        const res = await fetch(`${API_BASE}/weekly`);
        const json = await res.json();
        const rows = json.rows || [];

        // Find global max for scaling
        let maxUp = 0, maxDown = 0;
        rows.forEach(row => row.hours.forEach(h => {
            maxUp = Math.max(maxUp, h.avg_up);
            maxDown = Math.max(maxDown, h.avg_down);
        }));

        grid.innerHTML = '';
        rows.forEach((row, ri) => {
            const dayLabel = document.createElement('div');
            dayLabel.className = 'hm-dow-label';
            dayLabel.textContent = DOW_LABELS[ri];
            grid.appendChild(dayLabel);

            row.hours.forEach((cell, h) => {
                const el = document.createElement('div');
                el.className = 'hm-cell';
                const upColor = heatmapColor(cell.avg_up, maxUp, 'up');
                const downColor = heatmapColor(cell.avg_down, maxDown, 'down');
                el.innerHTML = `
          <div class="hm-cell-top"   style="background:${upColor}"></div>
          <div class="hm-cell-bot"   style="background:${downColor}"></div>
        `;
                el.title = `${DOW_LABELS[ri]} ${h}:00\n↑ ${fmtBytes(cell.avg_up)}/h  ↓ ${fmtBytes(cell.avg_down)}/h`;
                grid.appendChild(el);
            });
        });
    } catch (e) {
        grid.innerHTML = '<div style="padding:20px;color:#f87171;">热力图加载失败</div>';
        console.warn('Heatmap load failed', e);
    }
}

// ── WS Updates ────────────────────────────────────
function handleSpeedUpdate(msg) {
    const { device_id, upload_bps, download_bps } = msg;
    if (!deviceMap[device_id]) {
        fetch(`${API_BASE}/devices`).then(r => r.json()).then(initDevices).catch(() => { });
        return;
    }
    updateSpeedCells(device_id, upload_bps, download_bps);
    setOnlineStatus(device_id, true);
    updateKpi();
    if (dynSortEnabled) applySort();
}

function handleHeartbeat(onlineMap) {
    Object.entries(onlineMap).forEach(([id, online]) => {
        setOnlineStatus(id, online);
        if (!online) updateSpeedCells(id, 0, 0);
    });
    updateKpi();
    if (dynSortEnabled) applySort();
}

// ── WebSocket ─────────────────────────────────────
let ws = null, wsReconnectTimer = null;

function updateWsStatus(state) {
    const el = document.getElementById('wsStatus');
    if (state === 'connected') { el.textContent = '● 已连接'; el.className = 'ws-indicator connected'; }
    else if (state === 'error') { el.textContent = '● 断开'; el.className = 'ws-indicator error'; }
    else { el.textContent = '● 连接中...'; el.className = 'ws-indicator'; }
}

function connectWS() {
    if (ws) { try { ws.close(); } catch (e) { } }
    ws = new WebSocket(WS_URL);
    ws.onopen = () => { updateWsStatus('connected'); if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null; } };
    ws.onmessage = evt => {
        const msg = JSON.parse(evt.data);
        if (msg.type === 'init') initDevices(msg.devices);
        else if (msg.type === 'speed') handleSpeedUpdate(msg);
        else if (msg.type === 'heartbeat') handleHeartbeat(msg.online);
    };
    ws.onerror = () => updateWsStatus('error');
    ws.onclose = () => { updateWsStatus('error'); wsReconnectTimer = setTimeout(connectWS, 2000); };
}

// ── Period tabs (now unused, kept for heatmap refresh) ─────────
// (tabs removed from HTML along with stat columns)

// ── Bootstrap ─────────────────────────────────────
startClock();
initPeakChart();
buildHourAxis();
connectWS();
