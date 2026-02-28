/* ─── device.js v3: Date picker + device heatmap + accurate stats ─── */

const WS_URL = `ws://${location.host}/ws`;
const API_BASE = `${location.protocol}//${location.host}/api`;
const deviceId = location.pathname.split('/').pop();

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

// ── Clock ─────────────────────────────────────────
function startClock() {
    const el = document.getElementById('headerTime');
    function tick() { el.textContent = new Date().toLocaleString('zh-CN', { hour12: false }); }
    tick(); setInterval(tick, 1000);
}

// ── Realtime chart ────────────────────────────────
const MAX_RT = 300;
let rtUpData = Array(MAX_RT).fill(null);
let rtDownData = Array(MAX_RT).fill(null);
const rtLabels = Array(MAX_RT).fill('');
let realtimeChart = null;

function initRealtimeChart() {
    const ctx = document.getElementById('realtimeChart').getContext('2d');
    realtimeChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: rtLabels,
            datasets: [
                { label: '上传', data: rtUpData, borderColor: '#22d3ee', borderWidth: 1.5, fill: true, backgroundColor: 'rgba(34,211,238,0.08)', tension: 0.4, pointRadius: 0 },
                { label: '下载', data: rtDownData, borderColor: '#a78bfa', borderWidth: 1.5, fill: true, backgroundColor: 'rgba(167,139,250,0.08)', tension: 0.4, pointRadius: 0 }
            ]
        },
        options: {
            animation: false,
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: true, labels: { color: '#94a3b8', boxWidth: 12, font: { size: 11 } } },
                tooltip: { callbacks: { label: c => `${c.dataset.label}: ${fmtSpeed(c.raw)}` } }
            },
            scales: {
                x: { display: false },
                y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8', callback: v => fmtSpeed(v) } }
            }
        }
    });
}

async function loadRealtimeHistory() {
    try {
        const res = await fetch(`${API_BASE}/realtime/${deviceId}?seconds=300`);
        const json = await res.json();
        json.data.forEach(row => {
            rtUpData.push(row.upload_bps);
            rtDownData.push(row.download_bps);
            rtLabels.push('');
        });
        while (rtUpData.length > MAX_RT) { rtUpData.shift(); rtDownData.shift(); rtLabels.shift(); }
        realtimeChart.update('none');
    } catch (e) { console.warn('RT history failed', e); }
}

function pushRealtimePoint(up, down) {
    rtUpData.push(up); rtDownData.push(down); rtLabels.push('');
    if (rtUpData.length > MAX_RT) { rtUpData.shift(); rtDownData.shift(); rtLabels.shift(); }
    realtimeChart.update('none');
}

// ── History chart ─────────────────────────────────
let historyChart = null;

function initHistoryChart() {
    const ctx = document.getElementById('historyChart').getContext('2d');
    historyChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: [],
            datasets: [
                { label: '上传', data: [], backgroundColor: 'rgba(34,211,238,0.7)', borderRadius: 4 },
                { label: '下载', data: [], backgroundColor: 'rgba(167,139,250,0.7)', borderRadius: 4 }
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { display: true, labels: { color: '#94a3b8', boxWidth: 12, font: { size: 11 } } },
                tooltip: { callbacks: { label: c => `${c.dataset.label}: ${fmtBytes(c.raw)}` } }
            },
            scales: {
                x: { grid: { display: false }, ticks: { color: '#94a3b8', maxTicksLimit: 14, font: { size: 10 } } },
                y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8', callback: v => fmtBytes(v) } }
            }
        }
    });
}

// ── Date range helpers ────────────────────────────
function todayRange() {
    const now = new Date();
    const from = new Date(now); from.setHours(0, 0, 0, 0);
    return { from_ts: from.getTime() / 1000, to_ts: now.getTime() / 1000 };
}
function yesterdayRange() {
    const now = new Date();
    const to = new Date(now); to.setHours(0, 0, 0, 0);
    const from = new Date(to); from.setDate(from.getDate() - 1);
    return { from_ts: from.getTime() / 1000, to_ts: to.getTime() / 1000 };
}
function weekRange() {
    const now = new Date();
    const from = new Date(now); from.setDate(from.getDate() - 7);
    return { from_ts: from.getTime() / 1000, to_ts: now.getTime() / 1000 };
}
function monthRange() {
    const now = new Date();
    const from = new Date(now); from.setDate(from.getDate() - 30);
    return { from_ts: from.getTime() / 1000, to_ts: now.getTime() / 1000 };
}

function formatLabel(ts, span_hours) {
    const d = new Date(ts * 1000);
    return span_hours <= 48
        ? d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
        : d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit' });
}

async function loadHistoryRange(from_ts, to_ts) {
    try {
        const url = `${API_BASE}/stats/${deviceId}?from_ts=${from_ts}&to_ts=${to_ts}`;
        const res = await fetch(url);
        const json = await res.json();

        document.getElementById('totalUpBytes').textContent = fmtBytes(json.total_upload_bytes || 0);
        document.getElementById('totalDownBytes').textContent = fmtBytes(json.total_download_bytes || 0);

        const hourly = json.hourly || [];
        const span_hours = (to_ts - from_ts) / 3600;
        const labels = hourly.map(r => formatLabel(r.hour_start, span_hours));

        historyChart.data.labels = labels;
        historyChart.data.datasets[0].data = hourly.map(r => r.upload_bytes);
        historyChart.data.datasets[1].data = hourly.map(r => r.download_bytes);
        historyChart.update();

        // Peak hours from the hourly data
        if (hourly.length > 0) {
            const peakDown = hourly.reduce((a, b) => a.download_bytes >= b.download_bytes ? a : b);
            const peakUp = hourly.reduce((a, b) => a.upload_bytes >= b.upload_bytes ? a : b);
            const pdDate = new Date(peakDown.hour_start * 1000);
            const puDate = new Date(peakUp.hour_start * 1000);
            document.getElementById('detailPeakDown').textContent =
                `${pdDate.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })} ${pdDate.getHours()}:00`;
            document.getElementById('detailPeakUp').textContent =
                `${puDate.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })} ${puDate.getHours()}:00`;
        }
    } catch (e) { console.warn('History range load failed', e); }
}

// ── Period quick-select tabs ──────────────────────
let activeRange = todayRange();

function selectPeriodTab(period) {
    document.querySelectorAll('#devPeriodTabs .tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`#devPeriodTabs [data-period="${period}"]`)?.classList.add('active');
    if (period === 'day') activeRange = todayRange();
    else if (period === 'yesterday') activeRange = yesterdayRange();
    else if (period === 'week') activeRange = weekRange();
    else if (period === 'month') activeRange = monthRange();
    loadHistoryRange(activeRange.from_ts, activeRange.to_ts);
}

document.querySelectorAll('#devPeriodTabs .tab').forEach(btn => {
    btn.addEventListener('click', () => selectPeriodTab(btn.dataset.period));
});

// ── Custom date range picker ──────────────────────
document.getElementById('applyDateBtn').addEventListener('click', () => {
    const fromInput = document.getElementById('dateFrom').value;
    const toInput = document.getElementById('dateTo').value;
    if (!fromInput) return;

    const from = new Date(fromInput + 'T00:00:00');
    const to = toInput ? new Date(toInput + 'T23:59:59') : new Date();

    if (isNaN(from.getTime())) return;

    activeRange = { from_ts: from.getTime() / 1000, to_ts: to.getTime() / 1000 };
    // Deselect preset tabs
    document.querySelectorAll('#devPeriodTabs .tab').forEach(t => t.classList.remove('active'));
    loadHistoryRange(activeRange.from_ts, activeRange.to_ts);
});

// Set default "to" date to today
document.getElementById('dateTo').value = new Date().toISOString().split('T')[0];
document.getElementById('dateFrom').value = (() => {
    const d = new Date(); d.setDate(d.getDate() - 1); return d.toISOString().split('T')[0];
})();

// ── Device heatmap ────────────────────────────────
const DOW_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

function buildHourAxis(axisId) {
    const ax = document.getElementById(axisId);
    if (!ax) return;
    ax.innerHTML = '<div class="hm-dow-label"></div>';
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
    return type === 'up'
        ? `rgba(34,211,238,${(t * 0.85 + 0.05).toFixed(2)})`
        : `rgba(167,139,250,${(t * 0.85 + 0.05).toFixed(2)})`;
}

async function loadDeviceHeatmap() {
    const grid = document.getElementById('devHmGrid');
    try {
        const res = await fetch(`${API_BASE}/weekly/${deviceId}`);
        const json = await res.json();
        const rows = json.rows || [];

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
                el.innerHTML = `
          <div class="hm-cell-top" style="background:${heatmapColor(cell.avg_up, maxUp, 'up')}"></div>
          <div class="hm-cell-bot" style="background:${heatmapColor(cell.avg_down, maxDown, 'down')}"></div>
        `;
                el.title = `${DOW_LABELS[ri]} ${h}:00\n↑ ${fmtBytes(cell.avg_up)}/h  ↓ ${fmtBytes(cell.avg_down)}/h`;
                grid.appendChild(el);
            });
        });
    } catch (e) {
        grid.innerHTML = '<div style="padding:16px;color:#f87171;">热力图加载失败</div>';
    }
}

// ── Device info ───────────────────────────────────
async function loadDeviceInfo() {
    try {
        const res = await fetch(`${API_BASE}/devices/${deviceId}`);
        const d = await res.json();
        document.title = `${d.name} — NetMonitor`;
        document.getElementById('deviceNameTitle').textContent = d.name;
        document.getElementById('heroName').textContent = d.name;
        document.getElementById('heroIcon').textContent =
            d.platform === 'darwin' ? '🍎' : d.platform === 'windows' ? '🪟' : '🐧';
        document.getElementById('heroPlatform').textContent =
            d.platform === 'darwin' ? 'macOS' : d.platform === 'windows' ? 'Windows' : d.platform;
        document.getElementById('heroIp').textContent = d.ip || '—';
        const badge = document.getElementById('heroBadge');
        badge.textContent = d.online ? '在线' : '离线';
        if (d.online) badge.classList.add('online');
        const l = d.latest || {};
        document.getElementById('liveUp').textContent = fmtSpeed(l.upload_bps || 0);
        document.getElementById('liveDown').textContent = fmtSpeed(l.download_bps || 0);
    } catch (e) { console.warn('Device info failed', e); }
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
    ws.onopen = () => {
        updateWsStatus('connected');
        if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null; }
    };
    ws.onmessage = evt => {
        const msg = JSON.parse(evt.data);
        if (msg.type === 'speed' && msg.device_id === deviceId) {
            document.getElementById('liveUp').textContent = fmtSpeed(msg.upload_bps);
            document.getElementById('liveDown').textContent = fmtSpeed(msg.download_bps);
            pushRealtimePoint(msg.upload_bps, msg.download_bps);
            const badge = document.getElementById('heroBadge');
            badge.textContent = '在线'; badge.classList.add('online');
        }
        if (msg.type === 'heartbeat' && msg.online?.[deviceId] !== undefined) {
            const online = msg.online[deviceId];
            const badge = document.getElementById('heroBadge');
            badge.textContent = online ? '在线' : '离线';
            badge.classList.toggle('online', !!online);
        }
    };
    ws.onerror = () => updateWsStatus('error');
    ws.onclose = () => {
        updateWsStatus('error');
        wsReconnectTimer = setTimeout(connectWS, 2000);
    };
}

// ── Bootstrap ─────────────────────────────────────
startClock();
initRealtimeChart();
initHistoryChart();
buildHourAxis('devHmHourAxis');
connectWS();
loadDeviceInfo();
loadRealtimeHistory();
selectPeriodTab('day');
loadDeviceHeatmap();
