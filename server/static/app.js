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
    if (pl.includes('darwin') || pl.includes('mac')) return '<span class="plat-badge mac" title="macOS">🍎 macOS</span>';
    if (pl.includes('windows')) return '<span class="plat-badge win" title="Windows">🪟 Win</span>';
    return '<span class="plat-badge linux" title="Linux">🐧 Linux</span>';
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
let peakUpData = [];
let peakDownData = [];
let peakChart = null;
let sessionPeakUp = 0, sessionPeakDown = 0;
let peakWindowSec = 300;

function initPeakChart() {
    const saved = localStorage.getItem('nm_peak_default_sec');
    if (saved) {
        peakWindowSec = parseInt(saved) || 300;
        const chk = document.getElementById('peakDefaultChk');
        if (chk) chk.checked = true;
    }
    updatePeakTabs();

    const ctx = document.getElementById('peakChart').getContext('2d');
    peakChart = new Chart(ctx, {
        type: 'line',
        data: {
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
                tooltip: {
                    callbacks: {
                        title: c => new Date(c[0].raw.x).toLocaleString('zh-CN'),
                        label: c => `${c.dataset.label}: ${fmtSpeed(c.raw.y)}`
                    }
                }
            },
            scales: {
                x: {
                    type: 'linear',
                    display: false,
                    min: Date.now() - peakWindowSec * 1000,
                    max: Date.now()
                },
                y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#94a3b8', font: { size: 10 }, callback: v => fmtSpeed(v) } }
            }
        }
    });

    fetchPeakHistory();
}

function updatePeakTabs() {
    document.querySelectorAll('.peak-tab').forEach(b => {
        b.classList.toggle('active', parseInt(b.dataset.sec) === peakWindowSec);
    });
}

function setPeakWindow(sec) {
    if (peakWindowSec === sec) return;
    peakWindowSec = sec;
    updatePeakTabs();

    // Clear custom date inputs
    const fromInput = document.getElementById('peakDateFrom');
    const toInput = document.getElementById('peakDateTo');
    if (fromInput) fromInput.value = '';
    if (toInput) toInput.value = '';

    fetchPeakHistory();
}

function savePeakDefault() {
    const chk = document.getElementById('peakDefaultChk');
    if (chk?.checked) {
        localStorage.setItem('nm_peak_default_sec', peakWindowSec);
    } else {
        localStorage.removeItem('nm_peak_default_sec');
    }
}

async function fetchPeakHistory(forceFromTs = 0, forceToTs = 0) {
    try {
        let url = `${API_BASE}/stats/aggregate?seconds=${peakWindowSec}`;
        if (forceFromTs > 0 && forceToTs > 0) {
            url = `${API_BASE}/stats/aggregate?from_ts=${forceFromTs}&to_ts=${forceToTs}`;
        }

        const res = await fetch(url);
        const json = await res.json();
        const data = json.data || [];

        // Connect logic to ensure trailing blanks show 0 instead of stretching across void
        const zeroFilledData = [];
        if (data.length > 0) {
            let lastTs = data[0].timestamp;
            for (let i = 0; i < data.length; i++) {
                const pt = data[i];
                // Insert zero-points for missing periods > threshold (e.g. 2 x bucket size)
                // We'll use 5 mins (300) to keep it safe and draw a drop-off line quickly
                if (pt.timestamp - lastTs > 300) {
                    zeroFilledData.push({ x: (lastTs + 1) * 1000, y: 0, _isGap: true }); // drop to zero right after offline
                    zeroFilledData.push({ x: (pt.timestamp - 1) * 1000, y: 0, _isGap: true }); // stay zero until right before back online
                }
                zeroFilledData.push({ x: pt.timestamp * 1000, y_up: pt.upload_bps, y_down: pt.download_bps });
                lastTs = pt.timestamp;
            }
        }

        // Map to {x,y} format
        peakUpData = zeroFilledData.map(d => ({ x: d.x, y: d._isGap ? 0 : d.y_up }));
        peakDownData = zeroFilledData.map(d => ({ x: d.x, y: d._isGap ? 0 : d.y_down }));

        peakChart.data.datasets[0].data = peakUpData;
        peakChart.data.datasets[1].data = peakDownData;

        const nowMs = Date.now();
        if (forceFromTs > 0 && forceToTs > 0) {
            peakChart.options.scales.x.min = forceFromTs * 1000;
            peakChart.options.scales.x.max = forceToTs * 1000;
        } else {
            peakChart.options.scales.x.min = nowMs - peakWindowSec * 1000;
            // set max cleanly to the future slightly so the right padding exists
            peakChart.options.scales.x.max = nowMs;
        }

        peakChart.update('none');
    } catch (e) { /* ignore */ }
}

function applyPeakCustomDate() {
    const fv = document.getElementById('peakDateFrom')?.value;
    const tv = document.getElementById('peakDateTo')?.value;
    if (!fv) return;
    const fromTs = Math.floor(new Date(fv + 'T00:00:00').getTime() / 1000);
    const toTs = tv ? Math.floor(new Date(tv + 'T23:59:59').getTime() / 1000) : Math.floor(Date.now() / 1000);

    // Clear tabs selection
    document.querySelectorAll('.peak-tab').forEach(b => b.classList.remove('active'));
    // Mark custom time window (0 means custom)
    peakWindowSec = 0;

    fetchPeakHistory(fromTs, toTs);
}

function pushPeakPoint(totalUp, totalDown) {
    sessionPeakUp = Math.max(sessionPeakUp, totalUp);
    sessionPeakDown = Math.max(sessionPeakDown, totalDown);
    document.getElementById('kpiPeakUp').textContent = fmtSpeed(sessionPeakUp);
    document.getElementById('kpiPeakDown').textContent = fmtSpeed(sessionPeakDown);

    // Only slide real-time if we are NOT on a custom static data-bound range
    if (peakWindowSec > 0) {
        const nowMs = Date.now();
        peakUpData.push({ x: nowMs, y: totalUp });
        peakDownData.push({ x: nowMs, y: totalDown });

        const minMs = nowMs - peakWindowSec * 1000;
        // prune arrays to avoid memory leak if tab left open for days
        while (peakUpData.length > 0 && peakUpData[0].x < minMs - 60000) peakUpData.shift();
        while (peakDownData.length > 0 && peakDownData[0].x < minMs - 60000) peakDownData.shift();

        peakChart.options.scales.x.min = minMs;
        peakChart.options.scales.x.max = nowMs;
        peakChart.update('none');
    }
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
        // ❌ No tr.onclick — navigation via the name <a> link instead
        row.innerHTML = `
      <td class="col-rank">—</td>
      <td class="col-name">
        <button class="action-btn rename-btn" id="btn-rename-${id}" title="重命名">✏️</button>
        <button class="action-btn delete-btn" id="btn-delete-${id}" title="删除">🗑</button>
        ${platformIcon(device.platform)}
        <a class="device-name-link" href="/device/${id}" id="name-${id}">${escHtml(device.name)}</a>
      </td>
      <td class="col-status"><span class="status-pill" id="pill-${id}">离线</span></td>
      <td class="col-speed up"  id="up-${id}">0 bps</td>
      <td class="col-speed down" id="down-${id}">0 bps</td>
      <td class="col-spark">
        <canvas id="spark-${id}" width="320" height="36"></canvas>
      </td>
    `;
        document.getElementById('deviceTableBody').appendChild(row);

        // Attach button listeners AFTER DOM insertion (no inline onclick conflict)
        document.getElementById(`btn-rename-${id}`)
            .addEventListener('click', e => { e.stopPropagation(); e.preventDefault(); renameDevice(id); });
        document.getElementById(`btn-delete-${id}`)
            .addEventListener('click', e => { e.stopPropagation(); e.preventDefault(); deleteDevice(id); });
    }
    return row;
}

// ── 内联弹框（替代被浏览器拦截的 prompt/confirm）────────
function showModal({ title, body, inputValue, confirmText, confirmClass, onConfirm }) {
    // Remove existing modal
    document.getElementById('nm-modal')?.remove();

    const modal = document.createElement('div');
    modal.id = 'nm-modal';
    modal.innerHTML = `
      <div class="nm-modal-backdrop"></div>
      <div class="nm-modal-box">
        <div class="nm-modal-title">${title}</div>
        <div class="nm-modal-body">${body}</div>
        ${inputValue !== undefined
            ? `<input class="nm-modal-input" id="nm-modal-input" type="text" value="${escHtml(inputValue)}" autocomplete="off">`
            : ''}
        <div class="nm-modal-footer">
          <button class="nm-btn nm-btn-cancel" id="nm-modal-cancel">取消</button>
          <button class="nm-btn nm-btn-confirm ${confirmClass || ''}" id="nm-modal-confirm">${confirmText}</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);

    const input = document.getElementById('nm-modal-input');
    if (input) { input.focus(); input.select(); }

    const close = () => document.getElementById('nm-modal')?.remove();

    document.getElementById('nm-modal-cancel').onclick = close;
    document.getElementById('nm-modal-backdrop') && (document.querySelector('.nm-modal-backdrop').onclick = close);
    document.getElementById('nm-modal-confirm').onclick = () => {
        const val = input ? input.value.trim() : null;
        close();
        onConfirm(val);
    };
    if (input) {
        input.addEventListener('keydown', e => {
            if (e.key === 'Enter') document.getElementById('nm-modal-confirm')?.click();
            if (e.key === 'Escape') close();
        });
    }
}

// ── 设备管理操作 ──────────────────────────────────────
function renameDevice(id) {
    const current = document.getElementById(`name-${id}`)?.textContent || '';
    showModal({
        title: '✏️ 重命名设备',
        body: '输入新的设备名称：',
        inputValue: current,
        confirmText: '确认',
        onConfirm: async (newName) => {
            if (!newName || newName === current) return;
            try {
                const r = await fetch(`${API_BASE}/devices/${id}/name`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: newName })
                });
                if (!r.ok) throw new Error(await r.text());
                const el = document.getElementById(`name-${id}`);
                if (el) el.textContent = newName;
                if (deviceMap[id]) deviceMap[id].name = newName;
            } catch (e) {
                console.error('重命名失败:', e);
            }
        }
    });
}

function deleteDevice(id) {
    const name = document.getElementById(`name-${id}`)?.textContent || id;
    showModal({
        title: '🗑 删除设备',
        body: `确定删除「<b>${escHtml(name)}</b>」及其所有历史数据吗？<br><small style="color:#f87171">此操作不可撤销</small>`,
        confirmText: '删除',
        confirmClass: 'nm-btn-danger',
        onConfirm: async () => {
            try {
                const r = await fetch(`${API_BASE}/devices/${id}`, { method: 'DELETE' });
                if (!r.ok) throw new Error(await r.text());
                document.getElementById(`row-${id}`)?.remove();
                delete deviceMap[id];
                delete sparkBuffers[id];
                updateKpi();
            } catch (e) {
                console.error('删除失败:', e);
            }
        }
    });
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

    // Live update for calendar heatmap (approx 1 message per sec, bps ≈ bytes)
    const tzOffset = new Date().getTimezoneOffset() * 60000;
    const todayStr = new Date(Date.now() - tzOffset).toISOString().slice(0, 10);
    const isCurrentMonth = (new Date(Date.now() - tzOffset).getFullYear() === calYear && (new Date(Date.now() - tzOffset).getMonth() + 1) === calMonth);
    let changed = false;

    if (isCurrentMonth && (upload_bps > 0 || download_bps > 0)) {
        if (!calData[todayStr]) calData[todayStr] = { upload_bytes: 0, download_bytes: 0 };
        // convert bps to bytes (bps / 8) because WS triggers every 1s
        calData[todayStr].upload_bytes += (upload_bps || 0) / 8;
        calData[todayStr].download_bytes += (download_bps || 0) / 8;
        changed = true;
    }

    if (changed) {
        renderCalendar();
    }

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
        else if (msg.type === 'device_renamed') {
            const el = document.getElementById(`name-${msg.device_id}`);
            if (el) el.textContent = msg.name;
            if (deviceMap[msg.device_id]) deviceMap[msg.device_id].name = msg.name;
        }
        else if (msg.type === 'device_deleted') {
            document.getElementById(`row-${msg.device_id}`)?.remove();
            delete deviceMap[msg.device_id];
            delete sparkBuffers[msg.device_id];
            updateKpi();
        }
    };
    ws.onerror = () => updateWsStatus('error');
    ws.onclose = () => { updateWsStatus('error'); wsReconnectTimer = setTimeout(connectWS, 2000); };
}

// ── Period tabs (now unused, kept for heatmap refresh) ─────────
// (tabs removed from HTML along with stat columns)

// ══════════════════════════════════════════════════════════
// MONTHLY CALENDAR HEATMAP
// ══════════════════════════════════════════════════════════
let calYear = new Date().getFullYear();
let calMonth = new Date().getMonth() + 1;  // 1-based
let calMode = 'up';   // 'up' | 'down'
let calData = {};     // {date: {upload_bytes, download_bytes}}

const CAL_UP_COLOR = [34, 211, 238]; // cyan
const CAL_DOWN_COLOR = [167, 139, 250]; // violet

function calColor(value, max, mode) {
    if (!max || !value) return 'rgba(255,255,255,0.04)';
    const t = Math.min(value / max, 1);
    const [r, g, b] = mode === 'up' ? CAL_UP_COLOR : CAL_DOWN_COLOR;
    return `rgba(${r},${g},${b},${(0.1 + t * 0.88).toFixed(2)})`;
}

function setCalMode(mode) {
    calMode = mode;
    document.getElementById('calTabUp').classList.toggle('active', mode === 'up');
    document.getElementById('calTabDown').classList.toggle('active', mode === 'down');
    renderCalendar();
}

function shiftCalMonth(delta) {
    calMonth += delta;
    if (calMonth > 12) { calMonth = 1; calYear++; }
    if (calMonth < 1) { calMonth = 12; calYear--; }
    loadCalendar();
}

async function loadCalendar() {
    document.getElementById('calGrid').innerHTML =
        '<div class="loading-state" style="grid-column:1/-1;padding:30px"><div class="spinner"></div><span>加载中...</span></div>';
    document.getElementById('calMonthLabel').textContent =
        `${calYear} 年 ${String(calMonth).padStart(2, '0')} 月`;
    try {
        const res = await fetch(`${API_BASE}/stats/daily?year=${calYear}&month=${calMonth}`);
        const json = await res.json();
        calData = {};
        (json.days || []).forEach(d => { calData[d.date] = d; });
        renderCalendar();
    } catch (e) {
        document.getElementById('calGrid').innerHTML =
            '<div style="padding:20px;color:#f87171;grid-column:1/-1">加载失败</div>';
    }
}

function renderCalendar() {
    const grid = document.getElementById('calGrid');
    const daysInMonth = new Date(calYear, calMonth, 0).getDate();
    // JS: 0=Sun 1=Mon ... we want Mon=0
    let firstDow = new Date(calYear, calMonth - 1, 1).getDay(); // 0=Sun
    firstDow = (firstDow + 6) % 7; // convert to Mon=0

    // Compute max for color scaling
    let maxVal = 0;
    let totalUp = 0, totalDown = 0, peakDate = '', peakVal = 0;
    for (const [date, d] of Object.entries(calData)) {
        totalUp += d.upload_bytes || 0;
        totalDown += d.download_bytes || 0;
        const v = calMode === 'up' ? d.upload_bytes : d.download_bytes;
        if ((v || 0) > maxVal) maxVal = v;
        if ((v || 0) > peakVal) { peakVal = v; peakDate = date; }
    }

    // Build grid cells
    let html = '';
    // Empty cells before first day
    for (let i = 0; i < firstDow; i++) {
        html += '<div class="cal-cell empty"></div>';
    }
    const tzOffset = new Date().getTimezoneOffset() * 60000;
    const today = new Date(Date.now() - tzOffset).toISOString().slice(0, 10);
    for (let day = 1; day <= daysInMonth; day++) {
        const dateStr = `${calYear}-${String(calMonth).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
        const d = calData[dateStr] || { upload_bytes: 0, download_bytes: 0 };
        const val = calMode === 'up' ? (d.upload_bytes || 0) : (d.download_bytes || 0);
        const color = calColor(val, maxVal, calMode);
        const weekday = ['日', '一', '二', '三', '四', '五', '六'][new Date(dateStr).getDay()];
        const isToday = dateStr === today;
        html += `<div class="cal-cell${isToday ? ' cal-today' : ''}"
          style="background:${color}"
          title="${dateStr} 周${weekday}\n↑ ${fmtBytes(d.upload_bytes || 0)}\n↓ ${fmtBytes(d.download_bytes || 0)}">
          <span class="cal-day-num">${day}</span>
          <div style="font-size: 0.65rem; line-height: 1.25; margin-top: auto; padding-top:4px; font-weight: 500;">
              ${(d.upload_bytes || d.download_bytes) ? `<div style="color:#ffffff; text-shadow: 0 1px 2px rgba(0,0,0,0.8);">↑ ${fmtBytes(d.upload_bytes || 0)}</div><div style="color:#ffffff; text-shadow: 0 1px 2px rgba(0,0,0,0.8);">↓ ${fmtBytes(d.download_bytes || 0)}</div>` : ''}
          </div>
        </div>`;
    }
    grid.innerHTML = html;

    // Summary stats
    const activeDays = Object.keys(calData).length || 1;
    document.getElementById('calMonthUp').textContent = fmtBytes(totalUp);
    document.getElementById('calMonthDown').textContent = fmtBytes(totalDown);
    document.getElementById('calDayAvgUp').textContent = fmtBytes(totalUp / activeDays);
    document.getElementById('calDayAvgDown').textContent = fmtBytes(totalDown / activeDays);
    document.getElementById('calPeakDay').textContent = peakDate ? peakDate.slice(5) + ` (${fmtBytes(peakVal)})` : '—';

    // Legend gradient
    const [r, g, b] = calMode === 'up' ? CAL_UP_COLOR : CAL_DOWN_COLOR;
    document.getElementById('calLegGrad').style.background =
        `linear-gradient(to right, rgba(${r},${g},${b},0.1), rgba(${r},${g},${b},0.98))`;
}

// ══════════════════════════════════════════════════════════
// GLOBAL HISTORY CHART
// ══════════════════════════════════════════════════════════
let globalHistoryChart = null;

function initGlobalHistoryChart() {
    const ctx = document.getElementById('globalHistoryChart').getContext('2d');
    globalHistoryChart = new Chart(ctx, {
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

    // Event listeners
    document.querySelectorAll('#globalPeriodTabs .tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('#globalPeriodTabs .tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            let range;
            switch (btn.dataset.period) {
                case 'day': range = todayRange(); break;
                case 'yesterday': range = yesterdayRange(); break;
                case 'week': range = weekRange(); break;
                case 'month': range = monthRange(); break;
            }
            if (range) loadGlobalHistoryRange(range.from_ts, range.to_ts);
        });
    });

    document.getElementById('applyGlobalDateBtn').addEventListener('click', () => {
        const fromV = document.getElementById('globalDateFrom').value;
        const toV = document.getElementById('globalDateTo').value;
        if (!fromV) return alert('请选择起始日期');
        const fromTs = Math.floor(new Date(fromV + 'T00:00:00').getTime() / 1000);
        const toTs = toV ? Math.floor(new Date(toV + 'T23:59:59').getTime() / 1000) : Math.floor(Date.now() / 1000);
        document.querySelectorAll('#globalPeriodTabs .tab').forEach(b => b.classList.remove('active'));
        loadGlobalHistoryRange(fromTs, toTs);
    });

    const initRange = todayRange();
    loadGlobalHistoryRange(initRange.from_ts, initRange.to_ts);
}

// Date helpers
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

async function loadGlobalHistoryRange(from_ts, to_ts) {
    try {
        const url = `${API_BASE}/stats/all?from_ts=${from_ts}&to_ts=${to_ts}`;
        const res = await fetch(url);
        const json = await res.json();

        document.getElementById('globalTotalUpBytes').textContent = fmtBytes(json.total_upload_bytes || 0);
        document.getElementById('globalTotalDownBytes').textContent = fmtBytes(json.total_download_bytes || 0);

        const hourly = json.hourly || [];
        const span_hours = (to_ts - from_ts) / 3600;
        const labels = hourly.map(r => formatLabel(r.hour_start, span_hours));

        globalHistoryChart.data.labels = labels;
        globalHistoryChart.data.datasets[0].data = hourly.map(r => r.upload_bytes);
        globalHistoryChart.data.datasets[1].data = hourly.map(r => r.download_bytes);
        globalHistoryChart.update();

        // Calculate peaks
        let pup = 0, pdown = 0, dtUp = '—', dtDown = '—';
        hourly.forEach((r, i) => {
            if (r.upload_bytes > pup) { pup = r.upload_bytes; dtUp = labels[i]; }
            if (r.download_bytes > pdown) { pdown = r.download_bytes; dtDown = labels[i]; }
        });
        document.getElementById('globalDetailPeakUp').textContent = dtUp + (pup > 0 ? ` (${fmtBytes(pup)})` : '');
        document.getElementById('globalDetailPeakDown').textContent = dtDown + (pdown > 0 ? ` (${fmtBytes(pdown)})` : '');
    } catch (e) { console.warn('History range load failed', e); }
}

// ── Bootstrap ─────────────────────────────────────
startClock();
initPeakChart();
initGlobalHistoryChart();
buildHourAxis();
connectWS();
loadCalendar();
