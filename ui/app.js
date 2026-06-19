/* 근태 — frontend logic */

const DAYS = [
  ['mon', '월'], ['tue', '화'], ['wed', '수'], ['thu', '목'], ['fri', '금'],
];
const TYPES = ['', '연차', '오전반차', '오후반차', '휴일'];

let state = null;          // { settings, weeks: { 'YYYY-MM-DD(월요일)': { mon:{type,in,out}, ... } } }
let weekOffset = 0;        // 0 = 이번 주
let started = false;
let saveTimer = null;
let holidayMap = {};       // { 'YYYY-MM-DD': '공휴일 이름' } — 8시간 근무로 인정

/* ---------------- time helpers (단위: 초) ---------------- */
function pad(n) { return String(n).padStart(2, '0'); }
function floorToMinuteSec(sec) { return Math.floor(sec / 60) * 60; }
function ceilToMinuteSec(sec) { return Math.ceil(sec / 60) * 60; }

function parseTimeToSec(str) {
  if (str === null || str === undefined) return null;
  str = String(str).trim();
  if (!str) return null;
  let pm = false, am = false;
  const m = str.match(/(오전|오후|AM|PM)/i);
  if (m) {
    if (/오후|PM/i.test(m[1])) pm = true; else am = true;
    str = str.replace(m[1], '').trim();
  }
  let h, mi, se = 0;
  if (str.indexOf(':') >= 0) {
    const p = str.split(':').map(s => s.trim());
    h = parseInt(p[0], 10); mi = parseInt(p[1], 10); se = p[2] ? parseInt(p[2], 10) : 0;
  } else {
    const d = str.replace(/\D/g, '');
    if (d.length === 4) { h = +d.slice(0, 2); mi = +d.slice(2); }
    else if (d.length === 6) { h = +d.slice(0, 2); mi = +d.slice(2, 4); se = +d.slice(4); }
    else if (d.length && d.length <= 2) { h = +d; mi = 0; }
    else return null;
  }
  if (isNaN(h) || isNaN(mi) || isNaN(se)) return null;
  if (pm && h < 12) h += 12;
  if (am && h === 12) h = 0;
  if (h < 0 || h > 47 || mi < 0 || mi > 59) return null;
  return (h * 60 + mi) * 60 + se;
}

function fmt24(sec) {
  if (sec === null || sec === undefined) return '';
  sec = floorToMinuteSec(sec);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return pad(h) + ':' + pad(m);
}
function fmtKor(sec) {
  if (sec === null || sec === undefined) return '-';
  sec = floorToMinuteSec(sec);
  let h = Math.floor(sec / 3600) % 24;
  const m = Math.floor((sec % 3600) / 60);
  const ap = h < 12 ? '오전' : '오후';
  let h12 = h % 12; if (h12 === 0) h12 = 12;
  return ap + ' ' + h12 + ':' + pad(m);
}
function fmtDur(sec) {
  if (sec === null || sec === undefined) return '-';
  const neg = sec < 0;
  sec = Math.abs(floorToMinuteSec(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return (neg ? '-' : '') + h + ':' + pad(m);
}
function overlap(a, b, ls, le) {
  return Math.max(0, Math.min(b, le) - Math.max(a, ls));
}
function workOnlySec(start, end, settings) {
  const e = Math.max(start, end);
  return Math.max(0, (e - start) - overlap(start, e, settings.lunchStart, settings.lunchEnd));
}
function endAfterWorkSec(start, work, settings) {
  let end = start + Math.max(0, work);
  for (let i = 0; i < 4; i++) {
    const next = start + Math.max(0, work) + overlap(start, end, settings.lunchStart, settings.lunchEnd);
    if (next === end) break;
    end = next;
  }
  return floorToMinuteSec(end);
}

/* ---------------- date helpers ---------------- */
function mondayOf(date) {
  const x = new Date(date);
  x.setHours(0, 0, 0, 0);
  const day = (x.getDay() + 6) % 7; // 월=0 ... 일=6
  x.setDate(x.getDate() - day);
  return x;
}
function ymd(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
function addDays(d, n) { const x = new Date(d); x.setDate(x.getDate() + n); return x; }

function nowSec() {
  const n = new Date();
  return floorToMinuteSec((n.getHours() * 60 + n.getMinutes()) * 60 + n.getSeconds());
}
function todayInfo() {
  const now = new Date();
  const mon = mondayOf(now);
  const idx = (now.getDay() + 6) % 7; // 0..6 (월..일)
  return { mondayKey: ymd(mon), dayIndex: idx, dayKey: idx < 5 ? DAYS[idx][0] : null };
}

/* ---------------- state ---------------- */
function defaultState() {
  return {
    settings: { dailyTarget: 28800, halfTarget: 14400, lunchStart: 43200, lunchEnd: 46800, weeklyTarget: 144000, defaultIn: '09:00' },
    weeks: {},
  };
}
function shownMondayKey() {
  return ymd(addDays(mondayOf(new Date()), weekOffset * 7));
}
function weekData(mondayKey) {
  if (!state.weeks[mondayKey]) {
    const wk = {};
    for (const [k] of DAYS) wk[k] = { type: '', in: '', out: '' };
    state.weeks[mondayKey] = wk;
  }
  // 누락 키 보정
  for (const [k] of DAYS) if (!state.weeks[mondayKey][k]) state.weeks[mondayKey][k] = { type: '', in: '', out: '' };
  return state.weeks[mondayKey];
}

// 화면 표시용: 분 단위로 내림 ('07:43:27' → '07:43')
function normalizeTimeValue(value) {
  const sec = parseTimeToSec(value);
  return sec === null ? '' : fmt24(floorToMinuteSec(sec));
}
// 저장용: 초까지 보존 ('07:43:27' → '07:43:27', 수동 입력은 ':00').
// EHR이 준 초 단위를 근무시간 계산에 써야 회사 공식 총계와 일치한다. 표시만 분으로 내림.
function fmtClock(sec) {
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return pad(h) + ':' + pad(m) + ':' + pad(s);
}
function normalizeClockValue(value) {
  const sec = parseTimeToSec(value);
  return sec === null ? '' : fmtClock(sec);
}

function normalizeStoredTimes() {
  state.settings.defaultIn = normalizeTimeValue(state.settings.defaultIn || defaultState().settings.defaultIn);
  const ti = todayInfo();
  const now = nowSec();
  Object.keys(state.weeks || {}).forEach(mondayKey => {
    const wk = state.weeks[mondayKey];
    for (const [key] of DAYS) {
      if (!wk[key]) continue;
      wk[key].in = normalizeClockValue(wk[key].in);
      wk[key].out = normalizeClockValue(wk[key].out);
      if (mondayKey === ti.mondayKey && key === ti.dayKey) {
        const outS = parseTimeToSec(wk[key].out);
        if (outS !== null && outS > now) wk[key].out = '';
      }
    }
  });
}

function scheduleSave() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(doSave, 400);
}
async function doSave() {
  try {
    if (window.pywebview && pywebview.api) await pywebview.api.save(state);
    else localStorage.setItem('worktime', JSON.stringify(state));
  } catch (e) { /* ignore */ }
}

/* ---------------- calculation ---------------- */
// 공휴일(8h 근무 인정)을 반영한 '유효 유형'. 사용자가 직접 유형을 안 고른 공휴일 → '공휴일'.
function effType(cell, dayStr) {
  if (holidayMap[dayStr]) return '공휴일';   // 공휴일은 무조건 8h 인정
  return cell.type;
}
function ecell(cell, dayStr) {
  const t = effType(cell, dayStr);
  return (t === cell.type) ? cell : Object.assign({}, cell, { type: t });
}

// 반차 인정 시간(크레딧). 오전/오후 반차 = 4h 자동 인정.
function creditSec(cell, settings) {
  return (cell.type === '오전반차' || cell.type === '오후반차') ? settings.halfTarget : 0;
}
// 하루 근무 목표. 반차도 하루 목표는 8h (4h 인정 + 4h 실근무).
function targetSec(cell, settings) {
  return settings.dailyTarget;
}
// end: 사용할 종료 시각(초). 미체크아웃 + 오늘이면 현재시각, 과거면 null.
function workedSec(cell, settings, end) {
  const t = cell.type;
  if (t === '연차' || t === '공휴일' || t === '휴일') return settings.dailyTarget;
  const credit = creditSec(cell, settings);            // 반차 4h 자동 인정
  const inS = parseTimeToSec(cell.in);
  let base = null;                                      // 실제 출퇴근으로 계산한 근무분
  if (inS !== null) {
    const outS = parseTimeToSec(cell.out);
    const e = (outS !== null) ? outS : end;
    if (e !== null) {
      const lunch = overlap(inS, e, settings.lunchStart, settings.lunchEnd);
      base = Math.max(0, (e - inS) - lunch);
    }
  }
  if (base === null && credit === 0) return null;
  return (base || 0) + credit;
}
// 종료시각 end(초)를 명시적으로 지정해 하루 근무(초)를 계산. 연차/휴일/반차 크레딧 포함.
function workedWith(cell, s, end) {
  const t = cell.type;
  if (t === '연차' || t === '공휴일' || t === '휴일') return s.dailyTarget;
  const credit = creditSec(cell, s);
  const inS = parseTimeToSec(cell.in);
  let base = null;
  if (inS !== null && end !== null) {
    const lunch = overlap(inS, end, s.lunchStart, s.lunchEnd);
    base = Math.max(0, (end - inS) - lunch);
  }
  if (base === null && credit === 0) return null;
  return (base || 0) + credit;
}

// 주간 누적(초).
//  mode 'now'  = '지금 이 순간까지 실제로 한 근무'만 (오늘은 현재시각까지, 미래/예정 날짜는 제외)
//  mode 'plan' = 입력한 퇴근시각까지 다 채웠을 때 (미래 예정·연차 포함)
function weeklySum(wk, s, mondayKey, now, mode) {
  const monday = new Date(mondayKey + 'T00:00:00');
  const todayStr = ymd(new Date());
  let total = 0;
  DAYS.forEach(([key], i) => {
    const dayStr = ymd(addDays(monday, i));
    const ec = ecell(wk[key], dayStr);                 // 공휴일 반영
    const outS = parseTimeToSec(ec.out);
    let end;
    if (dayStr < todayStr) {
      end = (outS !== null) ? outS : null;             // 과거: 기록된 퇴근까지
    } else if (dayStr === todayStr) {
      end = (mode === 'now')
        ? ((outS !== null) ? Math.min(outS, now) : now)
        : ((outS !== null) ? outS : now);              // 오늘
    } else {
      // 미래: 연차/반차/공휴일(확정)은 'now'에도 포함, 일반 근무 예정은 제외
      const isLeave = (ec.type === '연차' || ec.type === '오전반차' || ec.type === '오후반차' || ec.type === '공휴일' || ec.type === '휴일');
      if (mode === 'now' && !isLeave) return;
      end = (outS !== null) ? outS : null;             // 연차/반차/공휴일 또는 예정: 입력된 것만
    }
    const w = workedWith(ec, s, end);
    if (w) total += w;
  });
  return total;
}

function estimateCheckouts(wk, s, mondayKey, now) {
  const monday = new Date(mondayKey + 'T00:00:00');
  const todayStr = ymd(new Date());
  const weeklyTarget = s.weeklyTarget || 144000;
  let fixedTotal = 0;
  const pending = [];

  DAYS.forEach(([key], i) => {
    const dayStr = ymd(addDays(monday, i));
    const ec = ecell(wk[key], dayStr);
    const t = ec.type;
    const outS = parseTimeToSec(ec.out);
    const isFullOff = (t === '연차' || t === '공휴일' || t === '휴일');

    if (isFullOff) {
      fixedTotal += s.dailyTarget;
      return;
    }
    if (outS !== null) {
      const w = workedWith(ec, s, outS);
      if (w) fixedTotal += w;
      return;
    }

    const credit = creditSec(ec, s);
    if (credit) fixedTotal += credit;
    // 퇴근 없는 날을 예상 분배 대상에 포함: 오늘·미래는 물론, 과거라도 출근 기록이 있으면(퇴근 누락) 같이 나눈다.
    const hasIn = parseTimeToSec(ec.in) !== null;
    if (dayStr >= todayStr || hasIn) pending.push({ key, dayStr, cell: ec });
  });

  if (!pending.length) return {};

  const remaining = Math.max(0, weeklyTarget - fixedTotal);
  const daily = ceilToMinuteSec(remaining / pending.length);
  const defaultIn = parseTimeToSec(s.defaultIn);
  const result = {};

  pending.forEach(day => {
    const start = parseTimeToSec(day.cell.in);
    const startS = start !== null ? start : defaultIn;
    if (startS === null) return;

    const needed = Math.max(0, daily);
    const workedNow = day.dayStr === todayStr ? workOnlySec(startS, now, s) : 0;
    const out = workedNow >= needed ? now : endAfterWorkSec(startS, needed, s);
    result[day.key] = floorToMinuteSec(out);
  });

  return result;
}

// 잔여(초)를 셀에 표시. 음수면(40h 초과) 빨간 '+연장'.
function setRemainCell(id, diff) {
  const el = document.getElementById(id);
  if (!el) return;
  if (diff >= 0) {
    el.textContent = fmtDur(diff);
    el.classList.remove('ot');
  } else {
    el.textContent = '+' + fmtDur(-diff);
    el.classList.add('ot');
  }
}
function renderEstimatedCheckoutCells(estimates) {
  document.querySelectorAll('#rowEstOut td').forEach(td => {
    const value = estimates[td.dataset.day];
    td.textContent = value === undefined ? '' : fmt24(value);
    td.classList.toggle('muted', value === undefined);
  });
}

/* ---------------- render ---------------- */
function buildGrid() {
  const head = document.getElementById('headRow');
  head.innerHTML = '<th class="corner"></th>';
  for (const tr of ['rowType', 'rowIn', 'rowOut', 'rowWork', 'rowEstOut']) {
    const row = document.getElementById(tr);
    // 첫 번째 th(rowlabel)만 남기고 제거
    while (row.children.length > 1) row.removeChild(row.lastChild);
  }

  const mondayKey = shownMondayKey();
  const monday = new Date(mondayKey + 'T00:00:00');
  const ti = todayInfo();
  const isThisWeek = (mondayKey === ti.mondayKey);

  DAYS.forEach(([key, label], i) => {
    const date = addDays(monday, i);
    const dayStr = ymd(date);
    const hol = holidayMap[dayStr];                     // 공휴일 이름 or undefined
    const isToday = isThisWeek && ti.dayIndex === i;

    const th = document.createElement('th');
    th.innerHTML = label + '<span class="date">' + (date.getMonth() + 1) + '/' + date.getDate() + '</span>';
    if (hol) { th.classList.add('hol'); th.title = hol; }
    if (isToday) th.classList.add('today');
    head.appendChild(th);

    // type — 공휴일이면 빨간 이름 표시, 아니면 드롭다운
    const tdType = document.createElement('td');
    if (isToday) tdType.classList.add('today');
    if (hol) {
      const tag = document.createElement('div');
      tag.className = 'holtag';
      tag.textContent = hol;
      tag.title = hol + ' · 공휴일 (8시간 인정)';
      tdType.appendChild(tag);
    } else {
      const sel = document.createElement('select');
      sel.className = 'typesel';
      sel.dataset.day = key;
      TYPES.forEach(t => {
        const o = document.createElement('option');
        o.value = t; o.textContent = t === '' ? '—' : t;
        sel.appendChild(o);
      });
      tdType.appendChild(sel);
    }
    document.getElementById('rowType').appendChild(tdType);

    // in / out inputs
    for (const field of ['in', 'out']) {
      const td = document.createElement('td');
      if (isToday) td.classList.add('today');
      const inp = document.createElement('input');
      inp.className = 'cellinput' + (hol ? ' muted' : '');
      inp.dataset.day = key; inp.dataset.field = field;
      inp.placeholder = field === 'in' ? '출근' : '퇴근';
      if (hol) inp.disabled = true;
      td.appendChild(inp);
      document.getElementById(field === 'in' ? 'rowIn' : 'rowOut').appendChild(td);
    }

    // worked (read-only)
    const tdW = document.createElement('td');
    tdW.dataset.day = key;
    if (isToday) tdW.classList.add('today');
    document.getElementById('rowWork').appendChild(tdW);

    const tdEst = document.createElement('td');
    tdEst.dataset.day = key;
    if (isToday) tdEst.classList.add('today');
    document.getElementById('rowEstOut').appendChild(tdEst);
  });

  // bind events
  document.querySelectorAll('.typesel').forEach(sel => {
    sel.addEventListener('change', onCellChange);
  });
  document.querySelectorAll('.cellinput').forEach(inp => {
    inp.addEventListener('change', onCellChange);
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') { inp.blur(); } });
  });
}

function fillInputsFromState() {
  const wk = weekData(shownMondayKey());
  document.querySelectorAll('.typesel').forEach(sel => {
    const c = wk[sel.dataset.day];
    sel.value = c.type || '';
    applyTypeClass(sel);
    applyInputState(sel.dataset.day, c.type || '');
  });
  document.querySelectorAll('.cellinput').forEach(inp => {
    const c = wk[inp.dataset.day];
    inp.value = normalizeTimeValue(c[inp.dataset.field]);   // 표시는 분 (저장은 초 보존)
  });
  const defaultIn = document.getElementById('defaultIn');
  if (defaultIn) defaultIn.value = state.settings.defaultIn || '';
}

function applyTypeClass(sel) {
  sel.classList.remove('type-연차', 'type-오전반차', 'type-오후반차', 'type-휴일');
  if (sel.value) sel.classList.add('type-' + sel.value);
}

// 연차/휴일(종일 비근무)이면 출근/퇴근 입력을 막는다.
function applyInputState(day, type) {
  const off = (type === '연차' || type === '휴일');
  document.querySelectorAll('.cellinput[data-day="' + day + '"]').forEach(inp => {
    inp.disabled = off;
    inp.classList.toggle('muted', off);
  });
}

function onCellChange(e) {
  const el = e.target;
  const wk = weekData(shownMondayKey());
  const c = wk[el.dataset.day];
  if (el.classList.contains('typesel')) {
    c.type = el.value;
    applyTypeClass(el);
    applyInputState(el.dataset.day, el.value);
    // 오전반차 → 출근 13:00 자동 / 오후반차 → 퇴근 13:00 자동
    if (el.value === '오전반차' || el.value === '오후반차') {
      const field = el.value === '오전반차' ? 'in' : 'out';
      c[field] = '13:00';
      const inp = document.querySelector('.cellinput[data-day="' + el.dataset.day + '"][data-field="' + field + '"]');
      if (inp) inp.value = c[field];
    }
  } else {
    const norm = normalizeTimeValue(el.value);
    el.value = norm;
    c[el.dataset.field] = norm;
  }
  scheduleSave();
  recompute();
}

function onDefaultInChange(e) {
  const norm = normalizeTimeValue(e.target.value);
  e.target.value = norm;
  state.settings.defaultIn = norm;
  scheduleSave();
  recompute();
}

function recompute() {
  const s = state.settings;
  const mondayKey = shownMondayKey();
  const wk = weekData(mondayKey);
  const ti = todayInfo();
  const isThisWeek = (mondayKey === ti.mondayKey);
  const now = nowSec();

  // 근무 시간 셀
  document.querySelectorAll('#rowWork td').forEach(td => {
    const key = td.dataset.day;
    const idx = DAYS.findIndex(d => d[0] === key);
    const dayStr = ymd(addDays(new Date(mondayKey + 'T00:00:00'), idx));
    const c = ecell(wk[key], dayStr);                  // 공휴일 반영
    const isToday = isThisWeek && ti.dayIndex === idx;
    td.classList.remove('over', 'holiday');
    const end = isToday ? now : null;
    const w = workedSec(c, s, end);
    if (w === null) { td.textContent = ''; return; }
    td.textContent = fmtDur(w);
    if (w >= targetSec(c, s) && targetSec(c, s) > 0) td.classList.add('over');
  });

  // 요약 두 줄 (표시 중인 주, 월~금)
  const wTgt = s.weeklyTarget || 144000;
  const nowTotal = weeklySum(wk, s, mondayKey, now, 'now');   // 지금까지(미래·예정 제외)
  const planTotal = weeklySum(wk, s, mondayKey, now, 'plan'); // 예정 포함(입력 퇴근시각)
  const estimates = isThisWeek ? estimateCheckouts(wk, s, mondayKey, now) : {};

  // 1줄: 지금까지 — 현재 시각 기준
  document.getElementById('sNow').textContent = fmtKor(now);
  setRemainCell('sRemainNow', wTgt - nowTotal);
  document.getElementById('sCumNow').textContent = fmtDur(nowTotal);

  // 2줄: 예정 포함 — 입력한 퇴근시간 기준 (주 40h)
  document.getElementById('sCumPlan').textContent = fmtDur(planTotal);
  setRemainCell('sRemainPlan', wTgt - planTotal);
  document.getElementById('sTarget').textContent = fmtDur(wTgt);
  renderEstimatedCheckoutCells(estimates);
}

/* ---------------- EHR ---------------- */
let ehrNeedsLogin = false;

function setEhrBtn(label, disabled) {
  const btn = document.getElementById('ehrBtn');
  if (!btn) return;
  if (label != null) btn.textContent = label;
  if (disabled != null) btn.disabled = disabled;
}

async function refreshEhr(manual) {
  const status = document.getElementById('statusLine');
  status.className = 'status';
  status.textContent = 'EHR 조회 중…';
  setEhrBtn(null, true);
  let res = null;
  try {
    if (window.pywebview && pywebview.api && pywebview.api.fetch_ehr) {
      res = await pywebview.api.fetch_ehr();
    } else {
      res = { status: 'not_configured' };
    }
  } catch (e) {
    res = { status: 'error', message: String(e) };
  }
  setEhrBtn(null, false);

  if (!res || res.status === 'not_configured') {
    status.className = 'status';
    status.textContent = 'EHR 연동 준비 중 (수동 입력은 정상 동작)';
    return;
  }
  if (res.status === 'login_required') {
    ehrNeedsLogin = true;
    setEhrBtn('EHR 로그인', false);
    status.className = 'status err';
    status.textContent = 'EHR 로그인이 필요해요 — ‘EHR 로그인’ 클릭';
    return;
  }
  if (res.status === 'error') {
    status.className = 'status err';
    status.textContent = 'EHR 오류: ' + (res.message || '알 수 없음');
    return;
  }
  // ok — res.records: { 'YYYY-MM-DD': { in, out } } (과거+오늘만, 미래는 미포함)
  ehrNeedsLogin = false;
  setEhrBtn('로그인', false);
  const recs = res.records || {};
  let n = 0;
  for (const dateStr of Object.keys(recs)) {
    const d = new Date(dateStr + 'T00:00:00');
    const mk = ymd(mondayOf(d));
    const idx = (d.getDay() + 6) % 7;
    if (idx > 4) continue;
    const wk = weekData(mk);
    const key = DAYS[idx][0];
    if (recs[dateStr].in) wk[key].in = normalizeClockValue(recs[dateStr].in);
    if (recs[dateStr].out) {
      const out = normalizeClockValue(recs[dateStr].out);
      const outS = parseTimeToSec(out);
      const isToday = dateStr === ymd(new Date());
      if (isToday && outS !== null && outS > nowSec()) wk[key].out = '';
      else wk[key].out = out;
    }
    n++;
  }
  await doSave();
  fillInputsFromState();
  recompute();
  status.className = 'status ok';
  status.textContent = 'EHR 반영 완료 (' + n + '일)';
}

async function doEhrLogin() {
  const status = document.getElementById('statusLine');
  status.className = 'status';
  status.textContent = '로그인 창에서 로그인하세요…';
  setEhrBtn('로그인 중…', true);
  let res = null;
  try {
    if (window.pywebview && pywebview.api && pywebview.api.ehr_login) {
      res = await pywebview.api.ehr_login();
    } else {
      res = { status: 'error', message: '데스크톱 앱에서만 가능' };
    }
  } catch (e) {
    res = { status: 'error', message: String(e) };
  }
  setEhrBtn(null, false);
  if (res && res.status === 'ok') {
    status.className = 'status ok';
    status.textContent = '로그인 완료 — 근태 불러오는 중…';
    refreshEhr(true);
  } else if (res && res.status === 'cancelled') {
    status.className = 'status';
    status.textContent = '로그인이 취소됐어요';
    setEhrBtn('EHR 로그인', false);
  } else {
    status.className = 'status err';
    status.textContent = '로그인 오류: ' + ((res && res.message) || '알 수 없음');
    setEhrBtn('EHR 로그인', false);
  }
}

function ehrButtonClick() {
  if (ehrNeedsLogin) doEhrLogin();
  else refreshEhr(true);
}

window.appRefreshEhr = function () { refreshEhr(false); };

/* ---------------- init ---------------- */
async function loadState() {
  let loaded = null;
  try {
    if (window.pywebview && pywebview.api) loaded = await pywebview.api.load();
    else loaded = JSON.parse(localStorage.getItem('worktime') || 'null');
  } catch (e) { loaded = null; }
  state = loaded && loaded.settings ? loaded : defaultState();
  if (!state.weeks) state.weeks = {};
  if (!state.settings) state.settings = defaultState().settings;
  state.settings = Object.assign({}, defaultState().settings, state.settings);
  normalizeStoredTimes();
  await doSave();
}

async function loadHolidays() {
  const y = new Date().getFullYear();
  try {
    if (window.pywebview && pywebview.api && pywebview.api.holidays) {
      holidayMap = (await pywebview.api.holidays([y - 1, y, y + 1])) || {};
    }
  } catch (e) { holidayMap = {}; }
}

function updateWeekLabel() {
  const mk = shownMondayKey();
  const monday = new Date(mk + 'T00:00:00');
  const sun = addDays(monday, 6);
  const label = (weekOffset === 0 ? '이번 주 · ' : '') +
    (monday.getMonth() + 1) + '/' + monday.getDate() + ' ~ ' + (sun.getMonth() + 1) + '/' + sun.getDate();
  document.getElementById('weekLabel').textContent = label;
}

function rerenderWeek() {
  buildGrid();
  fillInputsFromState();
  updateWeekLabel();
  recompute();
}

async function init() {
  if (started) return;
  started = true;
  await loadState();
  await loadHolidays();
  rerenderWeek();

  document.getElementById('prevWeek').addEventListener('click', () => { weekOffset--; rerenderWeek(); });
  document.getElementById('nextWeek').addEventListener('click', () => { weekOffset++; rerenderWeek(); });
  document.getElementById('ehrBtn').addEventListener('click', ehrButtonClick);
  const defaultIn = document.getElementById('defaultIn');
  if (defaultIn) {
    defaultIn.addEventListener('change', onDefaultInChange);
    defaultIn.addEventListener('keydown', e => { if (e.key === 'Enter') defaultIn.blur(); });
  }

  setInterval(recompute, 1000);

  // 앱 켤 때 자동 EHR 조회
  refreshEhr(false);
}

if (window.pywebview) {
  window.addEventListener('pywebviewready', init);
} else {
  window.addEventListener('pywebviewready', init);
  window.addEventListener('DOMContentLoaded', () => setTimeout(init, 300));
}
