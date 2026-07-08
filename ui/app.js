/* 근태 — frontend logic */

const DAYS = [
  ['mon', '월'], ['tue', '화'], ['wed', '수'], ['thu', '목'], ['fri', '금'],
];
const TYPES = ['', '연차', '오전반차', '오후반차', '휴일'];
// TODO: '출장' 유형 검토(보류) — 근무시간이 사람마다 달라 하루 8h 초과도 가능.
//   유력안: 출퇴근 자유 입력(EHR도 채움) + 비어 있으면 8h 인정. 확정 후 구현.

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
    settings: { dailyTarget: 28800, halfTarget: 14400, lunchStart: 43200, lunchEnd: 46800, weeklyTarget: 144000, defaultIn: '09:00', theme: 'dark' },
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

// 반차의 '쉬는 쪽' 경계만 13:00으로 고정·잠금. '일하는 쪽'은 자유(직접 입력 + EHR 실제값).
//  오전반차 = 오전 휴무 → 출근 13:00 고정 / 퇴근은 자유
//  오후반차 = 오후 휴무 → 퇴근 13:00 고정 / 출근은 자유
function halfdayFixed(type) {
  if (type === '오전반차') return { field: 'in', value: '13:00' };
  if (type === '오후반차') return { field: 'out', value: '13:00' };
  return null;
}

// 화면 표시용: 분 단위로 내림 ('07:43:27' → '07:43')
function normalizeTimeValue(value) {
  const sec = parseTimeToSec(value);
  return sec === null ? '' : fmt24(floorToMinuteSec(sec));
}
// 시:분:초 포맷터 (저장 형식 HH:MM:SS).
function fmtClock(sec) {
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return pad(h) + ':' + pad(m) + ':' + pad(s);
}
// 저장용: 분 단위로 내려 저장 ('07:43:27' → '07:43:00').
// EHR 공식 총계가 출퇴근을 '분 단위로 자른 뒤' 계산하므로, 우리도 분으로 내려야 값이 일치한다.
function normalizeClockValue(value) {
  const sec = parseTimeToSec(value);
  return sec === null ? '' : fmtClock(floorToMinuteSec(sec));
}

function normalizeStoredTimes() {
  state.settings.defaultIn = normalizeTimeValue(state.settings.defaultIn || defaultState().settings.defaultIn);
  Object.keys(state.weeks || {}).forEach(mondayKey => {
    const wk = state.weeks[mondayKey];
    for (const [key] of DAYS) {
      if (!wk[key]) continue;
      wk[key].in = normalizeClockValue(wk[key].in);
      wk[key].out = normalizeClockValue(wk[key].out);
      // 반차의 고정 경계(쉬는 쪽)만 강제. 일하는 쪽은 그대로 둠.
      const fx = halfdayFixed(wk[key].type);
      if (fx) wk[key][fx.field] = normalizeClockValue(fx.value);
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

/* ---------------- theme ---------------- */
// 다크(기본) ↔ 엑셀(스프레드시트) 테마. <html data-theme>로 CSS 변수 세트를 교체한다.
function applyTheme(theme) {
  const t = (theme === 'excel') ? 'excel' : 'dark';
  document.documentElement.setAttribute('data-theme', t);
  const btn = document.getElementById('themeBtn');
  if (btn) btn.textContent = (t === 'excel') ? '다크' : '엑셀';   // 누르면 갈 테마를 라벨로
}
function toggleTheme() {
  const next = (state.settings.theme === 'excel') ? 'dark' : 'excel';
  state.settings.theme = next;
  applyTheme(next);
  scheduleSave();
}

/* ---------------- formula bar (엑셀 테마 장식) ---------------- */
// 셀 주소: 열 B~F = 월~금(A는 라벨열), 행 2=유형 3=출근 4=퇴근.
function cellRef(day, field) {
  const idx = DAYS.findIndex(d => d[0] === day);
  if (idx < 0) return '';
  const col = String.fromCharCode(66 + idx);   // B..F
  const row = field === 'type' ? 2 : field === 'in' ? 3 : field === 'out' ? 4 : '';
  return col + row;
}
function updateFormulaBar(day, field, value) {
  const r = document.getElementById('fbRefText');
  const v = document.getElementById('fbVal');
  if (r) r.textContent = cellRef(day, field);
  if (v) v.textContent = value || '';
}
function bindFormulaBar() {
  const grid = document.getElementById('grid');
  if (!grid) return;
  const onFocus = e => {
    const el = e.target;
    if (!el.classList) return;
    if (el.classList.contains('cellinput')) updateFormulaBar(el.dataset.day, el.dataset.field, el.value);
    else if (el.classList.contains('typesel')) updateFormulaBar(el.dataset.day, 'type', el.value || '—');
  };
  grid.addEventListener('focusin', onFocus);
  grid.addEventListener('input', onFocus);
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
  head.innerHTML = '<th class="snum">1</th><th class="corner"></th>';   // snum = 엑셀 테마의 행번호 거터
  for (const tr of ['rowType', 'rowIn', 'rowOut', 'rowWork', 'rowEstOut']) {
    const row = document.getElementById(tr);
    // 앞쪽 고정 th(행번호 + rowlabel) 2개만 남기고 제거
    while (row.children.length > 2) row.removeChild(row.lastChild);
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

// 연차/휴일은 출근·퇴근 둘 다 잠금. 반차는 '고정 경계'(쉬는 쪽) 1칸만 잠그고 나머지는 입력 허용.
function applyInputState(day, type) {
  const bothOff = (type === '연차' || type === '휴일');
  const fx = halfdayFixed(type);
  document.querySelectorAll('.cellinput[data-day="' + day + '"]').forEach(inp => {
    const off = bothOff || (fx && inp.dataset.field === fx.field);
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
    // 반차 → 쉬는 쪽 경계만 13:00 고정 (일하는 쪽은 자유)
    const fx = halfdayFixed(el.value);
    if (fx) {
      c[fx.field] = fx.value;
      const inp = document.querySelector('.cellinput[data-day="' + el.dataset.day + '"][data-field="' + fx.field + '"]');
      if (inp) inp.value = fx.value;
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
    setEhrBtn('로그인', false);
    status.className = 'status err';
    status.textContent = 'EHR 로그인이 필요해요 — ‘로그인’ 클릭';
    return;
  }
  if (res.status === 'error') {
    status.className = 'status err';
    status.textContent = 'EHR 오류: ' + (res.message || '알 수 없음');
    return;
  }
  // ok — res.records: { 'YYYY-MM-DD': { in, out } } (과거+오늘만, 미래는 미포함)
  ehrNeedsLogin = false;
  setEhrBtn('새로고침', false);   // 로그인됨 → 다시 누르면 재동기화(refresh)
  const recs = res.records || {};
  for (const dateStr of Object.keys(recs)) {
    const d = new Date(dateStr + 'T00:00:00');
    const mk = ymd(mondayOf(d));
    const idx = (d.getDay() + 6) % 7;
    if (idx > 4) continue;
    const wk = weekData(mk);
    const key = DAYS[idx][0];
    const fx = halfdayFixed(wk[key].type);   // 반차 고정 경계는 EHR로 안 덮음(자유 경계만 채움)
    if (recs[dateStr].in && !(fx && fx.field === 'in')) wk[key].in = normalizeClockValue(recs[dateStr].in);
    if (recs[dateStr].out && !(fx && fx.field === 'out')) {
      const out = normalizeClockValue(recs[dateStr].out);
      const outS = parseTimeToSec(out);
      const isToday = dateStr === ymd(new Date());
      // 오늘인데 EHR 퇴근이 미래(이상치)면 무시하고 기존 입력 유지, 그 외엔 실제값으로 덮어씀
      if (!(isToday && outS !== null && outS > nowSec())) wk[key].out = out;
    }
  }
  await doSave();
  fillInputsFromState();
  recompute();
  status.className = 'status ok';
  status.textContent = 'EHR 반영 완료 (최근 2개월)';
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
    setEhrBtn('로그인', false);
  } else {
    status.className = 'status err';
    status.textContent = '로그인 오류: ' + ((res && res.message) || '알 수 없음');
    setEhrBtn('로그인', false);
  }
}

function ehrButtonClick() {
  if (ehrNeedsLogin) doEhrLogin();
  else refreshEhr(true);
}

window.appRefreshEhr = function () { refreshEhr(false); };

/* ---------------- 화면 전환 (근무 / 식단 / 캘린더) ---------------- */
// 한 창 안에서 근무·식단·캘린더 화면을 서로 배타적으로 전환한다.
let viewMode = 'work';   // 'work' | 'meal' | 'cal'
let mealCacheLoaded = false;

function setView(mode) {
  viewMode = mode;
  const wrap = document.querySelector('.wrap');
  if (wrap) {
    wrap.classList.toggle('meal-mode', mode === 'meal');
    wrap.classList.toggle('cal-mode', mode === 'cal');
  }
  const mb = document.getElementById('mealBtn');
  const cb = document.getElementById('calBtn');
  if (mb) mb.textContent = mode === 'meal' ? '근무' : '식단';
  if (cb) cb.textContent = mode === 'cal' ? '근무' : '캘린더';
}

function toggleMeal() {
  setView(viewMode === 'meal' ? 'work' : 'meal');
  if (viewMode === 'meal' && !mealCacheLoaded) {
    mealCacheLoaded = true;
    loadMealCache();   // 저장된 게 있으면 즉시 표시 (네트워크 X)
  }
}

// 이번 주 판정은 백엔드(meal.py)가 작성일 기준으로 하고, 여기선 안내에 최신 글 날짜만 덧붙인다.
function mealLatestNote(createdAt) {
  if (!createdAt) return '';
  const d = new Date(createdAt);
  return isNaN(d.getTime()) ? '' : ' (최신 글: ' + (d.getMonth() + 1) + '/' + d.getDate() + ')';
}

function mealCaptionText(res) {
  let s = res.title || '주간식단표';
  if (res.createdAt) {
    const d = new Date(res.createdAt);
    if (!isNaN(d.getTime())) s += ' · ' + (d.getMonth() + 1) + '/' + d.getDate() + ' 게시';
  }
  if (res.cached) s += ' · 저장본';
  return s;
}

function renderMeal(res) {
  const img = document.getElementById('mealImg');
  const hint = document.getElementById('mealHint');
  const cap = document.getElementById('mealCaption');
  const origin = document.getElementById('mealOrigin');
  cap.textContent = '';
  origin.hidden = true;
  const show = msg => { img.hidden = true; hint.hidden = false; hint.textContent = msg; };

  if (!res || res.status === 'empty') { show('저장된 식단이 없어요 — ‘불러오기’를 눌러주세요.'); return; }
  if (res.status === 'login_required') { show('EHR 로그인이 필요해요 — 상단 ‘로그인’ 후 다시 시도하세요.'); return; }
  if (res.status === 'not_yet') {
    show('아직 이번 주 식단표가 안 올라왔어요 — 잠시 후 ‘불러오기’로 다시 시도해주세요.' + mealLatestNote(res.latestCreatedAt));
    if (res.boardUrl) { origin.hidden = false; origin.dataset.url = res.boardUrl; }
    return;
  }
  if (res.status === 'ok' && res.image) { img.src = res.image; img.hidden = false; hint.hidden = true; }
  else if (res.status === 'no_image') { show('본문에 이미지가 없어요 — ‘원본 열기’로 확인하세요.'); }
  else if (res.status === 'error') { show('불러오기 실패: ' + (res.message || '알 수 없음')); }
  else { show('식단을 표시할 수 없어요.'); return; }

  cap.textContent = mealCaptionText(res);
  if (res.boardUrl) { origin.hidden = false; origin.dataset.url = res.boardUrl; }
}

async function loadMealCache() {
  let res = null;
  try {
    if (window.pywebview && pywebview.api && pywebview.api.load_meal) res = await pywebview.api.load_meal();
  } catch (e) { res = null; }
  renderMeal(res || { status: 'empty' });
}

function setMealBusy(busy) {
  const btn = document.getElementById('mealReload');
  if (btn) { btn.disabled = busy; btn.textContent = busy ? '불러오는 중…' : '불러오기'; }
}

async function reloadMeal() {
  setMealBusy(true);
  const img = document.getElementById('mealImg');
  const hint = document.getElementById('mealHint');
  if (img.hidden) { hint.hidden = false; hint.textContent = '게시판에서 식단표 가져오는 중…'; }
  let res = null;
  try {
    if (window.pywebview && pywebview.api && pywebview.api.fetch_meal) res = await pywebview.api.fetch_meal();
    else res = { status: 'error', message: '데스크톱 앱에서만 가능' };
  } catch (e) { res = { status: 'error', message: String(e) }; }
  setMealBusy(false);
  renderMeal(res);
}

function openMealOrigin(e) {
  e.preventDefault();
  const url = e.currentTarget.dataset.url;
  if (url && window.pywebview && pywebview.api && pywebview.api.open_url) pywebview.api.open_url(url);
}

/* ---------------- 캘린더 (그룹웨어 일정) ---------------- */
// 다우오피스 캘린더 색상 팔레트(번호->hex). 백엔드 cal.py PALETTE 와 동일 (프론트 CSS .txtcolorN 추출).
const CAL_PALETTE = {
  '0': '#a3a3a3', '1': '#905341', '2': '#d06b64', '3': '#d75269', '4': '#fa573c',
  '5': '#ff7537', '6': '#ffad46', '7': '#42d692', '8': '#16a765', '9': '#7bd148',
  '10': '#b3dc6c', '11': '#fbe983', '12': '#fad165', '13': '#f691b2', '14': '#cd74e6',
  '15': '#9a9cff', '16': '#b99aff', '17': '#6691e5', '18': '#9fc6e7',
};
const CAL_MAX_CHIPS = 4;          // 하루 셀에 보일 최대 일정 수 (초과 시 '+N')

let calMonth = null;              // {y, m} — 표시 중인 달(1일 기준)
let calCalendars = [];            // [{id,label,color,type,mine,...}]
let calEvents = [];               // [{id,calendarId,color,type,summary,start,end,allday,...}]
let calSelected = null;           // Set<calendarId> — 체크된(표시할) 캘린더. null=아직 미초기화
let calLoadedOnce = false;
let calBoardUrl = null;
let calFetchTimer = null;         // 월 이동 디바운스 타이머
let calReqSeq = 0;                // 조회 순번(스테일 결과 폐기용)
let calInFlight = false;          // 조회 진행 중(브라우저 프로세스 중복 방지)
let calRefetchWanted = false;     // 진행 중에 들어온 요청 → 끝난 뒤 한 번 더

function calMonthKey(mm) { return mm.y + '-' + pad(mm.m); }
function calCurrentMonth() { const n = new Date(); return { y: n.getFullYear(), m: n.getMonth() + 1 }; }
function calShiftMonth(mm, delta) {
  const d = new Date(mm.y, mm.m - 1 + delta, 1);
  return { y: d.getFullYear(), m: d.getMonth() + 1 };
}
// 색번호 -> hex (텍스트 대비용은 CSS에서 처리)
function calColor(n) { return CAL_PALETTE[String(n)] || CAL_PALETTE['0']; }

// 일요일 시작 월 그리드 날짜 배열(42/35칸). 백엔드 _grid_range 와 동일 규칙.
function calGridDates(mm) {
  const first = new Date(mm.y, mm.m - 1, 1);
  const start = addDays(first, -first.getDay());          // 직전(당일) 일요일
  const last = new Date(mm.y, mm.m, 0);                   // 이번 달 말일
  const end = addDays(last, 6 - last.getDay());           // 직후(당일) 토요일
  const dates = [];
  for (let d = new Date(start); d <= end; d = addDays(d, 1)) dates.push(new Date(d));
  return dates;
}

// 일정이 해당 날짜(YYYY-MM-DD)에 걸치는지. 시작~종료(둘 다 날짜 기준, 종료 포함).
function calEventOnDate(ev, dayStr) {
  const s = (ev.start || '').slice(0, 10);
  if (!s) return false;
  let e = (ev.end || '').slice(0, 10) || s;
  if (e < s) e = s;
  return dayStr >= s && dayStr <= e;
}

function calSelectedIds() {
  return calSelected ? Array.from(calSelected) : calCalendars.map(c => c.id);
}

// 저장된 선택 상태를 반영해 calSelected 초기화(없으면 전체 선택).
function calInitSelection() {
  const saved = state.settings.calSelected;
  const allIds = calCalendars.map(c => c.id);
  if (Array.isArray(saved)) {
    calSelected = new Set(saved.filter(id => allIds.includes(id)));
  } else {
    calSelected = new Set(allIds);   // 기본: 모두 표시
  }
}

function calPersistSelection() {
  state.settings.calSelected = calSelectedIds();
  scheduleSave();
}

function setCalStatus(msg, cls) {
  const el = document.getElementById('calStatus');
  if (!el) return;
  el.textContent = msg || '';
  el.className = 'calstatus' + (cls ? ' ' + cls : '');
}

function setCalBusy(busy) {
  const btn = document.getElementById('calReload');
  if (btn) { btn.disabled = busy; btn.textContent = busy ? '불러오는 중…' : '불러오기'; }
}

function updateCalLabel() {
  const el = document.getElementById('calLabel');
  if (el) el.textContent = calMonth.y + '년 ' + calMonth.m + '월';
  const today = document.getElementById('calToday');
  const cur = calCurrentMonth();
  if (today) today.disabled = (calMonth.y === cur.y && calMonth.m === cur.m);
}

// 체크박스(캘린더별 표시 토글). 색 점 + 라벨.
function renderCalLegend() {
  const box = document.getElementById('calLegend');
  if (!box) return;
  box.innerHTML = '';
  if (!calCalendars.length) return;
  calCalendars.forEach(c => {
    const id = 'calchk_' + c.id;
    const wrap = document.createElement('label');
    wrap.className = 'callegitem' + (c.type === 'holiday' ? ' holiday' : '');
    wrap.htmlFor = id;

    const chk = document.createElement('input');
    chk.type = 'checkbox';
    chk.id = id;
    chk.className = 'callegchk';
    chk.checked = calSelected.has(c.id);
    chk.addEventListener('change', () => {
      if (chk.checked) calSelected.add(c.id); else calSelected.delete(c.id);
      calPersistSelection();
      renderCalGrid();
    });

    const dot = document.createElement('span');
    dot.className = 'callegdot';
    dot.style.background = (c.type === 'holiday') ? 'var(--red)' : calColor(c.color);

    const txt = document.createElement('span');
    txt.className = 'calleglabel';
    txt.textContent = c.label;
    txt.title = c.label + (c.mine ? '' : (c.ownerName ? ' (' + c.ownerName + ')' : ''));

    wrap.appendChild(chk); wrap.appendChild(dot); wrap.appendChild(txt);
    box.appendChild(wrap);
  });
}

function calChip(ev) {
  const chip = document.createElement('div');
  const isHol = ev.type === 'holiday';
  chip.className = 'calchip' + (isHol ? ' holiday' : (ev.allday ? ' allday' : ''));
  if (isHol) {
    chip.textContent = ev.summary;
  } else if (ev.allday) {
    chip.style.background = calColor(ev.color);
    chip.textContent = ev.summary;
  } else {
    const dot = document.createElement('span');
    dot.className = 'calchipdot';
    dot.style.background = calColor(ev.color);
    const t = document.createElement('span');
    t.className = 'calchiptime';
    t.textContent = (ev.start || '').slice(11, 16);
    chip.appendChild(dot); chip.appendChild(t);
    chip.appendChild(document.createTextNode(' ' + ev.summary));
  }
  const who = ev.calendarName ? ' · ' + ev.calendarName : '';
  chip.title = (ev.allday || isHol ? '' : (ev.start || '').slice(11, 16) + ' ') + ev.summary + who;
  chip.addEventListener('click', () => {
    if (calBoardUrl && window.pywebview && pywebview.api && pywebview.api.open_url) pywebview.api.open_url(calBoardUrl);
  });
  return chip;
}

function renderCalGrid() {
  const grid = document.getElementById('calGrid');
  if (!grid || !calMonth) return;
  grid.innerHTML = '';
  const dates = calGridDates(calMonth);
  grid.style.setProperty('--calrows', String(dates.length / 7));
  const todayStr = ymd(new Date());
  const sel = calSelected || new Set(calCalendars.map(c => c.id));

  // 표시할 일정만: 선택된 캘린더 + 그리드 범위
  const visible = calEvents.filter(ev => sel.has(ev.calendarId));

  dates.forEach(d => {
    const dayStr = ymd(d);
    const dow = d.getDay();                       // 0=일 .. 6=토
    const inMonth = (d.getMonth() + 1 === calMonth.m && d.getFullYear() === calMonth.y);

    const dayEvents = visible.filter(ev => calEventOnDate(ev, dayStr));
    dayEvents.sort((a, b) => {
      const ah = a.type === 'holiday' ? 0 : (a.allday ? 1 : 2);
      const bh = b.type === 'holiday' ? 0 : (b.allday ? 1 : 2);
      if (ah !== bh) return ah - bh;
      return (a.start || '').localeCompare(b.start || '');
    });
    const isHoliday = dayEvents.some(ev => ev.type === 'holiday');

    const cell = document.createElement('div');
    cell.className = 'calday';
    if (!inMonth) cell.classList.add('other');
    if (dayStr === todayStr) cell.classList.add('today');
    if (dow === 0 || isHoliday) cell.classList.add('sun');
    else if (dow === 6) cell.classList.add('sat');

    const num = document.createElement('div');
    num.className = 'caldaynum';
    num.textContent = d.getDate();
    cell.appendChild(num);

    const list = document.createElement('div');
    list.className = 'caldayevents';
    const shown = dayEvents.slice(0, CAL_MAX_CHIPS);
    shown.forEach(ev => list.appendChild(calChip(ev)));
    if (dayEvents.length > shown.length) {
      const more = document.createElement('div');
      more.className = 'calmore';
      more.textContent = '+' + (dayEvents.length - shown.length) + ' 더';
      more.addEventListener('click', () => {
        if (calBoardUrl && window.pywebview && pywebview.api && pywebview.api.open_url) pywebview.api.open_url(calBoardUrl);
      });
      list.appendChild(more);
    }
    cell.appendChild(list);
    grid.appendChild(cell);
  });
}

function applyCalResult(res) {
  if (!res) return false;
  if (res.status === 'login_required') {
    setCalStatus('EHR 로그인이 필요해요 — 상단 ‘로그인’ 후 다시 시도하세요.', 'err');
    return false;
  }
  if (res.status === 'error') {
    setCalStatus('불러오기 실패: ' + (res.message || '알 수 없음'), 'err');
    return false;
  }
  if (res.status !== 'ok') return false;
  const known = new Set(calCalendars.map(c => c.id));
  calCalendars = res.calendars || [];
  calEvents = res.events || [];
  calBoardUrl = res.boardUrl || calBoardUrl;
  if (calCalendars.length) {
    if (!calSelected) {
      calInitSelection();               // 첫 로드: 저장된 선택 or 전체
    } else {
      // 이후 로드: 새로 나타난(이전에 없던) 캘린더는 기본 표시로 추가
      calCalendars.forEach(c => { if (!known.has(c.id)) calSelected.add(c.id); });
    }
  }
  renderCalLegend();
  renderCalGrid();
  setCalStatus(res.cached ? '저장본 표시 중…' : '캘린더 반영 완료', res.cached ? '' : 'ok');
  return true;
}

async function loadCalCache() {
  const month = calMonthKey(calMonth);
  let res = null;
  try {
    if (window.pywebview && pywebview.api && pywebview.api.load_calendar) {
      res = await pywebview.api.load_calendar(month);
    }
  } catch (e) { res = null; }
  // 캐시를 읽는 동안 다른 달로 옮겼으면 반영하지 않음
  if (res && res.status === 'ok' && month === calMonthKey(calMonth)) applyCalResult(res);
}

// 월 이동 연타 시 마지막에 멈춘 달만 조회하도록 디바운스.
function scheduleCalFetch(delay) {
  if (calFetchTimer) clearTimeout(calFetchTimer);
  calFetchTimer = setTimeout(() => { calFetchTimer = null; fetchCal(); }, delay);
}

// 한 번에 하나의 조회만 실행(headless 브라우저 프로세스 중복 방지).
// 조회 중 다른 요청이 오면 끝난 뒤 한 번 더, 표시 중인 달의 결과만 반영(스테일 폐기).
async function fetchCal() {
  if (calInFlight) { calRefetchWanted = true; return; }
  const month = calMonthKey(calMonth);
  const seq = ++calReqSeq;
  calInFlight = true;
  setCalBusy(true);
  if (!calCalendars.length) setCalStatus('캘린더 불러오는 중…', '');
  let res = null;
  try {
    if (window.pywebview && pywebview.api && pywebview.api.fetch_calendar) {
      // 전체 캘린더를 받아오고, 표시 여부는 체크박스로 거른다(재조회 없이 즉시 토글).
      res = await pywebview.api.fetch_calendar(month, null);
    } else {
      res = { status: 'error', message: '데스크톱 앱에서만 가능' };
    }
  } catch (e) { res = { status: 'error', message: String(e) }; }
  calInFlight = false;
  setCalBusy(false);
  // 그새 다른 달로 이동했으면 이 결과는 버린다(잘못된 달 표시/깜빡임 방지)
  if (seq !== calReqSeq || month !== calMonthKey(calMonth)) {
    if (calRefetchWanted) { calRefetchWanted = false; scheduleCalFetch(0); }
    return;
  }
  applyCalResult(res);
  if (calRefetchWanted) { calRefetchWanted = false; scheduleCalFetch(0); }
}

function enterCal() {
  if (!calMonth) calMonth = calCurrentMonth();
  updateCalLabel();
  if (!calLoadedOnce) {
    calLoadedOnce = true;
    loadCalCache();          // 캐시 있으면 즉시 표시
    scheduleCalFetch(0);     // 곧바로 최신 조회
  }
}

function toggleCal() {
  setView(viewMode === 'cal' ? 'work' : 'cal');
  if (viewMode === 'cal') enterCal();
}

function calGoMonth(mm) {
  calMonth = mm;
  updateCalLabel();
  calEvents = [];                 // 이전 달 잔상 제거
  renderCalGrid();
  loadCalCache();                 // 해당 달 캐시 있으면 즉시 표시
  scheduleCalFetch(350);          // 연타가 멈춘 뒤에 한 번만 최신 조회
}

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
  const todayBtn = document.getElementById('todayBtn');
  if (todayBtn) todayBtn.disabled = (weekOffset === 0);   // 이번 주면 비활성
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
  applyTheme(state.settings.theme);
  await loadHolidays();
  rerenderWeek();

  document.getElementById('prevWeek').addEventListener('click', () => { weekOffset--; rerenderWeek(); });
  document.getElementById('nextWeek').addEventListener('click', () => { weekOffset++; rerenderWeek(); });
  document.getElementById('todayBtn').addEventListener('click', () => { weekOffset = 0; rerenderWeek(); });
  document.getElementById('ehrBtn').addEventListener('click', ehrButtonClick);
  document.getElementById('themeBtn').addEventListener('click', toggleTheme);
  document.getElementById('mealBtn').addEventListener('click', toggleMeal);
  document.getElementById('mealReload').addEventListener('click', reloadMeal);
  document.getElementById('mealOrigin').addEventListener('click', openMealOrigin);
  document.getElementById('calBtn').addEventListener('click', toggleCal);
  document.getElementById('calReload').addEventListener('click', fetchCal);
  document.getElementById('calPrev').addEventListener('click', () => calGoMonth(calShiftMonth(calMonth, -1)));
  document.getElementById('calNext').addEventListener('click', () => calGoMonth(calShiftMonth(calMonth, 1)));
  document.getElementById('calToday').addEventListener('click', () => calGoMonth(calCurrentMonth()));
  bindFormulaBar();
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
