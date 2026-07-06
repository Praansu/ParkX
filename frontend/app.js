// Dashboard frontend - polls FastAPI backend every 2s, vanilla JS + Chart.js

const ST = {
  slots: [true, true, true],
  books: [false, false, false],
  gate: false,
  distance: 0,
  online: false,
  uptime: 0,
  selSlot: 1,
  selTime: null,
  pending: null,
  toastTimer: null
};

const API_URL = '/api';
const PRICES = { 1: 50, 2: 90, 3: 130, 4: 160, 8: 280 };
let TAKEN_HOURS = { 1: [], 2: [], 3: [] };
let chartHourly = null;
let chartDaily = null;
let chartPredict = null;


// Startup
document.addEventListener('DOMContentLoaded', () => {
  initNavbar();
  initBookingForm();
  initSimControls();
  initChatbot();

  startClock();
  startUptime();

  pollStatus();
  setInterval(pollStatus, 2000);

  const bdate = document.getElementById('bdate');
  if (bdate) bdate.value = new Date().toISOString().slice(0, 10);

  loadBookingsTable();
  console.log("[ParkX] ready.");
});


// Tab switching
function initNavbar() {
  const tabs = document.querySelectorAll('.ntab');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const target = tab.getAttribute('data-tab');
      tabs.forEach(t => t.classList.remove('on'));
      tab.classList.add('on');
      document.querySelectorAll('.section').forEach(s => s.classList.remove('on'));
      const sec = document.getElementById(`tab-${target}`);
      if (sec) sec.classList.add('on');
      if (target === 'analytics') loadAnalyticsCharts();
      if (target === 'bookings') loadBookingsTable();
      if (target === 'alerts') loadAlertsData();
    });
  });
}


// Clock & uptime
function startClock() {
  const el = document.getElementById('clk');
  setInterval(() => { if (el) el.textContent = new Date().toLocaleTimeString('en-US', { hour12: false }); }, 1000);
}

function startUptime() {
  const el = document.getElementById('si-uptime');
  setInterval(() => {
    ST.uptime++;
    const h = String(Math.floor(ST.uptime / 3600)).padStart(2, '0');
    const m = String(Math.floor((ST.uptime % 3600) / 60)).padStart(2, '0');
    const s = String(ST.uptime % 60).padStart(2, '0');
    if (el) el.textContent = `${h}:${m}:${s}`;
  }, 1000);
}


// Toast
function showToast(msg, type = 'ok') {
  const t = document.getElementById('toast');
  if (!t) return;
  const icon = type === 'ok' ? '<i class="fa-solid fa-circle-check"></i>' : '<i class="fa-solid fa-circle-xmark"></i>';
  t.innerHTML = `${icon} ${msg}`;
  t.className = `show ${type}`;
  clearTimeout(ST.toastTimer);
  ST.toastTimer = setTimeout(() => { t.className = ''; }, 4000);
}


// Main poller — runs every 2s
async function pollStatus() {
  try {
    const res = await fetch(`${API_URL}/status`);
    if (!res.ok) throw new Error("Offline");
    const d = await res.json();

    ST.slots[0] = d.slot1 === 1;
    ST.slots[1] = d.slot2 === 1;
    ST.slots[2] = d.slot3 === 1;
    ST.gate = d.gate === 1;
    ST.distance = d.distance;
    ST.online = d.online;

    const free = d.slot1 + d.slot2 + d.slot3;
    updateConnection();
    updateMetrics(free);
    updateGate();
    await updateBookings();
    updateSlotCards();
    updateTrafficLight(free);
    updateLCD(free);
  } catch (e) {
    console.error("Poller:", e);
    const dot = document.getElementById('cdot');
    const lbl = document.getElementById('clbl');
    const off = document.getElementById('offnotice');
    if (dot) dot.className = 'conn-dot dead';
    if (lbl) lbl.textContent = 'BACKEND OFFLINE';
    if (off) off.classList.add('show');
  }
}


function updateConnection() {
  const dot = document.getElementById('cdot');
  const lbl = document.getElementById('clbl');
  const chip = document.getElementById('blynk-chip');
  const off = document.getElementById('offnotice');

  if (ST.online) {
    if (dot) dot.className = 'conn-dot live';
    if (lbl) lbl.textContent = 'ESP32 CLUSTER ACTIVE';
    if (chip) { chip.className = 'chip c-green'; chip.textContent = 'Blynk - Connected'; }
    if (off) off.classList.remove('show');
  } else {
    if (dot) dot.className = 'conn-dot dead';
    if (lbl) lbl.textContent = 'ESP32 CLUSTER OFFLINE';
    if (chip) { chip.className = 'chip c-red'; chip.textContent = 'Blynk - Offline'; }
    if (off) off.classList.add('show');
  }
}

function updateMetrics(free) {
  const fEl = document.getElementById('si-free');
  if (fEl) { fEl.textContent = `${free} / 3`; fEl.style.color = free > 0 ? 'var(--green)' : 'var(--red)'; }

  const gEl = document.getElementById('si-gate');
  if (gEl) {
    gEl.textContent = ST.gate ? 'Open (90 deg)' : 'Closed (0 deg)';
    gEl.style.color = ST.gate ? 'var(--amber)' : 'var(--sub)';
  }

  const dEl = document.getElementById('si-dist');
  if (dEl) dEl.textContent = `${Math.round(ST.distance)} cm`;

  const ex = document.getElementById('si-exit');
  if (ex) { ex.textContent = 'Clear'; ex.style.color = 'var(--sub)'; }
}

function updateGate() {
  const arm = document.getElementById('gate');
  if (arm) ST.gate ? arm.classList.add('open') : arm.classList.remove('open');
}


async function updateBookings() {
  try {
    const res = await fetch(`${API_URL}/bookings`);
    const bk = await res.json();
    const now = new Date();
    const today = now.toISOString().slice(0, 10);

    ST.books = [false, false, false];
    TAKEN_HOURS = { 1: [], 2: [], 3: [] };

    for (const b of bk) {
      if (b.status !== 'UPCOMING' && b.status !== 'ACTIVE') continue;
      TAKEN_HOURS[b.slot].push(b.time);
      if (b.date !== today) continue;
      const [h, m] = b.time.split(':').map(Number);
      const start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), h, m);
      const end = new Date(start.getTime() + b.dur * 3600000);
      if (now >= start && now < end) ST.books[b.slot - 1] = true;
    }
  } catch (e) { console.error("Bookings fetch:", e); }
}


function updateSlotCards() {
  for (let i = 0; i < 3; i++) {
    const card = document.getElementById(`slt-${i + 1}`);
    const chip = document.getElementById(`schip-${i + 1}`);
    const txt = document.getElementById(`sstate-${i + 1}`);
    const btn = document.getElementById(`sbtn-${i + 1}`);

    if (!ST.slots[i]) {
      if (card) card.className = 'slt occupied';
      if (chip) { chip.className = 'chip c-red'; chip.textContent = 'OCCUPIED'; }
      if (txt) txt.textContent = 'Vehicle Parked';
      if (btn) btn.disabled = true;
    } else if (ST.books[i]) {
      if (card) card.className = 'slt reserved';
      if (chip) { chip.className = 'chip c-amber'; chip.textContent = 'RESERVED'; }
      if (txt) txt.textContent = 'Booked Arrival';
      if (btn) btn.disabled = true;
    } else {
      if (card) card.className = 'slt free';
      if (chip) { chip.className = 'chip c-green'; chip.textContent = 'FREE'; }
      if (txt) txt.textContent = 'Empty';
      if (btn) btn.disabled = false;
    }
  }
}


function updateTrafficLight(free) {
  const r = document.getElementById('tl-r');
  const a = document.getElementById('tl-a');
  const g = document.getElementById('tl-g');
  const txt = document.getElementById('tl-txt');
  const chip = document.getElementById('tl-chip');
  const sig = document.getElementById('si-sig');

  if (ST.gate) {
    setBulbs(r, a, g, 'off', 'off', 'on');
    if (txt) txt.textContent = 'PROCEED';
    if (chip) { chip.className = 'chip c-green'; chip.textContent = 'Gate Open'; }
    if (sig) { sig.textContent = 'Go'; sig.style.color = 'var(--green)'; }
  } else if (free === 0) {
    setBulbs(r, a, g, 'on', 'off', 'off');
    if (txt) txt.textContent = 'FULL';
    if (chip) { chip.className = 'chip c-red'; chip.textContent = 'No Vacancy'; }
    if (sig) { sig.textContent = 'Stop'; sig.style.color = 'var(--red)'; }
  } else if (ST.distance > 0 && ST.distance < 10) {
    setBulbs(r, a, g, 'off', 'on', 'off');
    if (txt) txt.textContent = 'WAIT';
    if (chip) { chip.className = 'chip c-amber'; chip.textContent = 'Opening Gate'; }
    if (sig) { sig.textContent = 'Warning'; sig.style.color = 'var(--amber)'; }
  } else {
    setBulbs(r, a, g, 'on', 'off', 'off');
    if (txt) txt.textContent = 'STOP';
    if (chip) { chip.className = 'chip c-red'; chip.textContent = 'Awaiting Car'; }
    if (sig) { sig.textContent = 'Stop'; sig.style.color = 'var(--red)'; }
  }
}

function setBulbs(r, a, g, rs, as, gs) {
  if (r) r.className = `tl-bulb tl-r ${rs}`;
  if (a) a.className = `tl-bulb tl-a ${as}`;
  if (g) g.className = `tl-bulb tl-g ${gs}`;
}


function updateLCD(free) {
  const rows = document.getElementById('lcd-rows');
  const pwr = document.getElementById('lcd-pwr');
  if (!rows) return;

  if (!ST.online) {
    if (pwr) pwr.className = 'lcd-pwr';
    rows.innerHTML = `
      <div class="lcd-row">                    </div>
      <div class="lcd-row">   HARDWARE ERROR   </div>
      <div class="lcd-row">   Blynk offline    </div>
      <div class="lcd-row">                    </div>`;
    return;
  }

  if (pwr) pwr.className = 'lcd-pwr on';
  rows.innerHTML = `
    <div class="lcd-row">${`TOTAL FREE: ${free} / 3`.padEnd(20, ' ')}</div>
    <div class="lcd-row">${`SLOT 1: ${ST.slots[0] ? 'EMPTY' : 'OCCUPIED'}`.padEnd(20, ' ')}</div>
    <div class="lcd-row">${`SLOT 2: ${ST.slots[1] ? 'EMPTY' : 'OCCUPIED'}`.padEnd(20, ' ')}</div>
    <div class="lcd-row">${`SLOT 3: ${ST.slots[2] ? 'EMPTY' : 'OCCUPIED'}`.padEnd(20, ' ')}</div>`;
}


// Booking form
function initBookingForm() {
  const picker = document.getElementById('slot-picker');
  const items = picker?.querySelectorAll('.sp-item') || [];
  const bdur = document.getElementById('bdur');
  const bdate = document.getElementById('bdate');
  const bname = document.getElementById('bname');
  const bphone = document.getElementById('bphone');
  const bplate = document.getElementById('bplate');

  // Quick reserve from Live Map
  for (let i = 1; i <= 3; i++) {
    const btn = document.getElementById(`sbtn-${i}`);
    if (btn) {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        ST.selSlot = i;
        items.forEach(el => el.classList.toggle('sel', parseInt(el.getAttribute('data-s')) === i));
        const tab = document.querySelector('.ntab[data-tab="book"]');
        if (tab) tab.click();
        renderTimeSlots();
        syncSummary();
      });
    }
  }

  items.forEach(el => {
    el.addEventListener('click', () => {
      items.forEach(i => i.classList.remove('sel'));
      el.classList.add('sel');
      ST.selSlot = parseInt(el.getAttribute('data-s'));
      ST.selTime = null;
      renderTimeSlots();
      syncSummary();
    });
  });

  if (bdate) bdate.addEventListener('change', () => { renderTimeSlots(); syncSummary(); });
  [bdur, bname, bplate].forEach(el => {
    if (el) { el.addEventListener('input', syncSummary); el.addEventListener('change', syncSummary); }
  });

  const submitBtn = document.getElementById('btn-confirm-book');
  if (submitBtn) submitBtn.addEventListener('click', openModal);

  const cancelModal = document.getElementById('btn-modal-cancel');
  if (cancelModal) cancelModal.addEventListener('click', () => document.getElementById('modal')?.classList.remove('open'));

  const confirmModal = document.getElementById('btn-modal-confirm');
  if (confirmModal) confirmModal.addEventListener('click', executeBooking);

  const clearBtn = document.getElementById('btn-clear-form');
  if (clearBtn) clearBtn.addEventListener('click', clearForm);

  const scanBtn = document.getElementById('btn-anpr-fill');
  if (scanBtn) {
    scanBtn.addEventListener('click', async () => {
      try {
        const res = await fetch(`${API_URL}/anpr`);
        const d = await res.json();
        if (bplate && d.plate && d.plate !== '--') {
          bplate.value = d.plate;
          syncSummary();
          showToast(`Scanned: ${d.plate}`, 'ok');
        }
      } catch (e) { showToast("ANPR offline", "fail"); }
    });
  }

  renderTimeSlots();
  syncSummary();
}


function renderTimeSlots() {
  const grid = document.getElementById('tgrid');
  if (!grid) return;
  const hours = ['08:00','09:00','10:00','11:00','12:00','13:00','14:00','15:00','16:00','17:00','18:00','19:00'];
  const booked = TAKEN_HOURS[ST.selSlot] || [];
  grid.innerHTML = hours.map(h => {
    const taken = booked.includes(h);
    const sel = h === ST.selTime;
    return `<div class="tslot ${taken ? 'taken' : ''} ${sel ? 'sel' : ''}" onclick="selectHour('${h}')">${h}</div>`;
  }).join('');
}

window.selectHour = function(t) {
  ST.selTime = t;
  renderTimeSlots();
  syncSummary();
};


function syncSummary() {
  const slot = `Slot 0${ST.selSlot}`;
  const date = document.getElementById('bdate')?.value || '--';
  const time = ST.selTime || '--';
  const dur = parseInt(document.getElementById('bdur')?.value || 1);
  const name = document.getElementById('bname')?.value.trim() || '--';
  const plate = document.getElementById('bplate')?.value.trim().toUpperCase() || '--';
  const cost = PRICES[dur] || 50;

  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  set('sum-slot', slot); set('sum-date', date); set('sum-time', time);
  set('sum-dur', `${dur} hour${dur > 1 ? 's' : ''}`);
  set('sum-name', name); set('sum-plate', plate); set('sum-price', `NPR ${cost}`);
}


function openModal() {
  const name = document.getElementById('bname').value.trim();
  const plate = document.getElementById('bplate').value.trim().toUpperCase();
  const date = document.getElementById('bdate').value;
  const phone = document.getElementById('bphone').value.trim();
  const dur = parseInt(document.getElementById('bdur').value);

  if (!name || !plate || !date || !ST.selTime) {
    showToast("Fill all fields and pick a time.", "fail");
    return;
  }

  ST.pending = { slot: ST.selSlot, date, time: ST.selTime, dur, name, phone, plate, amount: PRICES[dur] || 50 };

  const body = document.getElementById('modal-body');
  if (body) {
    body.innerHTML = `
      <div class="cr"><span class="cr-ic"><i class="fa-solid fa-square-parking"></i></span><span class="cr-k">Bay</span><span class="cr-v">Slot 0${ST.pending.slot}</span></div>
      <div class="cr"><span class="cr-ic"><i class="fa-solid fa-calendar-day"></i></span><span class="cr-k">Date</span><span class="cr-v">${ST.pending.date}</span></div>
      <div class="cr"><span class="cr-ic"><i class="fa-solid fa-clock"></i></span><span class="cr-k">Arrival</span><span class="cr-v">${ST.pending.time} (${ST.pending.dur}h)</span></div>
      <div class="cr"><span class="cr-ic"><i class="fa-solid fa-id-card"></i></span><span class="cr-k">Plate</span><span class="cr-v">${ST.pending.plate}</span></div>
      <div class="cr"><span class="cr-ic"><i class="fa-solid fa-user"></i></span><span class="cr-k">Driver</span><span class="cr-v">${ST.pending.name}</span></div>
      <div class="cr"><span class="cr-ic"><i class="fa-solid fa-indian-rupee-sign"></i></span><span class="cr-k">Charge</span><span class="cr-v" style="color:var(--primary)">NPR ${ST.pending.amount}</span></div>`;
  }

  const modal = document.getElementById('modal');
  if (modal) modal.classList.add('open');
}


async function executeBooking() {
  if (!ST.pending) return;
  try {
    const res = await fetch(`${API_URL}/bookings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(ST.pending)
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail || "Overlap");
    const modal = document.getElementById('modal');
    if (modal) modal.classList.remove('open');
    showToast(`Registered: ${d.booking.id}`, 'ok');
    clearForm();
    loadBookingsTable();
    pollStatus();
  } catch (e) {
    const modal = document.getElementById('modal');
    if (modal) modal.classList.remove('open');
    showToast(e.message, 'fail');
  }
}


function clearForm() {
  const reset = id => { const el = document.getElementById(id); if (el) el.value = ''; };
  reset('bname'); reset('bphone'); reset('bplate');
  ST.selTime = null;
  renderTimeSlots();
  syncSummary();
}


// Bookings table
async function loadBookingsTable() {
  const tbody = document.getElementById('btbody');
  if (!tbody) return;

  try {
    const res = await fetch(`${API_URL}/bookings`);
    const data = await res.json();

    if (!data.length) {
      tbody.innerHTML = `<tr><td colspan="10" style="text-align:center;color:var(--sub)">No bookings yet.</td></tr>`;
      return;
    }

    const cls = { ACTIVE: 'c-green', UPCOMING: 'c-amber', COMPLETED: 'c-mute', CANCELLED: 'c-red' };

    tbody.innerHTML = data.map(b => `
      <tr>
        <td class="mono" style="font-weight:600;color:var(--primary)">${b.id}</td>
        <td>Slot 0${b.slot}</td>
        <td class="mono">${b.date}</td>
        <td class="mono">${b.time}</td>
        <td class="mono">${b.dur}h</td>
        <td class="mono" style="text-transform:uppercase">${b.plate}</td>
        <td>${b.name}</td>
        <td class="mono">NPR ${b.amount}</td>
        <td><span class="chip ${cls[b.status] || 'c-mute'}">${b.status}</span></td>
        <td>${b.status === 'UPCOMING' || b.status === 'ACTIVE'
          ? `<button class="btn btn-danger btn-xs" onclick="cancelReq('${b.id}')"><i class="fa-solid fa-trash-can"></i></button>`
          : '--'}</td>
      </tr>
    `).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center;color:var(--red)">Failed to load.</td></tr>`;
  }
}

window.cancelReq = async function(id) {
  try {
    const res = await fetch(`${API_URL}/bookings/${id}/cancel`, { method: 'POST' });
    if (!res.ok) throw new Error("Cancel failed");
    showToast(`Cancelled: ${id}`, 'ok');
    loadBookingsTable();
    pollStatus();
  } catch (e) { showToast("Error cancelling.", "fail"); }
};

const refreshBtn = document.getElementById('btn-refresh-bookings');
if (refreshBtn) refreshBtn.addEventListener('click', loadBookingsTable);


// Simulation controls
function initSimControls() {
  const act = (action, msg) => {
    showToast(msg, 'ok');
    fetch(`${API_URL}/simulate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action })
    }).catch(() => {});
  };

  const btn = id => document.getElementById(id);
  if (btn('btn-sim-entry')) btn('btn-sim-entry').addEventListener('click', () => act('entry', 'Vehicle at entrance'));
  if (btn('btn-sim-exit')) {
    btn('btn-sim-exit').addEventListener('click', () => {
      act('exit', 'Vehicle at exit');
      setTimeout(() => act('gate_off', ''), 4000);
    });
  }
  if (btn('btn-sim-full')) btn('btn-sim-full').addEventListener('click', () => act('fill', '100% capacity'));
  if (btn('btn-sim-reset')) {
    btn('btn-sim-reset').addEventListener('click', async () => {
      act('reset', 'Reset');
      const res = await fetch(`${API_URL}/bookings`);
      const bk = await res.json();
      for (const b of bk) {
        if (b.status === 'UPCOMING' || b.status === 'ACTIVE')
          await fetch(`${API_URL}/bookings/${b.id}/cancel`, { method: 'POST' });
      }
      loadBookingsTable();
    });
  }

  const input = document.getElementById('anpr-file-input');
  const anprBtn = document.getElementById('btn-sim-anpr');
  if (anprBtn && input) {
    anprBtn.addEventListener('click', () => input.click());
    input.addEventListener('change', async () => {
      if (!input.files.length) return;
      showToast("Scanning plate...", 'ok');
      try {
        const b64 = await new Promise(r => {
          const f = new FileReader();
          f.onload = e => r(e.target.result.split(',')[1]);
          f.readAsDataURL(input.files[0]);
        });
        const res = await fetch(`${API_URL}/anpr`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ image: b64 })
        });
        const d = await res.json();
        const plate = document.getElementById('bplate');
        if (plate && d.plate && d.plate !== '--') { plate.value = d.plate; syncSummary(); }
        showToast(`Plate: ${d.plate} (${Math.round((d.confidence||0)*100)}%)`, 'ok');
      } catch (e) { showToast("ANPR error.", 'fail'); }
    });
  }
}


// Analytics
async function loadAnalyticsCharts() {
  try {
    const res = await fetch(`${API_URL}/analytics`);
    const d = await res.json();

    const total = d.daily.reduce((s, x) => s + x.cnt, 0);
    document.getElementById('stat-visits').textContent = total;
    document.getElementById('stat-visits-sub').textContent = total > 0 ? "Last 7 days" : "No data";
    document.getElementById('stat-today').textContent = d.entries_today;
    document.getElementById('stat-s1').textContent = `${d.utilisation.slot1}%`;
    document.getElementById('stat-total').textContent = d.total_events;

    const colors = ['#10b981', '#f59e0b', '#6366f1'];
    for (let i = 1; i <= 3; i++) {
      const u = d.utilisation[`slot${i}`];
      const pct = document.getElementById(`util-pct-${i}`);
      const fill = document.getElementById(`util-fill-${i}`);
      if (pct) pct.textContent = `${u}%`;
      if (fill) { fill.style.width = `${u}%`; fill.style.background = colors[i-1]; }
    }

    const peak = d.hourly.reduce((m, h) => h.pct > m.pct ? h : m, { hour: '--', pct: 0 });
    const note = document.getElementById('util-note');
    if (note) {
      note.innerHTML = d.total_events < 10
        ? `<i class="fa-solid fa-circle-exclamation"></i> Collecting data (${d.total_events}/10 events).`
        : `<i class="fa-solid fa-circle-check"></i> Peak: <strong>${peak.hour}:00</strong> (${Math.round(peak.pct)}%).`;
    }

    // Hourly chart
    const hLabels = d.hourly.filter(x => parseInt(x.hour) >= 6).map(x => `${x.hour}:00`);
    const hData = d.hourly.filter(x => parseInt(x.hour) >= 6).map(x => x.pct);
    if (chartHourly) chartHourly.destroy();
    const ctxH = document.getElementById('chart-hourly-canvas').getContext('2d');
    const grad = ctxH.createLinearGradient(0, 0, 0, 200);
    grad.addColorStop(0, 'rgba(99,102,241,0.4)'); grad.addColorStop(1, 'rgba(99,102,241,0.01)');
    chartHourly = new Chart(ctxH, {
      type: 'line',
      data: { labels: hLabels, datasets: [{ label: 'Occupancy (%)', data: hData, borderColor: '#6366f1', borderWidth: 2, backgroundColor: grad, fill: true, tension: 0.4, pointBackgroundColor: '#6366f1' }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { color: 'rgba(255,255,255,0.02)' }, ticks: { color: '#8a90a6', font: { family: 'Outfit' } } }, y: { min: 0, max: 100, grid: { color: 'rgba(255,255,255,0.02)' }, ticks: { color: '#8a90a6', callback: v => `${v}%` } } } }
    });

    // Daily chart
    const dLabels = d.daily.map(x => x.day);
    const dData = d.daily.map(x => x.cnt);
    if (chartDaily) chartDaily.destroy();
    const ctxD = document.getElementById('chart-daily-canvas').getContext('2d');
    chartDaily = new Chart(ctxD, {
      type: 'bar',
      data: { labels: dLabels, datasets: [{ data: dData, backgroundColor: '#484e68', hoverBackgroundColor: '#6366f1', borderRadius: 4 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false }, ticks: { color: '#8a90a6' } }, y: { min: 0, grid: { color: 'rgba(255,255,255,0.02)' }, ticks: { color: '#8a90a6', stepSize: 1 } } } }
    });

    loadPredictions();
  } catch (e) { console.error("Analytics:", e); }
}


async function loadPredictions() {
  try {
    const res = await fetch(`${API_URL}/predict`);
    const d = await res.json();

    const badge = document.getElementById('predict-badge');
    if (badge) {
      badge.className = d.data_points >= 50 ? 'chip c-green' : 'chip c-amber';
      badge.textContent = d.data_points >= 50 ? `${d.data_points} logs` : `training (${d.data_points}/50)`;
    }

    const note = document.getElementById('predict-note');
    if (note) note.textContent = d.predictions[0]?.note || '';

    const labels = d.predictions.map(p => p.time);
    const pData = d.predictions.map(p => p.predicted_occupancy_percent);

    if (chartPredict) chartPredict.destroy();
    const ctxP = document.getElementById('chart-predict-canvas').getContext('2d');
    const g2 = ctxP.createLinearGradient(0, 0, 0, 200);
    g2.addColorStop(0, 'rgba(245,158,11,0.4)'); g2.addColorStop(1, 'rgba(245,158,11,0.01)');
    chartPredict = new Chart(ctxP, {
      type: 'line',
      data: { labels, datasets: [{ label: 'Predicted (%)', data: pData, borderColor: '#f59e0b', borderWidth: 2, backgroundColor: g2, fill: true, tension: 0.35, pointBackgroundColor: '#f59e0b' }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { color: 'rgba(255,255,255,0.02)' }, ticks: { color: '#8a90a6' } }, y: { min: 0, max: 100, grid: { color: 'rgba(255,255,255,0.02)' }, ticks: { color: '#8a90a6', callback: v => `${v}%` } } } }
    });
  } catch (e) { console.error("Predictions:", e); }
}


// Alerts
async function loadAlertsData() {
  const tbody = document.getElementById('alerts-tbody');
  const totalEl = document.getElementById('alert-total');
  const activeEl = document.getElementById('alert-active');
  const emailEl = document.getElementById('alert-email-status');
  const wrap = document.getElementById('alerts-table-wrap');
  const empty = document.getElementById('alerts-empty');
  const offline = document.getElementById('alerts-offline');
  const loading = document.getElementById('alerts-loading');

  if (loading) loading.style.display = 'block';
  if (wrap) wrap.style.display = 'none';
  if (empty) empty.style.display = 'none';
  if (offline) offline.style.display = 'none';

  try {
    const res = await fetch(`${API_URL}/alerts?limit=25`);
    const d = await res.json();

    if (loading) loading.style.display = 'none';
    if (totalEl) totalEl.textContent = d.total;

    const active = d.alerts.filter(a => a.severity !== 'info').length;
    if (activeEl) { activeEl.textContent = active; activeEl.style.color = active > 0 ? 'var(--red)' : 'var(--green)'; }

    if (emailEl) { emailEl.textContent = 'Enabled (Gmail)'; emailEl.style.color = 'var(--green)'; }

    if (!d.alerts.length) { if (empty) empty.style.display = 'block'; return; }

    const colors = { critical: 'var(--red)', warning: 'var(--amber)', info: 'var(--sub)' };
    if (tbody) {
      tbody.innerHTML = d.alerts.map(a => {
        const [dt, tm] = (a.ts || '').split('T');
        return `<tr>
          <td class="mono">${dt}<br><span style="color:var(--mute)">${(tm||'').slice(0,8)}</span></td>
          <td class="mono" style="text-transform:capitalize">${a.alert_type.replace(/_/g,' ')}</td>
          <td><span style="color:${colors[a.severity]};font-weight:600">[${a.severity}]</span></td>
          <td style="line-height:1.4">${a.message}</td>
          <td class="mono" style="color:${a.emailed ? 'var(--green)' : 'var(--mute)'}">${a.emailed ? 'Sent' : '--'}</td>
        </tr>`;
      }).join('');
    }
    if (wrap) wrap.style.display = 'block';
  } catch (e) {
    if (loading) loading.style.display = 'none';
    if (offline) offline.style.display = 'block';
  }
}

const refreshAlerts = document.getElementById('btn-refresh-alerts');
if (refreshAlerts) refreshAlerts.addEventListener('click', loadAlertsData);


// Chatbot
const chatHistory = [];

function initChatbot() {
  const toggle = document.getElementById('cb-toggle');
  const win = document.getElementById('chatbot');
  const close = document.getElementById('btn-chat-close');
  const send = document.getElementById('btn-chat-send');
  const input = document.getElementById('cb-input');

  if (toggle && win) toggle.addEventListener('click', () => { win.classList.add('open'); toggle.style.display = 'none'; });
  if (close && win && toggle) close.addEventListener('click', () => { win.classList.remove('open'); toggle.style.display = 'flex'; });
  if (send) send.addEventListener('click', submitChat);
  if (input) input.addEventListener('keydown', e => { if (e.key === 'Enter') submitChat(); });
}


async function submitChat() {
  const input = document.getElementById('cb-input');
  const msg = input.value.trim();
  if (!msg) return;

  const body = document.getElementById('cb-body');
  body.innerHTML += `<div class="cb-msg user">${msg}</div>`;
  input.value = '';
  body.scrollTop = body.scrollHeight;

  chatHistory.push({ role: 'user', content: msg });
  const tmpId = `dot-${Date.now()}`;
  body.innerHTML += `<div class="cb-msg bot" id="${tmpId}"><i class="fa-solid fa-ellipsis animate"></i></div>`;
  body.scrollTop = body.scrollHeight;

  try {
    const res = await fetch(`${API_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg, history: chatHistory.slice(-12) })
    });
    const d = await res.json();

    const ld = document.getElementById(tmpId);
    if (ld) ld.remove();
    body.innerHTML += `<div class="cb-msg bot">${d.reply}</div>`;
    chatHistory.push({ role: 'assistant', content: d.reply });
    if (chatHistory.length > 40) chatHistory.splice(0, chatHistory.length - 40);

    if (d.action_executed) {
      loadBookingsTable();
      pollStatus();
      loadAlertsData();
    }
  } catch (e) {
    const ld = document.getElementById(tmpId);
    if (ld) ld.remove();
    body.innerHTML += `<div class="cb-msg error"><i class="fa-solid fa-triangle-exclamation"></i> AI offline — check server.</div>`;
  }
  body.scrollTop = body.scrollHeight;
}
