/* 근태 — frontend logic */

const DAYS = [
  ['mon', '월'], ['tue', '화'], ['wed', '수'], ['thu', '목'], ['fri', '금'],
];
// '출장' = 표시용 마커. 시간은 자유 입력(TTree/EHR도 채움)이고 근무 계산은 일반 근무와 동일.
// '(무급)' 반차 = 표시만 다르고 계산은 일반 반차와 동일(4h 인정 = 주 40h 목표에서 그만큼 빠지는 것과 같은 산수).
// '휴일'은 제거 — 진짜 공휴일은 holidayMap이 자동으로 빨간 표시 + 8h 인정하므로 불필요.
const TYPES = ['', '연차', '오전반차', '오후반차', '오전반차(무급)', '오후반차(무급)', '출장'];

let state = null;          // { settings, weeks: { 'YYYY-MM-DD(월요일)': { mon:{type,in,out}, ... } } }
let weekOffset = 0;        // 0 = 이번 주
let started = false;
let saveTimer = null;
let holidayMap = {};       // { 'YYYY-MM-DD': '공휴일 이름' } — 8시간 근무로 인정
let renderedTodaySig = null; // 마지막 그리드 렌더 시점의 오늘(주+요일) 서명 — 자정 넘어가면 재렌더 트리거

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
  if (type && type.indexOf('오전반차') === 0) return { field: 'in', value: '13:00' };
  if (type && type.indexOf('오후반차') === 0) return { field: 'out', value: '13:00' };
  return null;
}
function isHalfday(type) {
  return !!(type && (type.indexOf('오전반차') === 0 || type.indexOf('오후반차') === 0));
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
      // 구버전 '휴일' 마이그레이션: 시간이 있으면 출장날 표시였을 것 → '출장',
      // 없으면 8h 인정 유지를 위해 '연차'(진짜 공휴일이면 holidayMap이 어차피 우선).
      if (wk[key].type === '휴일') {
        wk[key].type = (wk[key].in || wk[key].out) ? '출장' : '연차';
      }
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
  applyBusTiles();      // 지도 타일도 테마에 맞춰(다크/밝은) 교체
  renderBusMarkers();
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
  const busOut = busPlannedOut(cell, t);
  if (t === cell.type && busOut === null) return cell;
  const e = Object.assign({}, cell, { type: t });
  if (busOut !== null) e.out = fmtClock(busOut);   // 퇴근 버스 '도착 N분 전'을 예정 퇴근으로
  return e;
}

// 반차 인정 시간(크레딧). 오전/오후 반차(무급 포함) = 4h 자동 인정.
function creditSec(cell, settings) {
  return isHalfday(cell.type) ? settings.halfTarget : 0;
}
// 하루 근무 목표. 반차도 하루 목표는 8h (4h 인정 + 4h 실근무).
function targetSec(cell, settings) {
  return settings.dailyTarget;
}
// 회색 기본 예정은 저장하지 않는다. 퇴근이 입력된 날에만 출근 대체값으로 사용한다.
function plannedStartSec(cell, settings) {
  const start = parseTimeToSec(cell.in);
  if (start !== null) return start;
  if (cell.type === '오전반차') return 13 * 3600;
  return parseTimeToSec(settings.defaultIn);
}
function effectiveStartSec(cell, settings) {
  const start = parseTimeToSec(cell.in);
  if (start !== null || parseTimeToSec(cell.out) === null) return start;
  return plannedStartSec(cell, settings);
}
// end: 사용할 종료 시각(초). 미체크아웃 + 오늘이면 현재시각, 과거면 null.
function workedSec(cell, settings, end) {
  const t = cell.type;
  if (t === '연차' || t === '공휴일' || t === '휴일') return settings.dailyTarget;
  const credit = creditSec(cell, settings);            // 반차 4h 자동 인정
  const inS = effectiveStartSec(cell, settings);
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
  const inS = effectiveStartSec(cell, s);
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
      const isLeave = (ec.type === '연차' || isHalfday(ec.type) || ec.type === '공휴일' || ec.type === '휴일');
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
  const result = {};

  pending.forEach(day => {
    const startS = plannedStartSec(day.cell, s);
    if (startS === null) return;

    const needed = Math.max(0, daily);
    const workedNow = day.dayStr === todayStr ? workOnlySec(startS, now, s) : 0;
    const out = workedNow >= needed ? now : endAfterWorkSec(startS, needed, s);
    result[day.key] = floorToMinuteSec(out);
  });

  return result;
}

function timeTone(diff) {
  return diff < 0 ? 'overtime' : diff === 0 ? 'complete' : diff <= state.settings.dailyTarget ? 'near' : 'remaining';
}
// 색상과 상태 문구를 함께 표시해 잔여·달성·연장을 구분한다.
function setRemainCell(id, diff) {
  const el = document.getElementById(id);
  if (!el) return;
  el.dataset.tone = timeTone(diff);
  el.textContent = (diff < 0 ? '+' : '') + fmtDur(Math.abs(diff));
  const label = document.createElement('small');
  label.textContent = diff < 0 ? '연장' : diff === 0 ? '달성' : '남음';
  el.appendChild(label);
}
function setWeeklyProgress(id, total, target) {
  const el = document.getElementById(id);
  const percent = Math.max(0, Math.min(100, total / target * 100));
  el.dataset.tone = timeTone(target - total);
  el.firstElementChild.style.width = percent + '%';
  el.setAttribute('aria-valuenow', Math.round(percent));
  el.setAttribute('aria-valuetext', fmtDur(total) + ' / ' + fmtDur(target));
  el.title = '주간 누적 ' + fmtDur(total) + ' / 목표 ' + fmtDur(target);
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
  for (const tr of ['rowType', 'rowIn', 'rowOut', 'rowWork', 'rowEstOut', 'rowBus']) {
    const row = document.getElementById(tr);
    // 앞쪽 고정 th(행번호 + rowlabel) 2개만 남기고 제거
    while (row.children.length > 2) row.removeChild(row.lastChild);
  }

  const mondayKey = shownMondayKey();
  const monday = new Date(mondayKey + 'T00:00:00');
  const ti = todayInfo();
  const isThisWeek = (mondayKey === ti.mondayKey);
  renderedTodaySig = ti.mondayKey + ':' + ti.dayIndex;   // 이 렌더가 어느 '오늘'을 기준으로 그렸는지 기록

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
      inp.setAttribute('aria-label', label + '요일 ' + (field === 'in' ? '출근 시간' : '퇴근 시간'));
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

    const tdBus = document.createElement('td');
    if (isToday) tdBus.classList.add('today');
    const busBtn = document.createElement('button');
    busBtn.type = 'button';
    busBtn.className = 'buscell';
    busBtn.dataset.day = key;
    busBtn.setAttribute('aria-label', label + '요일 퇴근 버스');
    busBtn.addEventListener('click', () => openBusPicker(key, busBtn));
    tdBus.appendChild(busBtn);
    document.getElementById('rowBus').appendChild(tdBus);
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
  Array.from(sel.classList).forEach(cl => { if (cl.indexOf('type-') === 0) sel.classList.remove(cl); });
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

function updateDefaultInHints(wk) {
  document.querySelectorAll('#rowIn .cellinput').forEach(inp => {
    const cell = wk[inp.dataset.day];
    const fallback = inp.disabled ? '' : normalizeTimeValue(state.settings.defaultIn);
    inp.placeholder = inp.disabled ? '—' : fallback || '출근';
    inp.title = fallback && !cell.in ? '기본 출근 예정 ' + fallback + ' · 퇴근 입력 시 이 시간으로 계산' : '출근 시간';
  });
}

function recompute() {
  const s = state.settings;
  const mondayKey = shownMondayKey();
  const wk = weekData(mondayKey);
  const ti = todayInfo();
  const isThisWeek = (mondayKey === ti.mondayKey);
  const now = nowSec();

  // 자정을 넘겨 '오늘'이 바뀌었으면(1초 타이머로 앱을 켜둔 채 날짜가 넘어간 경우)
  // 그리드를 다시 그려 민트 강조를 옳은 요일로 이동시킨다. buildGrid가 renderedTodaySig를 갱신하므로 무한루프 없음.
  if (renderedTodaySig !== null && renderedTodaySig !== ti.mondayKey + ':' + ti.dayIndex) {
    rerenderWeek();
    return;
  }

  // 근무 시간 셀
  updateDefaultInHints(wk);
  updateBusOutHints(wk);
  document.querySelectorAll('#rowWork td').forEach(td => {
    const key = td.dataset.day;
    const idx = DAYS.findIndex(d => d[0] === key);
    const dayStr = ymd(addDays(new Date(mondayKey + 'T00:00:00'), idx));
    const c = ecell(wk[key], dayStr);                  // 공휴일 반영
    const isToday = isThisWeek && ti.dayIndex === idx;
    td.classList.remove('over', 'holiday');
    td.removeAttribute('title');
    const end = isToday ? now : null;
    const w = workedSec(c, s, end);
    if (w === null) { td.textContent = ''; return; }
    td.textContent = fmtDur(w);
    const inferred = !c.in && parseTimeToSec(c.out) !== null && c.type !== '연차' && c.type !== '휴일' && c.type !== '공휴일';
    td.title = inferred ? '기본 출근 예정 ' + fmt24(plannedStartSec(c, s)) + ' 기준' : '';
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
  setWeeklyProgress('progressNow', nowTotal, wTgt);
  setWeeklyProgress('progressPlan', planTotal, wTgt);
  renderEstimatedCheckoutCells(estimates);
  renderBusCells(mondayKey, wk, estimates);
  if (viewMode === 'bus') {
    renderBusToday();
    if (busSideTab === 'live') renderBusLiveTab();
    if (busSideTab === 'stop' && busPreview && busPreview.min !== Math.floor(now / 60)) renderBusPreview();   // 분이 바뀔 때만
  }
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

/* ---------------- 화면 전환 ---------------- */
// 한 창 안에서 근무·버스·식단·캘린더·TTree·결재 화면을 서로 배타적으로 전환한다.
let viewMode = 'work';   // 'work' | 'bus' | 'meal' | 'cal' | 'ttree' | 'approval'
let mealCacheLoaded = false;

function setView(mode) {
  viewMode = mode;
  closeBusPicker();
  const wrap = document.querySelector('.wrap');
  if (wrap) {
    wrap.classList.toggle('bus-mode', mode === 'bus');
    wrap.classList.toggle('meal-mode', mode === 'meal');
    wrap.classList.toggle('cal-mode', mode === 'cal');
    wrap.classList.toggle('ttree-mode', mode === 'ttree');
    wrap.classList.toggle('approval-mode', mode === 'approval');
  }
  document.querySelectorAll('#sideNav .navitem').forEach(b => {
    const on = b.dataset.view === mode;
    b.classList.toggle('active', on);
    if (on) b.setAttribute('aria-current', 'page');
    else b.removeAttribute('aria-current');
  });
}

// 사이드바 탭 선택. 화면 전환 + 각 화면의 최초 진입/재진입 훅을 여기서 처리한다.
function selectView(mode) {
  if (mode === viewMode) return;
  setView(mode);
  if (mode === 'meal' && !mealCacheLoaded) {
    mealCacheLoaded = true;
    loadMealCache();   // 저장된 게 있으면 즉시 표시 (네트워크 X)
  } else if (mode === 'cal') {
    enterCal();
  } else if (mode === 'ttree') {
    enterTtree();
  } else if (mode === 'bus') {
    enterBus();
  } else if (mode === 'approval') {
    if (!approvalInit) { approvalInit = true; initApprovalPanel(); }
    refreshApprovalSheet();
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

// 전체 선택/해제: on=true면 모든 캘린더 표시, false면 모두 숨김.
function calSetAll(on) {
  if (!calCalendars.length) return;
  calSelected = new Set(on ? calCalendars.map(c => c.id) : []);
  calPersistSelection();
  renderCalLegend();   // 체크박스 상태 반영
  renderCalGrid();     // 그리드 갱신
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

// 범례에 보일 이름. 구독한 남의 캘린더는 '실제 사람 이름(ownerName)'을 우선 보여준다.
// 사람이 자기 캘린더를 팀명으로 지어두면 label(=name)이 팀명뿐이라 누군지 알 수 없기 때문.
// 캘린더 이름(name)이 사람 이름과 다르면 뒤에 '· 팀명'처럼 덧붙인다.
function calLegendLabel(c) {
  if (c.type === 'holiday' || c.type === 'company' || c.mine) return c.label;
  const owner = (c.ownerName || '').trim();
  const name = (c.name || '').trim();
  if (owner) {
    if (name && name !== owner && name !== '내 일정') return owner + ' · ' + name;
    return owner;
  }
  return c.label;
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
    const shown = calLegendLabel(c);
    txt.textContent = shown;
    txt.title = shown + (c.mine || !c.ownerName || shown.indexOf(c.ownerName) !== -1 ? '' : ' (' + c.ownerName + ')');

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


function calGoMonth(mm) {
  calMonth = mm;
  updateCalLabel();
  calEvents = [];                 // 이전 달 잔상 제거
  renderCalGrid();
  loadCalCache();                 // 해당 달 캐시 있으면 즉시 표시
  scheduleCalFetch(350);          // 연타가 멈춘 뒤에 한 번만 최신 조회
}

/* ---------------- 퇴근 버스 ---------------- */
// 퇴근 정류장의 노선 프로필(첫차·막차·요일별 배차·정류장 오프셋 — bus.py)로 그날 도착 시각을 만들고
// '도착 N분 전'을 그날의 예정 퇴근으로 쓴다. 고른 버스는 요일 칸에 { route, at } 로 저장되고
// 실제 퇴근(EHR · 직접 입력)이 있으면 그 값이 우선한다. 예정 퇴근은 ecell() 을 거쳐 주간 누적 ·
// 다른 요일 예상 퇴근 계산에 그대로 반영된다.
const BUS_DEFAULT_CENTER = [37.5665, 126.978];     // 정류장 미설정 시 지도 시작점(서울시청)
const BUS_OFF_TYPES = ['연차', '휴일', '공휴일', '오후반차'];   // 퇴근 버스가 필요 없는 날
const BUS_SOURCE_LABEL = { demo: '데모 배차(추정)', osm: 'OSM 배차', tago: 'TAGO 배차', 'tago+demo': 'TAGO+추정 배차', gbis: '경기도 배차' };
// 출퇴근(peak) 배차를 쓰는 시간대 — 기점 출발 기준. 경기도 API 노선은 출퇴근/평시 배차가 따로 있다.
const BUS_PEAK = [[7 * 3600, 9 * 3600], [17 * 3600, 20 * 3600]];
const DOW = '일월화수목금토';

let busMap = null;
let busTiles = null;
let busLayer = null;
let busStops = [];            // 지도에 표시 중인 정류장 후보
let busBusy = false;
let busLive = null;           // { at: ms, arrivals: [{no, sec, prev}] } — TAGO 실시간 도착
let busLiveTimer = null;
let busTodaySig = '';         // 오늘의 버스 목록 재렌더 판단(분 · 설정 · 선택이 바뀔 때만)
let busPopDay = null;         // 열린 선택 팝업의 요일 키
let busDefaultKey = false;    // config.json 에 배포 기본 키가 있는지(값은 모름)
let busPreview = null;        // 지도에서 누른(아직 저장 전) 정류장: { stop, saved, routes, take:Set, live, loading, … }
let busPreviewSeq = 0;        // 미리보기 요청 순번(그새 다른 정류장을 누르면 이전 응답 폐기)
let busSideTab = 'today';     // 오른쪽 열 탭: 'today' | 'live' | 'stop'
let busLiveError = '';        // 마지막 실시간 조회 실패 사유(성공 · 미조회면 '')
let busLiveTabSig = '';       // 실시간 탭 재렌더 판단(받은 시각 · 30초 경과 · 설정이 바뀔 때만)

function busCfg() {
  const b = state.settings.bus || (state.settings.bus = {});
  if (!Array.isArray(b.routes)) b.routes = [];
  if (!Array.isArray(b.take)) b.take = b.routes.map(r => r.no);
  if (!(b.bufferMin >= 0)) b.bufferMin = 5;          // 기본: 버스 도착 5분 전 퇴근
  return b;
}
function busBufferSec() { return busCfg().bufferMin * 60; }
function busDayKind(date) {
  const dow = date.getDay();
  if (dow === 0 || holidayMap[ymd(date)]) return 'sun';    // 일요일 · 공휴일 배차
  return dow === 6 ? 'sat' : 'wd';
}
// 노선 하나의 그날 이 정류장 도착 시각(초): 첫차~막차를 배차 간격으로 + 기점→정류장 소요.
// span(토·일 첫차/막차) · ivOff(평시 배차)는 경기도 API 노선에만 있다 — 없으면 하루 한 가지 배차.
function busRouteTimes(route, date) {
  const kind = busDayKind(date);
  const span = (route.span && route.span[kind]) || route;
  const first = parseTimeToSec(span.first), last = parseTimeToSec(span.last);
  if (first === null || last === null) return [];
  const iv = route.iv || {}, ivOff = route.ivOff;
  if (ivOff && !iv[kind] && !ivOff[kind]) return [];          // 그 요일 배차 0 = 운행 안 함(주말 쉬는 마을버스 등)
  const peak = Math.max(3, iv[kind] || iv.wd || 15) * 60;
  const calm = ivOff ? Math.max(3, ivOff[kind] || ivOff.wd || peak / 60) * 60 : peak;
  const end = last < first ? last + 86400 : last;            // 자정 넘는 막차
  const off = (route.offset || 0) * 60;
  const out = [];
  for (let t = first; t <= end; t += BUS_PEAK.some(([a, z]) => t % 86400 >= a && t % 86400 < z) ? peak : calm) out.push(t + off);
  if (out[out.length - 1] < end + off - 60) out.push(end + off);      // 막차는 배차 간격과 상관없이 그 시각에 있다
  return out;
}
// 노선 하나의 그날 도착 시각 [{at, live}]. 실시간으로 보이는 구간은 실제 도착 예정으로 바꾼다
// (그 사이 시간표상 버스는 실제로 없다 — 밤엔 배차가 대표값보다 김). liveFn: busLiveTimes() 결과.
function busTimesWithLive(r, date, liveFn) {
  let times = busRouteTimes(r, date);
  const obs = liveFn ? liveFn(r) : [];
  if (obs.length) {
    const until = obs[obs.length - 1] + (times.length > 1 ? (times[1] - times[0]) / 2 : 0);
    times = obs.concat(times.filter(t => t > until));
  }
  return times.map(at => ({ at, live: obs.includes(at) }));
}
// 그날 탈 수 있는 버스(체크한 노선) 도착순. leave = 도착 − N분 = 그 버스를 타려면 나서야 하는 시각.
function busArrivalsOn(date) {
  const b = busCfg();
  const take = new Set(b.take);
  const buf = busBufferSec();
  const live = busLiveTimes(busLive, date);
  const list = [];
  b.routes.filter(r => take.has(r.no)).forEach(r => {
    busTimesWithLive(r, date, live).forEach(t => list.push({ route: r.no, at: t.at, leave: t.at - buf, live: t.live }));
  });
  return list.sort((x, y) => x.at - y.at || x.route.localeCompare(y.route));
}
// 노선 맞추기: TAGO 경기도 노선 id 는 'GGB' + 경기도 routeId 라서 앞 GGB 를 떼고 비교한다.
function busLiveMatch(r, a) {
  const id = x => String(x || '').replace(/^GGB/, '');
  return r.id && a.id ? id(a.id) === id(r.id) : a.no === r.no;
}
function busLiveCapable(stop) { return !!stop && (stop.source === 'tago' || stop.source === 'gbis'); }
// TAGO 로 저장했던 경기도 정류장(GGB…)을 경기도 API 정류장 모양으로 — 지도 표시 · 저장 여부 비교용(TAGO 필드도 유지)
function busGbisShape(s) {
  const m = s && s.source === 'tago' && /^GGB(\d+)$/.exec(s.nodeId || '');
  return m ? Object.assign({}, s, { id: 'gbis:' + m[1], stationId: m[1], source: 'gbis' }) : s;
}
// 오늘 · 3분 안에 받은 실시간 도착만 쓴다: 노선 → 정류장 도착 예정(초, 분 단위) 목록
function busLiveTimes(live, date) {
  if (!live || ymd(date) !== ymd(new Date()) || Date.now() - live.at > 180000) return null;
  return r => [...new Set(live.arrivals.filter(a => busLiveMatch(r, a))
    .map(a => Math.round((live.base + a.sec) / 60) * 60))].sort((x, y) => x - y);
}
// 근무 목표를 채운 시각(need) 이후 처음 탈 수 있는 버스
function busRecommend(list, need) {
  if (need === null || need === undefined) return null;
  return list.find(x => x.leave >= need) || null;
}
function busPlannedOut(cell, type) {
  if (!cell.bus || parseTimeToSec(cell.out) !== null || BUS_OFF_TYPES.includes(type)) return null;
  const at = parseTimeToSec(cell.bus.at);
  return at === null ? null : Math.max(0, at - busBufferSec());
}
// 이 요일의 버스 선택만 빼고 계산한 예상 퇴근 = 그날 나서도 되는 가장 이른 시각(다른 요일 선택은 반영).
function busNeedSec(mondayKey, dayKey) {
  const wk = weekData(mondayKey);
  const probe = Object.assign({}, wk, { [dayKey]: Object.assign({}, wk[dayKey], { bus: null }) });
  const est = estimateCheckouts(probe, state.settings, mondayKey, nowSec())[dayKey];
  return est === undefined ? null : est;
}
function busDateOf(mondayKey, dayKey) {
  return addDays(new Date(mondayKey + 'T00:00:00'), DAYS.findIndex(d => d[0] === dayKey));
}
function busDayLabel(date) {
  return DOW[date.getDay()] + ' ' + (date.getMonth() + 1) + '/' + date.getDate();
}
function busIsPicked(pick, x) {
  return !!pick && pick.route === x.route && parseTimeToSec(pick.at) === x.at;
}
function busEl(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text !== undefined) el.textContent = text;
  return el;
}

function setDayBus(mondayKey, dayKey, x) {
  const cell = weekData(mondayKey)[dayKey];
  if (x) cell.bus = { route: x.route, at: fmt24(x.at) };
  else delete cell.bus;
  scheduleSave();
  busTodaySig = '';
  recompute();
}

// 근무 그리드 '퇴근 버스' 행: 고른 버스(실선) / 예상 퇴근 이후 첫 버스 추천(점선)
function renderBusCells(mondayKey, wk, estimates) {
  const b = busCfg();
  const on = !!b.stop;
  document.getElementById('rowBus').hidden = !on;
  document.getElementById('grid').classList.toggle('has-bus', on);
  if (!on) return;
  const now = nowSec(), todayStr = ymd(new Date());
  document.querySelectorAll('#rowBus .buscell').forEach(btn => {
    const key = btn.dataset.day;
    const date = busDateOf(mondayKey, key);
    const cell = wk[key];
    const off = BUS_OFF_TYPES.includes(effType(cell, ymd(date)));
    let pick = null, cls = '', title = '클릭해서 퇴근 버스 선택';
    if (off) {
      title = '이 날은 퇴근 버스가 필요 없어요';
    } else if (cell.bus) {
      pick = cell.bus; cls = 'picked';
      title = cell.bus.route + ' ' + cell.bus.at + ' 도착 → ' + fmt24(parseTimeToSec(cell.bus.at) - busBufferSec()) + ' 퇴근 · 클릭해서 변경';
    } else {
      const list = busArrivalsOn(date).filter(x => ymd(date) !== todayStr || x.leave >= now);
      const rec = busRecommend(list, estimates[key]);
      if (rec) {
        pick = { route: rec.route, at: fmt24(rec.at) }; cls = 'suggest';
        title = '추천: 예상 퇴근 ' + fmt24(estimates[key]) + ' 이후 첫 버스 · ' + fmt24(rec.leave) + ' 퇴근 · 클릭해서 선택';
      }
    }
    btn.disabled = off;
    btn.title = title;
    const sig = [cls, pick ? pick.route + pick.at : '', off].join('|');
    if (btn.dataset.sig === sig) return;           // 1초 타이머마다 DOM 을 새로 만들지 않도록
    btn.dataset.sig = sig;
    btn.className = 'buscell' + (cls ? ' ' + cls : '');
    btn.textContent = '';
    if (pick) btn.append(busEl('span', 'busno', pick.route), busEl('span', 'busat', pick.at));
    else btn.textContent = off ? '—' : '선택';
  });
}

// 고른 버스가 있고 퇴근이 비었으면 퇴근 칸에 '도착 N분 전'을 회색 예정으로 보여준다.
function updateBusOutHints(wk) {
  document.querySelectorAll('#rowOut .cellinput').forEach(inp => {
    const cell = wk[inp.dataset.day];
    const at = cell.bus && !inp.disabled ? parseTimeToSec(cell.bus.at) : null;
    inp.placeholder = at === null ? '퇴근' : fmt24(at - busBufferSec());
    inp.title = at === null ? '퇴근 시간'
      : '퇴근 버스 ' + cell.bus.route + ' ' + cell.bus.at + ' 도착 ' + busCfg().bufferMin + '분 전 · 직접 입력하면 입력값이 우선';
  });
}

// 버스 한 줄(요일 팝업 · 오늘의 버스 공용). ctx: { rec, pick, need, now(오늘이면) }
function busOptionEl(x, ctx, onPick) {
  const btn = busEl('button', 'busopt');
  btn.type = 'button';
  const picked = busIsPicked(ctx.pick, x);
  const isRec = !picked && ctx.rec === x;
  if (picked) btn.classList.add('picked');
  else if (isRec) btn.classList.add('rec');
  if (ctx.need !== null && ctx.need !== undefined && x.leave < ctx.need) btn.classList.add('early');
  if (x.live) btn.classList.add('live');
  const leave = busEl('span', 'busopt-leave');
  leave.append(busEl('b', '', fmt24(x.leave)), document.createTextNode(' 퇴근'));
  const tags = [];
  if (picked) tags.push('선택됨');
  else if (isRec) tags.push('추천');
  if (ctx.now !== null && ctx.now !== undefined) {
    const left = Math.round((x.leave - ctx.now) / 60);
    if (left < 0) { tags.push('서둘러요'); btn.classList.add('hurry'); }
    else tags.push(left >= 60 ? Math.floor(left / 60) + '시간 ' + (left % 60) + '분 후' : left + '분 후');
  }
  btn.append(busEl('span', 'busopt-at', fmt24(x.at)), busEl('span', 'busno', x.route), leave, busEl('span', 'busopt-tag', tags.join(' · ')));
  btn.title = x.route + ' ' + fmt24(x.at) + ' 도착' + (x.live ? '(실시간)' : '') + ' → ' + fmt24(x.leave) + ' 퇴근' + (x.leave < (ctx.need || 0) ? ' (예상 퇴근보다 이름)' : '');
  btn.addEventListener('click', onPick);
  return btn;
}

// 요일 칸 클릭 → 그날 버스 도착 시각 목록에서 고른다(예상 퇴근 이후 첫 버스 추천).
function openBusPicker(dayKey, anchor) {
  const b = busCfg();
  if (!b.stop) { toggleBus(); return; }
  if (busPopDay === dayKey) { closeBusPicker(); return; }
  const mondayKey = shownMondayKey();
  const date = busDateOf(mondayKey, dayKey);
  const isToday = ymd(date) === ymd(new Date());
  const cell = weekData(mondayKey)[dayKey];
  const need = busNeedSec(mondayKey, dayKey);
  const now = nowSec();
  const all = busArrivalsOn(date).filter(x => !isToday || x.leave >= now);
  const rec = busRecommend(all, need);
  const from = (need !== null ? need : (rec ? rec.leave : 17 * 3600)) - 40 * 60;
  const list = all.filter(x => x.leave >= from || busIsPicked(cell.bus, x)).slice(0, 30);

  const pop = document.getElementById('busPop');
  pop.innerHTML = '';
  const head = busEl('div', 'buspophead');
  const close = busEl('button', 'buspopx', '×');
  close.type = 'button';
  close.title = '닫기';
  close.addEventListener('click', closeBusPicker);
  head.append(busEl('strong', '', busDayLabel(date) + ' · 퇴근 버스'), close);
  const sub = busEl('div', 'buspopsub');
  sub.append(document.createTextNode(b.stop.name + (need !== null ? ' · 예상 퇴근 ' : '')));
  if (need !== null) sub.append(busEl('b', '', fmt24(need)));
  sub.append(document.createTextNode(' · 도착 ' + b.bufferMin + '분 전 퇴근'));
  if (parseTimeToSec(cell.out) !== null) sub.append(document.createTextNode(' · 입력한 퇴근 ' + normalizeTimeValue(cell.out) + ' 우선'));
  const body = busEl('div', 'buspoplist');
  if (!list.length) body.append(busEl('div', 'busempty', b.take.length ? '이 시간 이후 버스가 없어요' : '버스 화면에서 탈 버스를 체크하세요'));
  let recEl = null;
  list.forEach(x => {
    const el = busOptionEl(x, { rec, pick: cell.bus, need, now: isToday ? now : null }, () => {
      setDayBus(mondayKey, dayKey, busIsPicked(cell.bus, x) ? null : x);
      closeBusPicker();
    });
    if (x === rec || busIsPicked(cell.bus, x)) recEl = recEl || el;
    body.append(el);
  });
  const foot = busEl('div', 'buspopfoot');
  const src = new Set(b.routes.map(r => BUS_SOURCE_LABEL[r.source] || r.source));
  foot.append(busEl('span', '', [...src].join(' · ') + ' · ' + DOW[date.getDay()] + (busDayKind(date) === 'wd' ? ' 평일' : busDayKind(date) === 'sat' ? ' 토요일' : ' 휴일') + ' 배차'));
  if (cell.bus) {
    const clear = busEl('button', 'themebtn', '선택 해제');
    clear.type = 'button';
    clear.addEventListener('click', () => { setDayBus(mondayKey, dayKey, null); closeBusPicker(); });
    foot.append(clear);
  }
  pop.append(head, sub, body, foot);
  pop.hidden = false;
  busPopDay = dayKey;
  const r = anchor.getBoundingClientRect();
  const left = Math.min(Math.max(8, r.left + r.width / 2 - pop.offsetWidth / 2), innerWidth - pop.offsetWidth - 8);
  let top = r.bottom + 4;
  if (top + pop.offsetHeight > innerHeight - 8) top = Math.max(8, r.top - pop.offsetHeight - 4);
  pop.style.left = left + 'px';
  pop.style.top = top + 'px';
  if (recEl) body.scrollTop = Math.max(0, recEl.offsetTop - body.offsetTop - 34);
}
function closeBusPicker() {
  const pop = document.getElementById('busPop');
  if (pop) pop.hidden = true;
  busPopDay = null;
}
function onBusOutsideClick(e) {
  const pop = document.getElementById('busPop');
  if (pop && !pop.hidden && !pop.contains(e.target) && !e.target.closest('.buscell')) closeBusPicker();
  const places = document.getElementById('busPlaces');
  if (places && !places.hidden && !e.target.closest('#busSearchForm')) places.hidden = true;
}

/* 버스 화면: 지도에서 정류장 고르기 + 오늘의 버스 */
// 버스 화면 열기. 사이드바에서는 selectView('bus') → enterBus(), 그리드의 '퇴근 버스' 셀에서는 toggleBus().
function toggleBus() {
  setView('bus');
  enterBus();
}
function enterBus() {
  const b = busCfg();
  document.getElementById('busBuffer').value = b.bufferMin;
  renderBusSide();
  showBusTab(busSideTab);
  if (!window.L) setBusStatus('지도 라이브러리를 불러오지 못했어요', 'err');
  else if (!busMap) initBusMap();
  else setTimeout(() => busMap.invalidateSize(), 0);
  refreshBusLive();
}
function setBusStatus(msg, cls) {
  const el = document.getElementById('busStatus');
  el.textContent = msg || '';
  el.className = 'calstatus' + (cls ? ' ' + cls : '');
  el.title = msg || '';
}
function setBusBusy(busy) {
  busBusy = busy;
  document.getElementById('busScan').disabled = busy;
  document.querySelector('#busSearchForm button').disabled = busy;
}
function initBusMap() {
  const b = busCfg();
  // 마지막으로 보던 지도 위치 → 고른 정류장 → 기본 위치 순으로 연다(다시 켜도 그대로)
  const view = b.view ? [[b.view.lat, b.view.lng], b.view.zoom] : b.stop ? [[b.stop.lat, b.stop.lng], 17] : [BUS_DEFAULT_CENTER, 15];
  busMap = L.map('busMap', { zoomControl: true, attributionControl: false }).setView(view[0], view[1]);
  busMap.on('moveend', () => {
    const c = busMap.getCenter();
    busCfg().view = { lat: +c.lat.toFixed(5), lng: +c.lng.toFixed(5), zoom: busMap.getZoom() };
    scheduleSave();
  });
  // 앱 창(pywebview) 안에서 링크를 누르면 창이 이동하므로 출처 표기는 링크 없이 텍스트로만
  L.control.attribution({ prefix: false }).addAttribution('© OpenStreetMap contributors').addTo(busMap);
  // 앱 창(file://)은 Referer 가 없어 OSM 타일 서버가 막는다 → 타일은 Python(bus.tile)이 받아 캐시해서 넘긴다
  busTiles = new (L.GridLayer.extend({
    createTile(c, done) {
      const img = document.createElement('img');
      img.alt = '';
      img.onload = () => done(null, img);
      img.onerror = () => done(null, img);
      const req = apiReady('bus_tile') ? pywebview.api.bus_tile(c.z, c.x, c.y) : Promise.resolve(null);
      req.then(src => { if (src) img.src = src; else done(null, img); }, () => done(null, img));
      return img;
    },
  }))({ maxZoom: 19, minZoom: 6 }).addTo(busMap);
  busLayer = L.layerGroup().addTo(busMap);
  applyBusTiles();
  busStops = Array.isArray(b.nearby) ? b.nearby : [];      // 지난번에 찾은 주변 정류장
  renderBusMarkers();
  setTimeout(() => busMap.invalidateSize(), 0);
}
// 다크 테마는 밝은 OSM 타일을 CSS 필터로 반전해 어둡게 보여준다
function applyBusTiles() {
  const el = document.getElementById('busMap');
  if (el) el.classList.toggle('dark', document.documentElement.getAttribute('data-theme') !== 'excel');
}
function busCssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function renderBusMarkers() {
  if (!busLayer) return;
  busLayer.clearLayers();
  const sel = busCfg().stop;
  const pv = busPreview && !busPreview.saved ? busPreview.stop : null;
  const list = busStops.slice();
  [sel, pv].forEach(x => { if (x && !list.some(s => s.id === x.id)) list.push(x); });
  const mint = busCssVar('--mint'), blue = busCssVar('--total'), panel = busCssVar('--panel'), yellow = busCssVar('--remaining');
  list.forEach(s => {
    const on = !!sel && sel.id === s.id;            // 저장된 퇴근 정류장
    const look = !!pv && pv.id === s.id;            // 지금 보고 있는(저장 전) 정류장
    const m = L.circleMarker([s.lat, s.lng], {
      radius: on ? 9 : look ? 8 : 6, weight: on || look ? 3 : 2, color: on ? mint : look ? yellow : blue,
      fillColor: on ? mint : panel, fillOpacity: on ? .85 : .95,
    });
    const tip = busEl('div');
    tip.append(busEl('b', '', s.name + (s.no ? ' (' + s.no + ')' : '')));
    if ((s.routes || []).length) tip.append(document.createElement('br'), document.createTextNode(s.routes.join(' · ')));
    m.bindTooltip(tip, { direction: 'top', offset: [0, -6] });
    m.on('click', () => previewBusStop(s));
    busLayer.addLayer(m);
  });
  document.getElementById('busMapHint').hidden = list.length > 0;
}

async function scanBusStops() {
  if (!busMap || busBusy) return;
  const b = busCfg();
  const c = busMap.getCenter();
  const radius = Math.round(Math.min(900, Math.max(250, busMap.distance(c, busMap.getBounds().getNorthEast()) * 0.75)));
  setBusBusy(true);
  setBusStatus(busHasKey() ? '정류장 찾는 중…' : '정류장 찾는 중… (OSM 서버가 붐비면 30초쯤 걸려요)');
  let res = null;
  try {
    res = apiReady('bus_nearby') ? await pywebview.api.bus_nearby(c.lat, c.lng, radius)
      : { status: 'error', message: '데스크톱 앱에서만 가능' };
  } catch (e) { res = { status: 'error', message: String(e) }; }
  setBusBusy(false);
  if (!res || res.status !== 'ok') { setBusStatus((res && res.message) || '정류장 조회 실패', 'err'); return; }
  busStops = res.stops || [];
  b.nearby = busStops;             // 다시 켰을 때 지도에 그대로 보이도록 저장
  scheduleSave();
  renderBusMarkers();
  setBusStatus(busStops.length ? '정류장 ' + busStops.length + '곳 · 눌러서 오는 버스 보기' : '근처에 정류장이 없어요 — 지도를 옮겨 다시 찾아보세요', busStops.length ? 'ok' : 'err');
}

async function searchBusPlace(e) {
  if (e) e.preventDefault();
  const q = document.getElementById('busSearch').value.trim();
  const box = document.getElementById('busPlaces');
  if (!q || busBusy) return;
  setBusStatus('장소 검색 중…');
  let res = null;
  try {
    res = apiReady('bus_search') ? await pywebview.api.bus_search(q) : { status: 'error', message: '데스크톱 앱에서만 가능' };
  } catch (err) { res = { status: 'error', message: String(err) }; }
  box.innerHTML = '';
  box.hidden = true;
  if (!res || res.status !== 'ok') { setBusStatus((res && res.message) || '장소 검색 실패', 'err'); return; }
  const places = res.places || [];
  if (!places.length) { setBusStatus('검색 결과가 없어요', 'err'); return; }
  const go = p => {
    box.hidden = true;
    if (busMap) busMap.setView([p.lat, p.lng], 17);
    scanBusStops();
  };
  if (places.length === 1) { go(places[0]); return; }
  setBusStatus('');
  places.forEach(p => {
    const btn = busEl('button', 'busplace', p.name);
    btn.type = 'button';
    if (p.detail) btn.append(busEl('small', '', p.detail));
    btn.addEventListener('click', () => go(p));
    box.append(btn);
  });
  box.hidden = false;
}

// 지도에서 정류장을 누르면 '정류장' 탭에서 그 정류장에 오는 버스(노선별 다음 도착)를 먼저 보여주고,
// 저장을 눌러야 퇴근 정류장이 된다. 저장된 정류장을 다시 열면 탈 버스만 바꿔 저장할 수 있다.
async function previewBusStop(stop) {
  const b = busCfg();
  const saved = !!b.stop && b.stop.id === stop.id;
  const seq = ++busPreviewSeq;
  const p = busPreview = { stop, saved, routes: [], take: new Set(saved ? b.take : []), live: null, loading: true, liveLoading: false, error: '' };
  showBusTab('stop');
  renderBusMarkers();
  // 저장된 정류장도 노선을 새로 받는다(새 노선 · 경기도 API 반영). 못 받으면 저장된 노선으로.
  let res = null;
  try {
    res = apiReady('bus_stop_routes') ? await pywebview.api.bus_stop_routes(stop)
      : { status: 'error', message: '데스크톱 앱에서만 가능' };
  } catch (e) { res = { status: 'error', message: String(e) }; }
  if (saved && (!res || res.status !== 'ok')) res = { status: 'ok', routes: JSON.parse(JSON.stringify(b.routes)) };
  if (seq !== busPreviewSeq) return;                 // 그새 다른 정류장을 눌렀으면 버린다
  p.loading = false;
  if (!res || res.status !== 'ok') { p.error = (res && res.message) || '노선 조회 실패'; renderBusPreview(); return; }
  p.routes = res.routes || [];
  if (!saved) p.take = new Set(p.routes.map(r => r.no));    // 새 정류장은 일단 전부 체크(저장된 정류장은 고른 것만)
  const fresh = saved && busLive && Date.now() - busLive.at < 50000;
  p.liveLoading = !fresh && busLiveCapable(stop) && busHasKey() && apiReady('bus_arrivals');
  if (fresh) p.live = busLive;
  renderBusPreview();
  if (!p.liveLoading) return;
  let a = null;
  try { a = await pywebview.api.bus_arrivals(stop); } catch (e) { a = null; }
  if (seq !== busPreviewSeq) return;
  p.liveLoading = false;
  if (a && a.status === 'ok') {
    p.live = busLiveFrom(a);
    busCalibrate(p.routes, p.live.arrivals, p.live.base);   // 미리보기 시각도 실시간에 맞춘다
  }
  renderBusPreview();
}

function saveBusPreview() {
  const p = busPreview;
  if (!p || p.loading || !p.routes.length || !p.take.size) return;
  const b = busCfg();
  const s = p.stop;
  b.stop = { id: s.id, name: s.name, no: s.no || '', lat: s.lat, lng: s.lng, source: s.source, cityCode: s.cityCode || '', nodeId: s.nodeId || '', stationId: s.stationId || '' };
  b.routes = p.routes;
  b.take = p.routes.map(r => r.no).filter(no => p.take.has(no));
  busLive = p.live;
  if (p.live) { b.liveFixAt = p.live.at; busSnapPicks(p.routes); }
  doSave();
  busPreview = null;
  showBusTab('today');
  renderBusMarkers();
  renderBusSide();
  recompute();
  refreshBusLive();
  setBusStatus('퇴근 정류장 저장 · ' + s.name + ' · 탈 버스 ' + b.take.length + '개', 'ok');
}

// 오른쪽 열 탭: 오늘의 버스 / 실시간 / 정류장(지도에서 누른 정류장 미리보기 — 있을 때만)
function showBusTab(tab) {
  busSideTab = tab === 'stop' && busPreview ? 'stop' : tab === 'live' ? 'live' : 'today';
  const stopTab = document.getElementById('busTabStop');
  stopTab.hidden = !busPreview;
  if (busPreview) stopTab.textContent = '정류장 · ' + busPreview.stop.name;
  [['busTabToday', 'today'], ['busTabLive', 'live'], ['busTabStop', 'stop']].forEach(([id, t]) => {
    const el = document.getElementById(id);
    el.classList.toggle('active', busSideTab === t);
    el.setAttribute('aria-selected', String(busSideTab === t));
  });
  document.getElementById('busTodayPane').hidden = busSideTab !== 'today';
  document.getElementById('busLivePane').hidden = busSideTab !== 'live';
  document.getElementById('busStopPane').hidden = busSideTab !== 'stop';
  if (busSideTab === 'stop') renderBusPreview();
  else if (busSideTab === 'live') { busLiveTabSig = ''; renderBusLiveTab(); }
  else { busTodaySig = ''; renderBusToday(); }
}

// 실시간 탭: 저장된 정류장의 탈 버스만, 노선마다 다가오는 버스(최대 2대)를 곧 오는 순으로.
// 다가오는 버스가 없는 노선도 '도착 정보 없음'으로 남겨서 저장한 버스가 다 보이게 한다.
function renderBusLiveTab() {
  const b = busCfg();
  const aged = busLive ? Math.max(0, (Date.now() - busLive.at) / 1000) : 0;
  const sig = [b.stop && b.stop.id, b.take.join(','), busLive && busLive.at, Math.floor(aged / 30), busLiveError, busHasKey()].join('|');
  if (sig === busLiveTabSig) return;
  busLiveTabSig = sig;
  document.getElementById('busLiveTitle').textContent = b.stop ? b.stop.name + (b.stop.no ? ' · ' + b.stop.no : '') : '실시간 도착';
  const got = busLive ? new Date(busLive.at) : null;
  document.getElementById('busLiveMeta').textContent = got
    ? pad(got.getHours()) + ':' + pad(got.getMinutes()) + ':' + pad(got.getSeconds()) + ' 기준 · 1분마다 갱신' : '';
  const box = document.getElementById('busLiveList');
  box.innerHTML = '';
  if (!b.stop) { box.append(busEl('div', 'busempty', '저장된 퇴근 정류장이 없어요.\n지도에서 정류장을 눌러 저장하세요.')); return; }
  if (!b.take.length) { box.append(busEl('div', 'busempty', '탈 버스가 없어요 — 오늘의 버스 탭에서 정류장 이름을 눌러 체크하세요.')); return; }
  if (!busLiveCapable(b.stop) || !busHasKey()) {
    box.append(busEl('div', 'busempty', '이 정류장은 실시간 도착을 볼 수 없어요.\n(경기도 · TAGO 정류장 + 공공데이터포털 키 필요)'));
    return;
  }
  if (!busLive) { box.append(busEl('div', 'busempty', busLiveError ? '실시간 도착 조회 실패: ' + busLiveError : '실시간 도착 불러오는 중…')); return; }
  const take = new Set(b.take);
  const rows = b.routes.filter(r => take.has(r.no))
    .map(r => ({ r, buses: busLive.arrivals.filter(a => busLiveMatch(r, a)).slice(0, 2) }))
    .sort((x, y) => (x.buses.length ? x.buses[0].sec : Infinity) - (y.buses.length ? y.buses[0].sec : Infinity));
  rows.forEach(({ r, buses }) => {
    const row = busEl('div', 'busliverow' + (buses.length ? '' : ' none'));
    const info = busEl('span', 'busliveinfo');
    if (!buses.length) info.textContent = '도착 정보 없음';
    buses.forEach(a => {
      const min = Math.max(0, Math.round((a.sec - aged) / 60));
      const at = (Math.round((busLive.base + a.sec) / 60) * 60) % 86400;
      const el = busEl('span');
      el.append(busEl('b', '', min ? min + '분' : '곧 도착'), document.createTextNode(fmt24(at) + (a.prev ? ' · ' + a.prev + '정류장 전' : '')));
      info.append(el);
    });
    row.append(busEl('span', 'busno', r.no), busEl('span', 'busroute-meta', r.dest ? r.dest + ' 방면' : ''), info);
    box.append(row);
  });
}

// '배차 10~25분'(출퇴근~평시) / '배차 15분'. 그 요일 배차가 없으면 ''
function busIvText(r, kind) {
  const a = (r.iv && (r.ivOff ? r.iv[kind] : r.iv[kind] || r.iv.wd)) || 0;
  const z = (r.ivOff && r.ivOff[kind]) || a;
  if (!a && !z) return '';
  return '배차 ' + (a && z && a !== z ? Math.min(a, z) + '~' + Math.max(a, z) : (a || z)) + '분';
}

// 정류장 탭: 노선마다 다음 도착 3번(실시간이면 초록) + 탈 버스 체크 + 저장
function renderBusPreview() {
  const p = busPreview;
  if (!p) return;
  const s = p.stop;
  const now = nowSec();
  p.min = Math.floor(now / 60);
  document.getElementById('busPrevName').textContent = s.name;
  document.getElementById('busPrevMeta').textContent = [s.no, s.dist ? s.dist + 'm' : '', p.saved ? '저장된 퇴근 정류장' : ''].filter(Boolean).join(' · ');
  const liveEl = document.getElementById('busPrevLive');
  renderBusLiveLine(liveEl, p.live, () => true);
  if (p.liveLoading) { liveEl.hidden = false; liveEl.textContent = '실시간 도착 불러오는 중…'; }
  const save = document.getElementById('busPrevSave');
  save.textContent = p.saved ? '탈 버스 저장' : '이 정류장으로 저장';
  save.disabled = p.loading || !p.routes.length || !p.take.size;
  const box = document.getElementById('busPrevRoutes');
  box.innerHTML = '';
  if (p.loading) { box.append(busEl('div', 'busempty', '노선 정보를 불러오는 중…')); return; }
  if (p.error) { box.append(busEl('div', 'busempty', p.error)); return; }
  if (!p.routes.length) { box.append(busEl('div', 'busempty', '이 정류장을 지나는 노선 정보를 찾지 못했어요.\n옆 정류장을 눌러보세요.')); return; }
  const today = new Date(), kind = busDayKind(today);
  const live = busLiveTimes(p.live, today);
  p.routes.forEach(r => {
    const row = busEl('label', 'busprevroute');
    const chk = busEl('input');
    chk.type = 'checkbox';
    chk.checked = p.take.has(r.no);
    chk.addEventListener('change', () => {
      if (chk.checked) p.take.add(r.no); else p.take.delete(r.no);
      save.disabled = !p.take.size;
    });
    const meta = busEl('span', 'busroute-meta', [r.dest ? r.dest + ' 방면' : '', busIvText(r, kind)].filter(Boolean).join(' · '));
    meta.title = (r.kind ? r.kind + ' · ' : '') + (r.first ? r.first + '~' + r.last + ' · ' : '')
      + ['wd', 'sat', 'sun'].map(d => ({ wd: '평일', sat: '토', sun: '일/공휴일' })[d] + ' ' + (busIvText(r, d) || '운행 안 함')).join(' · ');
    const times = busEl('span', 'busprevtimes');
    const next = busTimesWithLive(r, today, live).filter(t => t.at >= now).slice(0, 3);
    if (!next.length) times.textContent = !r.first ? '시간표 정보 없음 · 실시간만' : busRouteTimes(r, today).length ? '오늘 운행 끝' : '오늘 운행 안 함';
    next.forEach((t, i) => {
      const el = busEl('b', t.live ? 'live' : '', fmt24(t.at));
      el.title = t.live ? '실시간 도착 예정' : '시간표 추정';
      times.append(el);
      if (i === 0) times.append(busEl('small', '', Math.max(0, Math.round((t.at - now) / 60)) + '분 후'));
    });
    row.append(chk, busEl('span', 'busno', r.no), meta, times);
    box.append(row);
  });
}

// 배차 출처 + 오늘 실시간 보정 시각
function renderBusSrc() {
  const b = busCfg();
  const parts = [...new Set(b.routes.map(r => BUS_SOURCE_LABEL[r.source] || r.source))];
  const fix = b.liveFixAt ? new Date(b.liveFixAt) : null;
  if (fix && ymd(fix) === ymd(new Date())) parts.push('실시간 보정 ' + pad(fix.getHours()) + ':' + pad(fix.getMinutes()));
  const el = document.getElementById('busSrc');
  el.textContent = parts.join(' · ');
  el.title = fix ? '실시간 도착 예정에 맞춰 노선별 정류장 도착 시각을 보정했어요' : '';
}

// 오늘의 버스 탭 머리: 저장된 정류장(누르면 정류장 탭에서 탈 버스 변경) · 배차 출처 · N분 전
function renderBusSide() {
  const b = busCfg();
  const btn = document.getElementById('busStopEdit');
  btn.disabled = !b.stop;
  btn.textContent = b.stop ? b.stop.name + (b.stop.no ? ' · ' + b.stop.no : '') + ' ›' : '퇴근 정류장 미설정';
  btn.title = b.stop ? '정류장에 오는 버스 보기 · 탈 버스 바꾸기' : '';
  renderBusSrc();
  busTodaySig = '';
  renderBusToday();
}

// 오늘의 버스: 지금부터(또는 예상 퇴근 30분 전부터) 정류장에 올 버스와 그에 맞춘 퇴근 시각.
function renderBusToday() {
  const box = document.getElementById('busToday');
  const b = busCfg();
  const today = new Date(), now = nowSec();
  const ti = todayInfo();
  const cell = ti.dayKey ? weekData(ti.mondayKey)[ti.dayKey] : null;
  const off = !cell || BUS_OFF_TYPES.includes(effType(cell, ymd(today)));
  const need = off ? null : busNeedSec(ti.mondayKey, ti.dayKey);
  const sig = [Math.floor(now / 60), b.take.join(','), b.bufferMin, b.stop && b.stop.id, cell && JSON.stringify(cell.bus || null), need, busLive && busLive.at].join('|');
  if (sig === busTodaySig) return;
  busTodaySig = sig;

  document.getElementById('busTodayTitle').textContent = '오늘의 버스 · ' + (today.getMonth() + 1) + '/' + today.getDate() + ' (' + DOW[today.getDay()] + ')';
  const needEl = document.getElementById('busNeed');
  needEl.textContent = '';
  if (need !== null) needEl.append(document.createTextNode('예상 퇴근 '), busEl('b', '', fmt24(need)));
  else needEl.textContent = !ti.dayKey ? '주말' : off ? '근무 없음' : '';
  renderBusLive();

  box.innerHTML = '';
  if (!b.stop) { box.append(busEl('div', 'busempty', '지도에서 정류장을 누르면 그 정류장에 오는 버스를 볼 수 있어요.\n확인하고 저장하면 오늘 탈 버스와 퇴근 시각이 여기에 보여요.')); return; }
  if (!b.take.length) { box.append(busEl('div', 'busempty', '탈 버스가 없어요 — 위 정류장 이름을 눌러 체크하세요.')); return; }
  const all = busArrivalsOn(today).filter(x => x.at >= now);          // 아직 정류장에 안 온 버스
  const rec = busRecommend(all.filter(x => x.leave >= now), need);
  const start = need !== null ? Math.max(now, need - 30 * 60) : now;
  const list = all.filter(x => start === now || x.leave >= start || busIsPicked(cell && cell.bus, x)).slice(0, 24);
  if (!list.length) {
    box.append(busEl('div', 'busempty', all.length ? '예상 퇴근(' + fmt24(need) + ') 이후에는 버스가 없어요.' : '오늘 남은 버스가 없어요.'));
    return;
  }
  let focus = null;
  list.forEach(x => {
    const el = busOptionEl(x, { rec, pick: cell && !off ? cell.bus : null, need, now }, () => {
      if (!ti.dayKey || off) return;
      setDayBus(ti.mondayKey, ti.dayKey, busIsPicked(cell.bus, x) ? null : x);
    });
    if (x === rec || busIsPicked(cell && cell.bus, x)) focus = focus || el;
    box.append(el);
  });
  if (focus) box.scrollTop = Math.max(0, focus.offsetTop - box.offsetTop - 30);
}

function renderBusLive() {
  const take = new Set(busCfg().take);
  renderBusLiveLine(document.getElementById('busLive'), busLive, a => take.has(a.no));
}
// '실시간 · 375 3분 (2정류장 전) …' 한 줄. keep: 보여줄 도착만 거르는 함수
function renderBusLiveLine(el, live, keep) {
  el.innerHTML = '';
  el.hidden = !live;
  if (!live) return;
  const rows = live.arrivals.filter(keep);
  if (!rows.length) { el.textContent = '실시간 · 지금 다가오는 버스 없음'; return; }
  const aged = (Date.now() - live.at) / 1000;
  el.append(busEl('b', '', '실시간'));
  el.title = '초록 시각 = 실시간 도착 예정, 흰 시각 = 시간표 추정';
  rows.slice(0, 6).forEach(a => {
    const min = Math.max(0, Math.round((a.sec - aged) / 60));
    const span = busEl('span');
    span.append(busEl('b', '', a.no), document.createTextNode(' ' + (min ? min + '분' : '곧 도착') + (a.prev ? ' (' + a.prev + '정류장 전)' : '')));
    el.append(span);
  });
}

// 정류장 순번으로 추정한 '기점→정류장 소요'(offset)는 수십 분씩 틀릴 수 있다. 지금 다가오는 버스의
// 실시간 도착 예정에 시간표 위상을 맞춰 offset 을 배차 간격 안에서 옮긴다. 고정 배차 모델이라
// 다른 날짜 시각에도 그대로 쓰도록 저장하고, 이미 고른 버스는 새 시간표의 가장 가까운 시각으로 맞춘다.
function calibrateBusRoutes(arrivals, baseSec) {
  const b = busCfg();
  const moved = busCalibrate(b.routes, arrivals, baseSec);
  b.liveFixAt = Date.now();
  if (moved.length) busSnapPicks(moved);
  scheduleSave();
  return moved.length > 0;
}
// routes 의 offset 을 실시간 도착에 맞춰 옮기고(저장 전 미리보기에도 사용), 옮긴 노선 목록을 돌려준다.
// 지금 시간표에서 실시간 도착 예정과 가장 가까운 시각을 찾아 그 차이만큼 옮긴다(출퇴근/평시 배차가 섞여도 동작).
function busCalibrate(routes, arrivals, baseSec) {
  const today = new Date();
  const moved = [];
  routes.forEach(r => {
    const a = arrivals.find(x => busLiveMatch(r, x));          // 가장 먼저 오는 버스(도착순 정렬)
    const times = busRouteTimes(r, today);
    if (!a || times.length < 2) return;
    const obs = Math.round((baseSec + a.sec) / 60) * 60;      // 정류장 도착 예정(초, 분 단위)
    const i = times.reduce((p, t, j) => (Math.abs(t - obs) < Math.abs(times[p] - obs) ? j : p), 0);
    const step = Math.abs(times[Math.min(i + 1, times.length - 1)] - times[Math.max(i - 1, 0)]) / (i > 0 && i < times.length - 1 ? 2 : 1);
    if (Math.abs(obs - times[i]) > step) return;            // 운행 시간 밖(막차 뒤 등) — 보정하지 않음
    let off = Math.round(r.offset || 0) + Math.round((obs - times[i]) / 60);
    while (off < 0) off += Math.round(step / 60);
    if (off !== r.offset) { r.offset = off; moved.push(r); }
  });
  return moved;
}
// 오늘 이후로 고른 버스 중 보정된 노선은 새 시간표에서 가장 가까운 시각으로 옮긴다(배차 절반 이내).
function busSnapPicks(routes) {
  const todayStr = ymd(new Date());
  Object.keys(state.weeks).forEach(mondayKey => {
    DAYS.forEach(([key]) => {
      const cell = state.weeks[mondayKey][key];
      const r = cell && cell.bus && routes.find(x => x.no === cell.bus.route);
      const date = busDateOf(mondayKey, key);
      const at = r ? parseTimeToSec(cell.bus.at) : null;
      if (at === null || ymd(date) < todayStr) return;
      const times = busRouteTimes(r, date);
      const near = times.reduce((p, t) => (p === null || Math.abs(t - at) < Math.abs(p - at) ? t : p), null);
      const step = (times[1] - times[0]) || 0;
      if (near !== null && near !== at && Math.abs(near - at) <= step / 2) cell.bus.at = fmt24(near);
    });
  });
}

// bus_arrivals 응답 → { at(ms), base(받은 시각, 하루 초), arrivals }
function busLiveFrom(res) {
  const n = new Date();
  return { at: n.getTime(), base: n.getHours() * 3600 + n.getMinutes() * 60 + n.getSeconds(), arrivals: res.arrivals || [] };
}

// TAGO 정류장 + 키가 있을 때만 실시간 도착을 받아 시간표를 보정한다. 준비가 안 됐으면 null.
async function fetchBusLive() {
  const b = busCfg();
  if (!busLiveCapable(b.stop) || !busHasKey() || !apiReady('bus_arrivals')) return null;
  let res = null;
  try { res = await pywebview.api.bus_arrivals(b.stop); } catch (e) { res = { status: 'error', message: String(e) }; }
  if (!res || res.status !== 'ok') return res || { status: 'error', message: '응답 없음' };
  busLive = busLiveFrom(res);
  if (calibrateBusRoutes(busLive.arrivals, busLive.base)) {
    if (viewMode === 'bus') renderBusSide();
    recompute();
  } else renderBusSrc();
  return res;
}

// 버스 화면을 보는 동안 1분마다 실시간 도착 갱신(+ 보정)
async function refreshBusLive() {
  clearTimeout(busLiveTimer);
  busLiveTimer = null;
  // 방금(50초 안) 받은 실시간이 있으면 다시 부르지 않는다 — 배포 키 하루 호출 한도를 아끼려고
  const fresh = busLive && Date.now() - busLive.at < 50000;
  const res = viewMode !== 'bus' ? null : fresh ? { status: 'ok' } : await fetchBusLive();
  if (!res || res.status !== 'ok') {
    busLive = null;
    if (res) setBusStatus('실시간 도착 조회 실패: ' + (res.message || '알 수 없음'), 'err');
  }
  busLiveError = res && res.status !== 'ok' ? res.message || '알 수 없음' : '';
  busTodaySig = '';
  renderBusToday();
  renderBusLiveTab();
  if (res && viewMode === 'bus') busLiveTimer = setTimeout(refreshBusLive, 60000);
}

// 공공데이터포털 키는 항상 config.json 의 busApiKey(exe 에 묶임)를 쓴다 — 화면에서 넣는 곳은 없고 값은 Python 에만 있다.
function busHasKey() { return busDefaultKey; }
async function loadBusInfo() {
  try {
    if (apiReady('bus_info')) busDefaultKey = !!(await pywebview.api.bus_info()).defaultKey;
  } catch (e) { busDefaultKey = false; }
}
function onBusBufferChange(e) {
  const v = parseInt(e.target.value, 10);
  busCfg().bufferMin = isNaN(v) ? 5 : Math.max(0, Math.min(60, v));
  e.target.value = busCfg().bufferMin;
  scheduleSave();
  renderBusSide();
  recompute();
}

/* ---------------- TTree 휴가/출장 ---------------- */
let ttreeLookupsLoaded = false;
let ttreeLookups = null;
let ttreeBusy = false;

function apiReady(name) {
  return window.pywebview && pywebview.api && pywebview.api[name];
}
function setTtreeMessage(msg, cls) {
  const el = document.getElementById('ttreeMessage');
  if (!el) return;
  el.className = 'ttree-message' + (cls ? ' ' + cls : '');
  el.textContent = msg || '';
}
function setTtreeBusy(busy) {
  ttreeBusy = busy;
  ['ttreeLogin', 'ttreeReload', 'ttreeLookupReload', 'ttreePreview', 'ttreeSubmit', 'ttreeKind'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = busy;
  });
}
// 휴가·출장 탭 진입 훅. 조회 함수들이 busy 가드를 공유하므로 순서대로 기다린다.
async function enterTtree() {
  setTtreeDefaults();
  if (!ttreeLookupsLoaded) await loadTtreeLookups();
  await loadTtreeStatus();
}
function todayYmdInput() { return ymd(new Date()); }
function compactTimeForTtree(v) {
  const s = parseTimeToSec(v);
  if (s === null) return '';
  return fmt24(s);
}
function ttreePresetTime(key, fallback) {
  const p = (ttreeLookups && ttreeLookups.preset) || {};
  const v = p[key];
  if (v && String(v).length >= 4) return String(v).slice(0, 2) + ':' + String(v).slice(2, 4);
  return fallback;
}
function setTtreeDefaults() {
  const today = todayYmdInput();
  ['ttreeLeaveStart', 'ttreeLeaveEnd', 'ttreeBsrpStart', 'ttreeBsrpEnd'].forEach(id => {
    const el = document.getElementById(id);
    if (el && !el.value) el.value = today;
  });
  const bsrpStart = document.getElementById('ttreeBsrpStartTime');
  const bsrpEnd = document.getElementById('ttreeBsrpEndTime');
  if (bsrpStart && !bsrpStart.value) bsrpStart.value = '09:00';
  if (bsrpEnd && !bsrpEnd.value) bsrpEnd.value = '18:00';
  applyTtreeRangeTimes();
  const monday = new Date();
  monday.setDate(monday.getDate() - (monday.getDay() + 6) % 7);
  const sunday = new Date(monday); sunday.setDate(sunday.getDate() + 6);
  document.getElementById('ttreeOvertimeStart').value = ymd(monday);
  document.getElementById('ttreeOvertimeEnd').value = ymd(sunday);
}
function fillSelect(sel, items, valueKey, textKey, emptyText) {
  if (!sel) return;
  sel.innerHTML = '';
  if (emptyText) {
    const opt = document.createElement('option');
    opt.value = ''; opt.textContent = emptyText;
    sel.appendChild(opt);
  }
  (items || []).forEach(item => {
    const opt = document.createElement('option');
    opt.value = item[valueKey] || '';
    opt.textContent = item[textKey] || item[valueKey] || '';
    if (item.approvalLineName) opt.dataset.approvalLineName = item.approvalLineName;
    if (item.rangeTypeJson) opt.dataset.rangeTypeJson = item.rangeTypeJson;
    sel.appendChild(opt);
  });
}
function populateTtreeLookups(res) {
  ttreeLookups = res;
  ttreeLookupsLoaded = true;
  const cap = document.getElementById('ttreeCaption');
  if (cap && res.user) cap.textContent = (res.user.userName || res.user.userId || '') + ' · ' + (res.user.deptName || '');
  const classSel = document.getElementById('ttreeLeaveClass');
  // 대부분 '일반'(연차)에서 신청하므로 placeholder 없이 일반을 기본 선택
  fillSelect(classSel, res.leaveClasses || [], 'code', 'name');
  const generalCl = (res.leaveClasses || []).find(c => c.name === '일반');
  if (classSel && generalCl) classSel.value = generalCl.code;
  updateTtreeLeaveTypes();
  const approvalSel = document.getElementById('ttreeApproval');
  fillSelect(approvalSel, res.approvals || [], 'id', 'name', '결재선 선택');
  ttreeBalance = res.leaveBalance || [];
  autoSetTtreeApproval();
  renderTtreeBalance();
  setTtreeDefaults();
  applyTtreeKind();
}
async function loadTtreeLookups() {
  if (ttreeBusy) return;
  setTtreeBusy(true);
  setTtreeMessage('TTree 코드/결재선 불러오는 중...');
  let res = null;
  try {
    res = apiReady('ttree_lookups') ? await pywebview.api.ttree_lookups() : { status: 'error', message: '앱 브리지 없음' };
  } catch (e) { res = { status: 'error', message: String(e) }; }
  setTtreeBusy(false);
  if (res && res.status === 'ok') {
    populateTtreeLookups(res);
    setTtreeMessage('TTree 코드/결재선 로딩 완료', 'ok');
  } else if (res && res.status === 'login_required') {
    setTtreeMessage((res && res.message) || 'TTree 로그인이 필요합니다. 로그인 버튼을 눌러 주세요.', 'err');
  } else {
    setTtreeMessage('TTree 코드 로딩 실패: ' + ((res && res.message) || '알 수 없음'), 'err');
  }
}
async function doTtreeLogin() {
  if (ttreeBusy) return;
  setTtreeBusy(true);
  setTtreeMessage('열린 브라우저에서 TTree에 로그인해 주세요.');
  let res = null;
  try {
    res = apiReady('ttree_login') ? await pywebview.api.ttree_login() : { status: 'error', message: '앱 브리지 없음' };
  } catch (e) { res = { status: 'error', message: String(e) }; }
  setTtreeBusy(false);
  if (res && res.status === 'ok') {
    setTtreeMessage('TTree 로그인 완료. 코드와 현황을 다시 불러옵니다.', 'ok');
    ttreeLookupsLoaded = false;
    await loadTtreeLookups();
    await loadTtreeStatus();
  } else if (res && res.status === 'login_required') {
    setTtreeMessage(res.message || 'TTree 로그인 후 다시 시도해 주세요.', 'err');
  } else if (res && res.status === 'cancelled') {
    setTtreeMessage('TTree 로그인이 취소되었습니다.');
  } else {
    setTtreeMessage('TTree 로그인 실패: ' + ((res && res.message) || '알 수 없음'), 'err');
  }
}
function statusClass(code) {
  code = String(code || '');
  if (code === '900') return 'ok';
  if (code === '800') return 'deny';
  if (code === '999') return 'cancel';
  return 'pending';
}
function ttreePeriod(item) {
  if (item.kind === 'overtime') return item.registeredDate ? '신청일 ' + item.registeredDate : '신청일 미확인';
  const d = item.startDate === item.endDate ? item.startDate : (item.startDate + ' ~ ' + item.endDate);
  const t = item.startTime || item.endTime ? ' ' + [item.startTime, item.endTime].filter(Boolean).join('~') : '';
  return (d || '-') + t;
}
function renderTtreeList(id, items, emptyText) {
  const box = document.getElementById(id);
  if (!box) return;
  box.innerHTML = '';
  if (!items || !items.length) {
    const empty = document.createElement('div');
    empty.className = 'ttree-empty';
    empty.textContent = emptyText;
    box.appendChild(empty);
    return;
  }
  // TTree API 응답 순서가 뒤죽박죽이라 시작일(+시작시간) 최신순으로 정렬해서 보여준다
  const sorted = items.slice().sort((a, b) =>
    String(b.startDate || '').localeCompare(String(a.startDate || '')) ||
    String(b.startTime || '').localeCompare(String(a.startTime || '')));
  sorted.forEach(item => {
    const row = document.createElement('div');
    row.className = 'ttree-row';
    const main = document.createElement('div');
    main.className = 'ttree-row-main';
    const title = document.createElement('strong');
    title.textContent = item.title || '-';
    const sub = document.createElement('span');
    const extras = [ttreePeriod(item), item.dayCount ? item.dayCount + '일' : '', item.customer || '', item.location || '', item.reason || '', item.rejectionReason ? '반려 사유: ' + item.rejectionReason : ''].filter(Boolean);
    sub.textContent = extras.join(' · ');
    main.appendChild(title); main.appendChild(sub);
    const badge = document.createElement('span');
    badge.className = 'ttree-badge ' + statusClass(item.statusCode);
    badge.textContent = item.statusName || item.statusCode || '-';
    row.appendChild(main); row.appendChild(badge);
    box.appendChild(row);
  });
}
/* ---- TTree 신청 내역 → 근태 그리드 반영 ---- */
// 0.5일 휴가는 시간대로 반차 방향 판별(오전에 쉬면 오전반차), 그 외 휴가는 연차.
// 구분명에 '무급'이 들어가면 (무급) 반차로 표시 구분.
function ttreeLeaveGridType(item) {
  const dc = parseFloat(item.dayCount);
  const st = parseTimeToSec(item.startTime);
  const unpaid = String(item.title || '').indexOf('무급') !== -1;
  if (dc === 0.5 && st !== null) {
    const base = st < 12 * 3600 ? '오전반차' : '오후반차';
    return unpaid ? base + '(무급)' : base;
  }
  return '연차';
}
// 반려(800)/취소(999)를 뺀 휴가·출장을 근태 주간 데이터에 채운다.
//  - 휴가: 유형이 비어 있는 날만 설정 (사용자가 고른 유형은 유지)
//  - 출장/교육: 출근·퇴근이 비어 있는 칸만 신청 시간으로 채움 (EHR 실측·직접 입력 우선)
function applyTtreeToWorkGrid(res) {
  if (!res || res.status !== 'ok') return;
  const items = [];
  (res.leave || []).forEach(it => items.push(Object.assign({ _kind: 'leave' }, it)));
  (res.businessTrip || []).forEach(it => items.push(Object.assign({ _kind: 'bsrp' }, it)));
  let changed = 0;
  items.forEach(it => {
    const code = String(it.statusCode || '');
    if (code === '800' || code === '999') return;
    if (!it.startDate) return;
    const start = new Date(it.startDate + 'T00:00:00');
    const end = new Date((it.endDate || it.startDate) + 'T00:00:00');
    if (isNaN(start.getTime()) || isNaN(end.getTime())) return;
    for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
      const idx = (d.getDay() + 6) % 7;
      if (idx > 4) continue;                       // 주말 제외
      const dayStr = ymd(d);
      if (holidayMap[dayStr]) continue;            // 공휴일은 이미 8h 인정
      const wk = weekData(ymd(mondayOf(d)));
      const c = wk[DAYS[idx][0]];
      if (it._kind === 'leave') {
        if (c.type) continue;
        const t = ttreeLeaveGridType(it);
        c.type = t;
        const fx = halfdayFixed(t);
        if (fx) c[fx.field] = normalizeClockValue(fx.value);
        changed++;
      } else {
        if (c.type === '연차' || c.type === '휴일') continue;   // 종일 휴무로 지정된 날은 시간 채움 무의미
        const inV = normalizeClockValue(it.startTime);
        const outV = normalizeClockValue(it.endTime);
        let touched = false;
        if (!c.type) { c.type = '출장'; touched = true; }        // 출장 마커 표시 (사용자 지정 유형은 유지)
        if (inV && parseTimeToSec(c.in) === null) { c.in = inV; touched = true; }
        if (outV && parseTimeToSec(c.out) === null) { c.out = outV; touched = true; }
        if (touched) changed++;
      }
    }
  });
  if (!changed) return;
  scheduleSave();
  fillInputsFromState();
  recompute();
  const status = document.getElementById('statusLine');
  if (status) { status.className = 'status ok'; status.textContent = 'TTree 휴가·출장 ' + changed + '일 근태 반영'; }
}

async function loadTtreeStatus() {
  if (ttreeBusy) return;
  setTtreeBusy(true);
  setTtreeMessage('TTree 신청 현황 조회 중...');
  let res = null;
  try {
    res = apiReady('ttree_status') ? await pywebview.api.ttree_status() : { status: 'error', message: '앱 브리지 없음' };
  } catch (e) { res = { status: 'error', message: String(e) }; }
  setTtreeBusy(false);
  if (res && res.status === 'ok') {
    renderTtreeList('ttreeLeaveList', res.leave || [], '조회된 휴가 신청이 없습니다.');
    renderTtreeList('ttreeBsrpList', res.businessTrip || [], '조회된 출장 신청이 없습니다.');
    renderTtreeList('ttreeOvertimeList', res.overtime || [], res.warnings?.length ? '연장근무 현황 조회 실패' : '조회된 연장근무 신청이 없습니다.');
    if (res.leaveBalance) { ttreeBalance = res.leaveBalance; renderTtreeBalance(); }
    applyTtreeToWorkGrid(res);
    const range = document.getElementById('ttreeStatusRange');
    if (range && res.range) range.textContent = res.range.begin + ' ~ ' + res.range.end;
    setTtreeMessage(res.warnings?.length ? res.warnings.join(' ') : 'TTree 신청 현황 조회 완료', res.warnings?.length ? 'err' : 'ok');
  } else if (res && res.status === 'login_required') {
    setTtreeMessage((res && res.message) || 'TTree 로그인이 필요합니다. 로그인 버튼을 눌러 주세요.', 'err');
  } else {
    setTtreeMessage('TTree 현황 조회 실패: ' + ((res && res.message) || '알 수 없음'), 'err');
  }
}
function updateTtreeLeaveTypes() {
  const classCode = document.getElementById('ttreeLeaveClass')?.value || '';
  const cl = ((ttreeLookups && ttreeLookups.leaveClasses) || []).find(x => x.code === classCode);
  fillSelect(document.getElementById('ttreeLeaveType'), cl ? cl.types : [], 'code', 'name', '휴가 구분 선택');
  autoSetTtreeApproval();
  renderTtreeBalance();
}
// 결재선 자동 선택 — TTree와 동일한 규칙.
// 휴가: 구분에 지정된 결재선(approvalLineName) → 없으면 선호 결재선 → 첫 항목.
// 출장/교육: 구분별 매핑(교육은 2차 결재까지 필요) → 선호 결재선 → 첫 항목.
// (백엔드 build_leave_payload 의 _select_approval_id 와 같은 우선순위)
const TTREE_PREFERRED_LINES = ['차상위자', '차상위자 - 최고관리자'];
const TTREE_BSRP_APPROVAL = { bsrp: ['차상위자'], edu: ['차상위자 - 최고관리자'] };
function autoSetTtreeApproval() {
  const approvalSel = document.getElementById('ttreeApproval');
  if (!approvalSel || !approvalSel.options.length) return;
  const kind = document.getElementById('ttreeKind')?.value || 'leave';
  let wantedNames = [];
  if (kind === 'leave') {
    const typeSel = document.getElementById('ttreeLeaveType');
    const opt = typeSel && typeSel.options[typeSel.selectedIndex];
    const name = (opt && opt.dataset.approvalLineName) || '';
    if (name) wantedNames = [name];
  } else {
    const bsrpType = document.getElementById('ttreeBsrpType')?.value || 'bsrp';
    wantedNames = TTREE_BSRP_APPROVAL[bsrpType] || [];
  }
  const byName = name => Array.from(approvalSel.options).find(o => o.value && o.textContent === name);
  let target = null;
  for (const name of wantedNames.concat(TTREE_PREFERRED_LINES)) {
    target = byName(name);
    if (target) break;
  }
  if (!target) target = Array.from(approvalSel.options).find(o => o.value);
  if (target) approvalSel.value = target.value;
  renderTtreeApprovalDetail();
}
/* ---- 잔여 휴가 표시 ---- */
let ttreeBalance = [];
function ttreeFmtDay(v) {
  const n = Math.round(Number(v) * 100) / 100;
  return isNaN(n) ? String(v) : String(n);
}
function ttreeClassName(code) {
  const c = ((ttreeLookups && ttreeLookups.leaveClasses) || []).find(x => x.code === code);
  return (c && c.name) || code;
}
function renderTtreeBalance() {
  const el = document.getElementById('ttreeLeaveBalance');
  if (el) {
    const cls = document.getElementById('ttreeLeaveClass')?.value || '';
    const row = ttreeBalance.find(b => b.classCode === cls) ||
      (ttreeBalance.length === 1 ? ttreeBalance[0] : null);
    el.textContent = row
      ? '잔여 ' + ttreeFmtDay(row.remain) + '일 · 총 ' + ttreeFmtDay(row.total) + '일 중 ' + ttreeFmtDay(row.used) + '일 사용'
      : '—';
  }
  const sum = document.getElementById('ttreeBalanceSummary');
  if (sum) {
    sum.textContent = ttreeBalance.length
      ? ttreeBalance.map(b => ttreeClassName(b.classCode) + ' 잔여 ' + ttreeFmtDay(b.remain) + '일 (총 ' + ttreeFmtDay(b.total) + ' · 사용 ' + ttreeFmtDay(b.used) + ')').join('  ·  ')
      : '';
  }
}
function renderTtreeApprovalDetail() {
  const box = document.getElementById('ttreeApprovalDetail');
  const id = document.getElementById('ttreeApproval')?.value || '';
  if (!box) return;
  const lines = document.getElementById('ttreeKind')?.value === 'overtime' ? ttreeLookups?.overtime?.approvals : ttreeLookups?.approvals;
  const line = (lines || []).find(x => x.id === id);
  if (!line || !line.details || !line.details.length) {
    box.textContent = '';
    return;
  }
  box.textContent = line.details.map(d => (d.ordNo || '') + '차 ' + (d.userName || d.userId || '')).join(' → ');
}
function applyTtreeKind() {
  const kind = document.getElementById('ttreeKind')?.value || 'leave';
  const leave = document.getElementById('ttreeLeaveForm');
  const bsrp = document.getElementById('ttreeBsrpForm');
  const title = document.getElementById('ttreeTitle');
  if (leave) leave.hidden = kind !== 'leave';
  if (bsrp) bsrp.hidden = kind !== 'bsrp';
  const overtimeForm = document.getElementById('ttreeOvertimeForm');
  if (overtimeForm) overtimeForm.hidden = kind !== 'overtime';
  if (title) title.textContent = { leave: '휴가 신청', bsrp: '출장/교육 신청', overtime: '연장근무 신청' }[kind] || '휴가 신청';
  // 결재선 목록: 연장근무는 TTree가 지정한 전용 결재선(고정이면 변경 불가), 그 외는 일반 결재선
  const approval = document.getElementById('ttreeApproval');
  const policy = ttreeLookups?.overtime;
  if (approval) {
    const previous = approval.value;
    fillSelect(approval, (kind === 'overtime' ? policy?.approvals : ttreeLookups?.approvals) || [], 'id', 'name', '결재선 선택');
    approval.disabled = kind === 'overtime' && !!policy?.fixedApprovalId;
    if ([...approval.options].some(x => x.value === previous)) approval.value = previous;
  }
  if (kind === 'overtime') {
    if (approval && policy?.fixedApprovalId) approval.value = policy.fixedApprovalId;
    if (policy?.startDate) document.getElementById('ttreeOvertimeStart').value = policy.startDate;
    if (policy?.endDate) document.getElementById('ttreeOvertimeEnd').value = policy.endDate;
    document.getElementById('ttreeOvertimeNote').textContent = policy?.enabled ? '이번 주 월~일 · 12시간 고정' + (policy.fixedApprovalId ? ' · 회사 지정 결재선' : '') : (policy?.message || '폼 항목 갱신으로 연장근무 설정을 불러와 주세요.');
    document.getElementById('ttreeOvertimeRestartRow').hidden = !policy?.canRestart;
    if (!policy?.canRestart) document.getElementById('ttreeOvertimeRestart').checked = false;
    renderTtreeApprovalDetail();
  } else {
    autoSetTtreeApproval();
  }
  document.getElementById('ttreeConfirm').checked = false;
  document.getElementById('ttreePreviewBox').textContent = '';
  applyTtreeBsrpRange();
}
function closeTtreePanel() {
  selectView('work');
}
function applyTtreeBsrpRange() {
  const range = document.getElementById('ttreeBsrpRange')?.value || 'DAY';
  const startDate = document.getElementById('ttreeBsrpStart');
  const endDate = document.getElementById('ttreeBsrpEnd');
  if (!endDate || !startDate) return;
  if (range !== 'RANGE') {
    endDate.value = startDate.value;
    endDate.disabled = true;
  } else {
    endDate.disabled = false;
  }
}
function applyTtreeRangeTimes() {
  const range = document.getElementById('ttreeLeaveRange')?.value || 'DAY';
  const start = document.getElementById('ttreeLeaveStartTime');
  const end = document.getElementById('ttreeLeaveEndTime');
  const endDate = document.getElementById('ttreeLeaveEnd');
  const startDate = document.getElementById('ttreeLeaveStart');
  if (!start || !end) return;
  if (range === 'AM_HALF_VAC') {
    start.value = ttreePresetTime('amHalfVacBgnTime', '08:00');
    end.value = ttreePresetTime('amHalfVacEndTime', '12:00');
  } else if (range === 'PM_HALF_VAC') {
    start.value = ttreePresetTime('pmHalfVacBgnTime', '13:00');
    end.value = ttreePresetTime('pmHalfVacEndTime', '17:00');
  } else if (range === 'DAY' || range === 'RANGE') {
    start.value = ttreePresetTime('vacBgnTime', '08:00');
    end.value = ttreePresetTime('vacEndTime', '17:00');
  }
  const custom = range === 'CUSTOM';
  start.disabled = !custom && (range === 'DAY' || range === 'RANGE');
  end.disabled = !custom && (range === 'DAY' || range === 'RANGE');
  if (range !== 'RANGE' && endDate && startDate) endDate.value = startDate.value;
  if (endDate) endDate.disabled = range !== 'RANGE';
}
function collectTtreeLeaveDraft() {
  return {
    vcatnClCd: document.getElementById('ttreeLeaveClass')?.value || '',
    vcatnSeCd: document.getElementById('ttreeLeaveType')?.value || '',
    rangeCode: document.getElementById('ttreeLeaveRange')?.value || 'DAY',
    startDate: document.getElementById('ttreeLeaveStart')?.value || '',
    endDate: document.getElementById('ttreeLeaveEnd')?.value || '',
    startTime: compactTimeForTtree(document.getElementById('ttreeLeaveStartTime')?.value || ''),
    endTime: compactTimeForTtree(document.getElementById('ttreeLeaveEndTime')?.value || ''),
    reason: document.getElementById('ttreeLeaveReason')?.value || '',
    sanctnId: document.getElementById('ttreeApproval')?.value || '',
  };
}
function collectTtreeBsrpDraft() {
  applyTtreeBsrpRange();
  return {
    bsrpType: document.getElementById('ttreeBsrpType')?.value || 'bsrp',
    startDate: document.getElementById('ttreeBsrpStart')?.value || '',
    endDate: document.getElementById('ttreeBsrpEnd')?.value || '',
    startTime: compactTimeForTtree(document.getElementById('ttreeBsrpStartTime')?.value || ''),
    endTime: compactTimeForTtree(document.getElementById('ttreeBsrpEndTime')?.value || ''),
    customer: document.getElementById('ttreeBsrpCustomer')?.value || '',
    location: document.getElementById('ttreeBsrpLocation')?.value || '',
    reason: document.getElementById('ttreeBsrpReason')?.value || '',
    sanctnId: document.getElementById('ttreeApproval')?.value || '',
  };
}
function currentTtreeDraft() {
  if (document.getElementById('ttreeKind')?.value === 'overtime') return {
    startDate: document.getElementById('ttreeOvertimeStart').value,
    endDate: document.getElementById('ttreeOvertimeEnd').value,
    reason: document.getElementById('ttreeOvertimeReason').value,
    sanctnId: document.getElementById('ttreeApproval').value,
    restartWork: document.getElementById('ttreeOvertimeRestart').checked,
  };
  return (document.getElementById('ttreeKind')?.value || 'leave') === 'leave' ? collectTtreeLeaveDraft() : collectTtreeBsrpDraft();
}
function showTtreePreview(res) {
  const box = document.getElementById('ttreePreviewBox');
  if (!box) return;
  if (!res || res.status !== 'ok') {
    box.textContent = '오류: ' + ((res && res.message) || '알 수 없음');
    return;
  }
  box.textContent = res.summary || (res.endpoint + '\n' + res.contentType + '\n\n' + JSON.stringify(res.payload, null, 2));
}
async function previewTtreeRequest() {
  if (ttreeBusy) return;
  const kind = document.getElementById('ttreeKind')?.value || 'leave';
  const draft = currentTtreeDraft();
  let res = null;
  try {
    if (kind === 'leave') res = apiReady('ttree_preview_leave') ? await pywebview.api.ttree_preview_leave(draft) : { status: 'error', message: '앱 브리지 없음' };
    else if (kind === 'overtime') res = apiReady('ttree_preview_overtime') ? await pywebview.api.ttree_preview_overtime(draft) : { status: 'error', message: '앱 브리지 없음' };
    else res = apiReady('ttree_preview_bsrp') ? await pywebview.api.ttree_preview_bsrp(draft) : { status: 'error', message: '앱 브리지 없음' };
  } catch (e) { res = { status: 'error', message: String(e) }; }
  if (kind === 'overtime' && res?.summary) res.summary += '\n결재선: ' + document.getElementById('ttreeApproval').selectedOptions[0]?.textContent;
  showTtreePreview(res);
  setTtreeMessage(res && res.status === 'ok' ? '미리보기 생성 완료' : '미리보기 실패: ' + ((res && res.message) || '알 수 없음'), res && res.status === 'ok' ? 'ok' : 'err');
}
async function submitTtreeRequest() {
  if (ttreeBusy) return;
  if (!document.getElementById('ttreeConfirm')?.checked) {
    setTtreeMessage('실제 신청 전 확인 체크박스를 선택해 주세요.', 'err');
    return;
  }
  const kind = document.getElementById('ttreeKind')?.value || 'leave';
  const label = { leave: '휴가', bsrp: '출장/교육', overtime: '이번 주 12시간 연장근무' }[kind] || '휴가';
  if (kind === 'overtime' && !ttreeLookups?.overtime?.enabled) {
    setTtreeMessage(ttreeLookups?.overtime?.message || '폼 항목 갱신으로 연장근무 설정을 확인해 주세요.', 'err');
    return;
  }
  const draft = currentTtreeDraft();
  const detail = kind === 'overtime' ? '\n' + draft.startDate + ' ~ ' + draft.endDate + '\n사유: ' + draft.reason + '\n결재선: ' + document.getElementById('ttreeApproval').selectedOptions[0]?.textContent + (draft.restartWork ? '\n신청과 함께 근무를 재시작합니다.' : '') : '';
  if (!window.confirm('TTree에 실제 ' + label + ' 신청을 등록할까요?' + detail)) return;
  setTtreeBusy(true);
  setTtreeMessage('TTree에 실제 ' + label + ' 신청 전송 중...');
  let res = null;
  try {
    if (kind === 'leave') res = apiReady('ttree_submit_leave') ? await pywebview.api.ttree_submit_leave(draft) : { status: 'error', message: '앱 브리지 없음' };
    else if (kind === 'overtime') res = apiReady('ttree_submit_overtime') ? await pywebview.api.ttree_submit_overtime(draft) : { status: 'error', message: '앱 브리지 없음' };
    else res = apiReady('ttree_submit_bsrp') ? await pywebview.api.ttree_submit_bsrp(draft) : { status: 'error', message: '앱 브리지 없음' };
  } catch (e) { res = { status: 'error', message: String(e) }; }
  setTtreeBusy(false);
  if (res && res.status === 'ok') {
    document.getElementById('ttreeConfirm').checked = false;
    showTtreePreview({ status: 'ok', summary: res.summary, endpoint: kind === 'leave' ? 'POST /vcatn' : 'POST /work/bsrp', contentType: kind === 'leave' ? 'application/json' : 'application/x-www-form-urlencoded', payload: res.payload || {} });
    setTtreeMessage((res.message || label + ' 신청 완료') + ' · 현황을 다시 조회합니다.', 'ok');
    loadTtreeStatus();
  } else if (res && res.status === 'duplicate') {
    showTtreePreview({ status: 'ok', summary: res.message, endpoint: kind === 'leave' ? 'POST /vcatn' : 'POST /work/bsrp', contentType: '', payload: res.payload || {} });
    setTtreeMessage(res.message || '중복 신청으로 전송하지 않았습니다.', 'err');
  } else {
    setTtreeMessage(label + ' 신청 실패: ' + ((res && res.message) || '알 수 없음'), 'err');
  }
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
  if (state.settings.bus) {          // TAGO 로 저장했던 경기도 정류장 → 경기도 API 정류장 모양으로
    const b = state.settings.bus;
    b.stop = busGbisShape(b.stop);
    if (Array.isArray(b.nearby)) b.nearby = b.nearby.map(busGbisShape);
  }
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
  closeBusPicker();
  buildGrid();
  fillInputsFromState();
  updateWeekLabel();
  recompute();
}

/* ---------------- 지출결의서 결재 도우미 ---------------- */
let approvalInit = false;
let approvalPayday = null;
let approvalPaySrc = '';


function initApprovalPanel() {
  const sel = document.getElementById('apprMonth');
  if (sel && !sel.options.length) {
    for (let m = 1; m <= 12; m++) {
      const o = document.createElement('option'); o.value = m; o.textContent = m + '월'; sel.appendChild(o);
    }
    sel.value = String(new Date().getMonth() + 1);
  }
  const nameInp = document.getElementById('apprName');
  if (nameInp && state && state.settings) nameInp.value = state.settings.approvalName || '';
  if (sel) sel.addEventListener('change', () => { approvalPayday = null; approvalPaySrc = ''; refreshApprovalSheet(); });
  if (nameInp) nameInp.addEventListener('input', () => {
    if (state && state.settings) { state.settings.approvalName = nameInp.value.trim(); scheduleSave(); }
    refreshApprovalSheet();
  });
}

function apprTitleText(month, name) {
  return month + '월 지출결의서(개인경비) - ' + (name && name.trim() ? name.trim() : '000');
}

function refreshApprovalSheet() {
  const month = parseInt(document.getElementById('apprMonth').value, 10) || (new Date().getMonth() + 1);
  const name = (document.getElementById('apprName').value || '').trim();
  document.getElementById('apprTitle').textContent = apprTitleText(month, name);
  document.getElementById('apprPayee').textContent = name || '—';
  document.getElementById('apprPayday').textContent = approvalPayday || '—';
  document.getElementById('apprPaySrc').textContent = approvalPaySrc || '';
}

function setApprMsg(msg, cls) {
  const el = document.getElementById('apprMsg');
  if (el) { el.textContent = msg || ''; el.className = 'mealcaption' + (cls ? ' ' + cls : ''); }
}
function setApprBusy(busy) {
  ['apprLookup', 'apprOpen'].forEach(id => { const el = document.getElementById(id); if (el) el.disabled = busy; });
}

async function lookupApprovalPayday() {
  const month = parseInt(document.getElementById('apprMonth').value, 10);
  setApprBusy(true); setApprMsg('지급예정일 조회 중…');
  let res = null;
  try {
    if (apiReady('approval_payday')) res = await pywebview.api.approval_payday(month);
    else res = { status: 'error', message: '데스크톱 앱에서만 가능' };
  } catch (e) { res = { status: 'error', message: String(e) }; }
  setApprBusy(false);
  if (!res || res.status === 'login_required') { setApprMsg('EHR 로그인이 필요해요 — 상단 ‘로그인’ 후 다시.', 'err'); return; }
  if (res.status === 'ok' && res.payday) {
    approvalPayday = res.payday;
    approvalPaySrc = res.sourceTitle ? '(' + res.sourceTitle + ')' : '';
    setApprMsg('지급예정일 조회 완료', 'ok');
  } else if (res.status === 'not_found') {
    approvalPayday = null; approvalPaySrc = ''; setApprMsg(res.message || '지급일정 공지를 못 찾았어요.', 'err');
  } else if (res.status === 'no_date') {
    approvalPayday = null; setApprMsg('공지에서 개인경비 날짜를 못 찾았어요 — 직접 확인해주세요.', 'err');
  } else { setApprMsg('조회 실패: ' + (res.message || '알 수 없음'), 'err'); }
  refreshApprovalSheet();
}

async function openApprovalForm() {
  const month = parseInt(document.getElementById('apprMonth').value, 10);
  const name = (document.getElementById('apprName').value || '').trim();
  if (approvalPayday == null) await lookupApprovalPayday();   // 없으면 먼저 조회
  const payload = { title: apprTitleText(month, name), payee: name, payday: approvalPayday || '' };
  setApprBusy(true); setApprMsg('결재 폼 여는 중… 열린 창에서 검토·카드입력·제출하세요.');
  let res = null;
  try {
    if (apiReady('approval_prefill')) res = await pywebview.api.approval_prefill(payload);
    else res = { status: 'error', message: '데스크톱 앱에서만 가능' };
  } catch (e) { res = { status: 'error', message: String(e) }; }
  setApprBusy(false);
  if (!res) { setApprMsg('실패', 'err'); return; }
  if (res.status === 'login_required') setApprMsg('EHR 로그인이 필요해요 — 상단 ‘로그인’ 후 다시.', 'err');
  else if (res.status === 'started') setApprMsg((res.message || '결재 창을 열었어요.') + ' 열린 창에서 카드내역·검토·제출을 진행하세요.', 'ok');
  else if (res.status === 'ok') setApprMsg('폼 창을 닫았어요. (자동채움 ' + (res.filled && res.filled.title ? '완료' : '일부') + ')', 'ok');
  else setApprMsg('실패: ' + (res.message || '알 수 없음'), 'err');
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
  document.querySelectorAll('#sideNav .navitem').forEach(b =>
    b.addEventListener('click', () => selectView(b.dataset.view)));
  document.getElementById('busSearchForm').addEventListener('submit', searchBusPlace);
  document.getElementById('busScan').addEventListener('click', scanBusStops);
  document.getElementById('busBuffer').addEventListener('change', onBusBufferChange);
  document.getElementById('busTabToday').addEventListener('click', () => showBusTab('today'));
  document.getElementById('busTabLive').addEventListener('click', () => showBusTab('live'));
  document.getElementById('busTabStop').addEventListener('click', () => showBusTab('stop'));
  document.getElementById('busPrevSave').addEventListener('click', saveBusPreview);
  document.getElementById('busStopEdit').addEventListener('click', () => { if (busCfg().stop) previewBusStop(busCfg().stop); });
  document.getElementById('busBuffer').addEventListener('keydown', e => { if (e.key === 'Enter') e.target.blur(); });
  document.addEventListener('mousedown', onBusOutsideClick);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeBusPicker(); document.getElementById('busPlaces').hidden = true; } });
  document.getElementById('mealReload').addEventListener('click', reloadMeal);
  document.getElementById('mealOrigin').addEventListener('click', openMealOrigin);
  document.getElementById('calReload').addEventListener('click', fetchCal);
  document.getElementById('calPrev').addEventListener('click', () => calGoMonth(calShiftMonth(calMonth, -1)));
  document.getElementById('calNext').addEventListener('click', () => calGoMonth(calShiftMonth(calMonth, 1)));
  document.getElementById('calToday').addEventListener('click', () => calGoMonth(calCurrentMonth()));
  document.getElementById('ttreeCancel').addEventListener('click', closeTtreePanel);
  document.getElementById('ttreeLogin').addEventListener('click', doTtreeLogin);
  document.getElementById('ttreeReload').addEventListener('click', loadTtreeStatus);
  document.getElementById('ttreeLookupReload').addEventListener('click', loadTtreeLookups);
  document.getElementById('ttreeKind').addEventListener('change', applyTtreeKind);
  document.getElementById('ttreeLeaveClass').addEventListener('change', updateTtreeLeaveTypes);
  document.getElementById('ttreeLeaveType').addEventListener('change', autoSetTtreeApproval);
  document.getElementById('ttreeLeaveRange').addEventListener('change', applyTtreeRangeTimes);
  document.getElementById('ttreeLeaveStart').addEventListener('change', applyTtreeRangeTimes);
  document.getElementById('ttreeBsrpType').addEventListener('change', autoSetTtreeApproval);
  document.getElementById('ttreeBsrpRange').addEventListener('change', applyTtreeBsrpRange);
  document.getElementById('ttreeBsrpStart').addEventListener('change', applyTtreeBsrpRange);
  document.getElementById('ttreeApproval').addEventListener('change', renderTtreeApprovalDetail);
  document.getElementById('ttreePreview').addEventListener('click', previewTtreeRequest);
  document.getElementById('ttreeSubmit').addEventListener('click', submitTtreeRequest);
  document.getElementById('apprLookup').addEventListener('click', lookupApprovalPayday);
  document.getElementById('apprOpen').addEventListener('click', openApprovalForm);
  document.getElementById('calSelAll').addEventListener('click', () => calSetAll(true));
  document.getElementById('calSelNone').addEventListener('click', () => calSetAll(false));
  bindFormulaBar();
  const defaultIn = document.getElementById('defaultIn');
  if (defaultIn) {
    defaultIn.addEventListener('change', onDefaultInChange);
    defaultIn.addEventListener('keydown', e => { if (e.key === 'Enter') defaultIn.blur(); });
  }

  setInterval(recompute, 1000);

  // 앱 켤 때 자동 EHR 조회
  refreshEhr(false);
  // TTree 휴가·출장도 백그라운드로 한 번 조회해 근태에 반영 (로그인 안 돼 있으면 조용히 넘어감)
  if (apiReady('ttree_status')) loadTtreeStatus();
  // TAGO 키(개인/배포 기본)가 있으면 실시간 도착으로 퇴근 버스 시간표를 한 번 보정(버스 화면을 안 열어도 그리드 추천에 반영)
  loadBusInfo().then(fetchBusLive);
}

if (window.pywebview) {
  window.addEventListener('pywebviewready', init);
} else {
  window.addEventListener('pywebviewready', init);
  window.addEventListener('DOMContentLoaded', () => setTimeout(init, 300));
}
