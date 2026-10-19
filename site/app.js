/* Dashboard logic. Data files (built by scripts/build.py):
   data/meta.json   – lists (types, 시도/시군구, centroids), build stats
   data/cube.json   – [sidoIdx, sggIdx, typeIdx, status, permitYear, count]  (national view)
   data/close.json  – [sidoIdx, sggIdx, typeIdx, closeYear, permitYear, count] (national view)
   data/pts/<si>.json – {dongs:[[읍면동…] per 시군구], ris:{"g:d":[리…]},
                         rows:[[lat, lon, type, sgg, dong, ri, status, year, closeYear, name, addr, date, closed, approx, zone, bldg]]}
   data/tour/<si>.json – [[lat, lon, tourType, sgg, title, addr, img, contentId, lodgings≤1km, lodgings≤3km]]
   data/minbak.json – [sidoIdx, sggIdx, status, zone, bldg, count]  (외국인관광 도시민박, national view)
   data/visits.json – {q:[분기…], qdays, last, sido:[[외지인[], 외국인[]]…], sgg:[[[외지인[], 외국인[]]…]…]} (null = 자료 없음) */
(async function () {
  const initHash = new URLSearchParams(location.hash.slice(1)); // 공유 링크로 연 경우의 화면 상태
  const $ = id => document.getElementById(id);
  const fmt = n => n.toLocaleString('ko-KR');
  const pct = (a, b) => b ? (a / b * 100).toFixed(1) + '%' : '-';
  const esc = s => String(s ?? '').replace(/[&<>"]/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[m]));
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  // 배포마다 바뀌는 버전(app.js?v=…)을 데이터 요청에도 붙여 브라우저가 지난 데이터를 쓰지 않게 함
  const V = document.currentScript?.src.match(/[?&]v=([^&]+)/)?.[1];
  const getJSON = (u, fb) => fetch(V ? `${u}?v=${V}` : u).then(r => r.ok ? r.json() : fb).catch(() => fb);
  const [meta, cube, close, minbak, visits, arrivals, cubeq, closeq] = await Promise.all([getJSON('data/meta.json'), getJSON('data/cube.json', []), getJSON('data/close.json', []),
    getJSON('data/minbak.json', []), getJSON('data/visits.json', null), getJSON('data/arrivals.json', null), getJSON('data/cubeq.json', []), getJSON('data/closeq.json', [])]);
  const T = meta.types, CATS = meta.categories, S = meta.sido, ST = meta.status;
  const catOf = T.map(t => CATS.indexOf(t.cat));
  const col = c => css('--c' + c);
  const STC = ['var(--ok)', 'var(--pause)', 'var(--closed)'];
  const TOUR = meta.tour || { types: [], counts: [] };
  const TOUR_COL = ['#c4153c', '#8a4fb0', '#0e9aa7'];
  const yNow = new Date().getFullYear();

  const TL0 = 1990;
  const state = { sido: -1, sgg: -1, dong: -1, ri: -1, status: 0, types: new Set(T.map((_, i) => i)), tour: new Set([0]), tl: { mode: 'off', year: yNow }, sup: meta.visitors ? 'out' : 'tour', cmp: [], vt: { per: 'y', kind: '0' }, grp: -1, per: 'y' };
  let D = null; // detail file of the selected 시도, or the merged rows of the 합쳐 보기 regions
  let Dbase = null; // detail file of the selected 시도 (kept while D holds merged rows)
  const csvStore = {}; // CSV 내려받기용: id -> [머리글, 행들]
  let U = null; // 합쳐 보기: {regs:[{si, gi}], names} — 비교 목록의 지역을 하나로 묶어 숙박업 현황에 적용
  const detailCache = {}, tourCache = {};
  const loadDetail = si => (detailCache[si] ||= getJSON(`data/pts/${si}.json`, { dongs: [], ris: {}, rows: [] }));
  const loadTour = si => (tourCache[si] ||= getJSON(`data/tour/${si}.json`, []));
  $('updated').textContent = `마지막 갱신 ${meta.updated}.`;

  /* ---------- region dropdowns: 광역 → 기초 → 읍면동 → 리 ---------- */
  const level = () => U ? 1 : state.sido < 0 ? 0 : state.sgg < 0 ? 1 : state.dong < 0 ? 2 : state.ri < 0 ? 3 : 4;
  const dongList = () => (D && state.sgg >= 0) ? D.dongs[state.sgg] || [] : [];
  const riList = () => (D && state.dong >= 0) ? D.ris[`${state.sgg}:${state.dong}`] || [] : [];
  const opts = (sel, list, all) => { sel.innerHTML = `<option value="-1">${all}</option>` + list.map((n, i) => `<option value="${i}">${esc(n)}</option>`).join(''); sel.disabled = !list.length; };
  function fillBelow(from) {
    if (from <= 1) {
      opts($('f-sgg'), state.sido < 0 ? [] : S[state.sido].sgg, '전체');
      const gs = state.sido < 0 ? [] : S[state.sido].groups || [];
      $('f-sgg').options[0].insertAdjacentHTML('afterend', gs.map((g, k) => `<option value="g${k}">${esc(g.name)} (${g.gis.map(i => S[state.sido].sgg[i]).join('·')} 합계)</option>`).join(''));
    }
    if (from <= 2) opts($('f-dong'), dongList(), '전체');
    if (from <= 3) opts($('f-ri'), riList(), '전체');
  }
  $('f-sido').insertAdjacentHTML('beforeend', S.map((s, i) => `<option value="${i}">${esc(s.name)}</option>`).join(''));
  async function setSido(i) {
    state.sido = i; state.sgg = state.dong = state.ri = -1; state.grp = -1;
    const d = i < 0 ? null : await loadDetail(i);
    if (state.sido !== i) return;
    Dbase = d;
    if (U && !unionOn()) U = null;
    if (!U) D = d;
    $('f-sido').value = i; fillBelow(1); update(true);
  }
  function setSgg(i) {
    if (state.grp >= 0) { state.grp = -1; if (U && !unionOn()) { U = null; D = Dbase; } }
    state.sgg = i; state.dong = state.ri = -1; $('f-sgg').value = i; fillBelow(2); update(true); }
  function setDong(i) { state.dong = i; state.ri = -1; $('f-dong').value = i; fillBelow(3); update(true); }
  function setRi(i) { state.ri = i; $('f-ri').value = i; update(true); }
  $('f-sido').onchange = e => setSido(+e.target.value);
  $('f-sgg').onchange = e => e.target.value[0] === 'g' ? setGroup(+e.target.value.slice(1)) : setSgg(+e.target.value);
  async function setGroup(k) { // 묶음(예: 광주시)을 합쳐 보기와 같은 방식으로 보여줍니다
    state.sgg = state.dong = state.ri = -1; state.grp = k;
    $('f-sgg').value = 'g' + k; fillBelow(2);
    await applyUnion();
  }
  $('f-dong').onchange = e => setDong(+e.target.value);
  $('f-ri').onchange = e => setRi(+e.target.value);
  $('f-status').onchange = e => { state.status = +e.target.value; update(false); };
  fillBelow(1);

  function regionName() {
    if (U && U.label) return U.label;
    if (U) return U.names.length > 3 ? `${U.names.slice(0, 3).join(', ')} 외 ${U.names.length - 3}곳` : U.names.join(', ');
    if (state.sido < 0) return '전국';
    const p = [S[state.sido].name];
    if (state.sgg >= 0) p.push(S[state.sido].sgg[state.sgg]);
    if (state.dong >= 0) p.push(dongList()[state.dong]);
    if (state.ri >= 0) p.push(riList()[state.ri]);
    return p.join(' ');
  }
  function childNames() {
    switch (level()) {
      case 0: return S.map(s => s.name);
      case 1: return U ? U.names : S[state.sido].sgg;
      case 2: return dongList();
      case 3: return riList();
      default: return [];
    }
  }
  const childLabel = () => U ? (U.label ? '기초' : '선택 지역') : ['광역', '기초', '읍·면·동', '리', ''][level()];

  /* ---------- type filter ---------- */
  // 대분류 체크박스로 한 번에 켜고 끄며, 소분류는 ▸ 를 눌러 펼칩니다.
  const catTypes = CATS.map((_, ci) => T.map((_, i) => i).filter(i => catOf[i] === ci));
  $('typelist').innerHTML = CATS.map((c, ci) => {
    const items = catTypes[ci];
    if (!items.length) return '';
    return `<div class="chk cathead"><input type="checkbox" id="c${ci}" data-c="${ci}" checked><label for="c${ci}"><span class="sw" style="background:var(--c${ci})"></span>${esc(c)}</label><span class="n" id="cn${ci}"></span>`
      + (items.length > 1 ? `<button class="fold" data-f="${ci}" aria-expanded="false" aria-label="${esc(c)} 소분류 펼치기">▸</button>` : '<span></span>') + '</div>'
      + `<div class="subtypes" id="sub${ci}" hidden>` + items.map(i =>
        `<div class="chk"><input type="checkbox" id="t${i}" data-i="${i}" checked><label for="t${i}">${esc(T[i].name)}</label><span class="n" id="tn${i}"></span></div>`).join('') + '</div>';
  }).join('');
  function syncTypeBoxes() {
    T.forEach((_, i) => { $('t' + i).checked = state.types.has(i); });
    catTypes.forEach((items, ci) => { const box = $('c' + ci); if (!box) return; const n = items.filter(i => state.types.has(i)).length;
      box.checked = n === items.length; box.indeterminate = n > 0 && n < items.length; });
  }
  $('typelist').addEventListener('change', e => {
    const t = e.target;
    if (t.dataset.c != null) for (const i of catTypes[+t.dataset.c]) t.checked ? state.types.add(i) : state.types.delete(i);
    else { const i = +t.dataset.i; t.checked ? state.types.add(i) : state.types.delete(i); }
    syncTypeBoxes(); update(false);
  });
  $('typelist').addEventListener('click', e => {
    const b = e.target.closest('button.fold'); if (!b) return;
    const sub = $('sub' + b.dataset.f), open = sub.hidden;
    sub.hidden = !open; b.textContent = open ? '▾' : '▸'; b.setAttribute('aria-expanded', String(open));
  });
  $('t-all').onclick = () => { T.forEach((_, i) => state.types.add(i)); syncTypeBoxes(); update(false); };
  $('t-none').onclick = () => { state.types.clear(); syncTypeBoxes(); update(false); };

  /* ---------- aggregation ----------
     scanOpen(fn(type, status, year, child, weight)), scanClose(fn(type, closeYear, child, weight)) */
  const inDetail = r => U || (state.sgg < 0 || r[3] === state.sgg) && (state.dong < 0 || r[4] === state.dong) && (state.ri < 0 || r[5] === state.ri);
  const childOfRow = r => [null, r[3], r[4], r[5], null][level()];
  function scanOpen(fn) {
    if (!D) { for (const r of cube) fn(r[2], r[3], r[4], r[0], r[5]); return; }
    for (const r of D.rows) if (inDetail(r)) fn(r[2], r[6], r[7], childOfRow(r), 1);
  }
  function scanClose(fn) {
    if (!D) { for (const r of close) fn(r[2], r[3], r[0], r[5]); return; }
    for (const r of D.rows) if (r[8] && inDetail(r)) fn(r[2], r[8], childOfRow(r), 1);
  }
  /* 기간: 연도별(최근 20년) 또는 분기별(최근 5년). 분기 키 = 연도*10 + 분기 (예: 20243) */
  const curQ = Math.ceil((new Date().getMonth() + 1) / 3);
  function periods() {
    const keys = [];
    if (state.per === 'q') { for (let y = yNow - 4; y <= yNow; y++) for (let q = 1; q <= 4; q++) if (y < yNow || q <= curQ) keys.push(y * 10 + q); }
    else for (let y = yNow - 19; y <= yNow; y++) keys.push(y);
    const q = state.per === 'q', last = keys[keys.length - 1];
    return { keys, q, label: k => q ? `${String(k).slice(2, 4)}Q${k % 10}` : String(k), title: k => q ? `${Math.floor(k / 10)}년 ${k % 10}분기` : `${k}년`,
      partial: k => k === last, span: q ? '최근 5년 · 분기별' : '최근 20년' };
  }
  const qk = d => d && d.length >= 7 ? +d.slice(0, 4) * 10 + Math.ceil(+d.slice(5, 7) / 3) : 0;
  function scanQ(open, closed) { // 분기별 인허가·폐업 (전국 보기는 cubeq/closeq, 지역을 고르면 상세 행의 날짜)
    if (!D) { for (const r of cubeq) open(r[2], r[3], r[4], r[5]); for (const r of closeq) closed(r[2], r[3], r[4]); return; }
    for (const r of D.rows) if (inDetail(r)) { open(r[2], r[6], qk(r[11]), 1); if (r[6] === 2 && r[12]) closed(r[2], qk(r[12]), 1); }
  }
  function agg() {
    const a = { total: 0, byType: T.map(() => 0), allType: T.map(() => 0), byYear: {}, byArea: {}, st: [0, 0, 0],
      stType: T.map(() => [0, 0, 0]), stArea: {}, openY: {}, closeY: {}, areaType: {}, areaYear: {} };
    scanOpen((t, s, y, ch, w) => {
      const okS = state.status < 0 || s === state.status;
      if (okS) a.allType[t] += w;
      if (!state.types.has(t)) return;
      a.st[s] += w; a.stType[t][s] += w;
      if (ch != null && ch >= 0) (a.stArea[ch] ||= [0, 0, 0])[s] += w;
      if (y) a.openY[y] = (a.openY[y] || 0) + w;
      if (!okS) return;
      a.total += w; a.byType[t] += w;
      if (ch != null && ch >= 0) {
        a.byArea[ch] = (a.byArea[ch] || 0) + w;
        (a.areaType[ch] ||= T.map(() => 0))[t] += w;
        if (y) { const ay = a.areaYear[ch] ||= {}; ay[y] = (ay[y] || 0) + w; }
      }
      if (y) (a.byYear[y] ||= CATS.map(() => 0))[catOf[t]] += w;
    });
    scanClose((t, cy, ch, w) => { if (state.types.has(t)) a.closeY[cy] = (a.closeY[cy] || 0) + w; });
    // 차트용 기간별 값: 연도별이면 위 값을 그대로, 분기별이면 따로 셈
    a.byP = a.byYear; a.openP = a.openY; a.closeP = a.closeY;
    if (state.per === 'q') {
      a.byP = {}; a.openP = {}; a.closeP = {};
      scanQ((t, s, k, w) => { if (!state.types.has(t) || !k) return; a.openP[k] = (a.openP[k] || 0) + w;
        if (state.status < 0 || s === state.status) (a.byP[k] ||= CATS.map(() => 0))[catOf[t]] += w; },
      (t, k, w) => { if (state.types.has(t) && k) a.closeP[k] = (a.closeP[k] || 0) + w; });
    }
    return a;
  }
  const natType = () => { const b = T.map(() => 0); let n = 0; for (const r of cube) if (state.status < 0 || r[3] === state.status) { b[r[2]] += r[5]; n += r[5]; } return [b, n]; };

  /* ---------- map ---------- */
  if (typeof maplibregl === 'undefined') $('map').innerHTML = '<p class="note" style="padding:16px">지도 라이브러리를 불러오지 못했습니다. 새로고침해 주세요.</p>';
  const map = typeof maplibregl === 'undefined' ? null : new maplibregl.Map({
    container: 'map', style: 'https://tiles.openfreemap.org/styles/positron', center: [127.8, 36.2], zoom: 5.6, attributionControl: { compact: true } });
  let mapReady = false;
  const empty = { type: 'FeatureCollection', features: [] };
  if (map) {
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    map.on('load', () => {
      mapReady = true;
      const dem = { type: 'raster-dem', tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'], encoding: 'terrarium', tileSize: 256, maxzoom: 14,
        attribution: '지형: <a href="https://registry.opendata.aws/terrain-tiles/" target="_blank">AWS Terrain Tiles</a>' };
      map.addSource('dem', dem);
      map.addSource('dem3d', { ...dem, attribution: undefined });
      const firstSymbol = (map.getStyle().layers.find(l => l.type === 'symbol') || {}).id;
      map.addLayer({ id: 'hillshade', type: 'hillshade', source: 'dem', paint: {
        'hillshade-exaggeration': .5, 'hillshade-shadow-color': '#46525c', 'hillshade-highlight-color': '#ffffff', 'hillshade-accent-color': '#5b6b5a' } }, firstSymbol);
      // 국립공원 경계: OpenStreetMap(build.py → park_areas.json). 금정산은 지정 도면을 따라 그린 근사 경계
      const font = (map.getStyle().layers.find(l => l.layout && l.layout['text-font']) || {}).layout?.['text-font'] || ['Noto Sans Regular'];
      map.addSource('park-areas', { type: 'geojson', data: empty });
      getJSON('data/park_areas.json', null).then(g => { if (!g) return; map.getSource('park-areas').setData(g);
        $('n-park').textContent = g.features.filter(f => f.geometry.type === 'Point').length + '곳'; });
      map.addLayer({ id: 'park-fill', type: 'fill', source: 'park-areas', paint: { 'fill-color': '#2e7d32', 'fill-opacity': .3 } }, firstSymbol);
      map.addLayer({ id: 'park-line', type: 'line', source: 'park-areas', paint: { 'line-color': '#1b5e20', 'line-opacity': .9,
        'line-width': ['interpolate', ['linear'], ['zoom'], 6, 1.2, 12, 2.6] } }, firstSymbol);
      map.addLayer({ id: 'park-label', type: 'symbol', source: 'park-areas', minzoom: 7, filter: ['==', ['geometry-type'], 'Point'], layout: { 'text-field': ['get', 'park'], 'text-font': font, 'text-size': 12 },
        paint: { 'text-color': '#1b5e20', 'text-halo-color': '#fff', 'text-halo-width': 1.5 } });
      // 교통시설 아이콘: 네모(철도역 = 보라, 공항 = 남색)
      const square = (fill, px) => {
        const c = document.createElement('canvas'); c.width = c.height = px; const g = c.getContext('2d');
        g.fillStyle = '#fff'; g.fillRect(0, 0, px, px); g.fillStyle = fill; g.fillRect(2, 2, px - 4, px - 4);
        return g.getImageData(0, 0, px, px);
      };
      map.addImage('sq-rail', square('#8e44ad', 20), { pixelRatio: 2 });
      map.addImage('sq-air', square('#1f3a93', 28), { pixelRatio: 2 });
      const nm = ['coalesce', ['get', 'name:ko'], ['get', 'name']];
      // 교통: 배경지도 벡터 타일(OpenMapTiles 스키마)의 공항·철도
      const vec = Object.entries(map.getStyle().sources).find(([, v]) => v.type === 'vector')?.[0];
      if (vec) {
        map.addLayer({ id: 'rail-line', type: 'line', source: vec, 'source-layer': 'transportation',
          filter: ['all', ['match', ['get', 'class'], ['rail', 'transit'], true, false], ['!', ['has', 'service']]],
          paint: { 'line-color': '#5d6d7e', 'line-opacity': .55, 'line-width': ['interpolate', ['linear'], ['zoom'], 6, .6, 12, 2] } }, firstSymbol);
        // 역 이름은 11레벨부터(그 아래는 네모만). 출입구는 제외
        map.addLayer({ id: 'rail-st', type: 'symbol', source: vec, 'source-layer': 'poi', minzoom: 9,
          filter: ['all', ['==', ['get', 'class'], 'railway'], ['!', ['match', ['get', 'subclass'], ['subway_entrance', 'train_station_entrance'], true, false]]],
          layout: { 'icon-image': 'sq-rail', 'icon-size': ['interpolate', ['linear'], ['zoom'], 9, .8, 14, 1.2], 'icon-allow-overlap': true,
            'text-field': ['step', ['zoom'], '', 11, nm], 'text-font': font, 'text-size': 11, 'text-offset': [0, .9], 'text-anchor': 'top', 'text-optional': true },
          paint: { 'text-color': '#5b2c6f', 'text-halo-color': '#fff', 'text-halo-width': 1.4 } });
        map.addLayer({ id: 'airports', type: 'symbol', source: vec, 'source-layer': 'aerodrome_label', filter: ['has', 'iata'],
          layout: { 'icon-image': 'sq-air', 'icon-allow-overlap': true, 'text-field': nm, 'text-font': font, 'text-size': 12,
            'text-offset': [0, 1], 'text-anchor': 'top', 'text-optional': true },
          paint: { 'text-color': '#1f3a93', 'text-halo-color': '#fff', 'text-halo-width': 1.5 } });
      }
      // 지하철·경전철: OpenStreetMap 노선 관계의 공식 색(build.py → subway.json). 있으면 배경지도의 도시철도 선은 숨김
      map.addSource('subway', { type: 'geojson', data: empty });
      map.addLayer({ id: 'subway', type: 'line', source: 'subway', layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': ['get', 'c'], 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 1.2, 11, 2.6, 15, 5], 'line-opacity': .9 } }, firstSymbol);
      getJSON('data/subway.json', null).then(g => {
        if (!g || !g.features.length) return;
        map.getSource('subway').setData(g);
        if (map.getLayer('rail-line')) map.setFilter('rail-line', ['all', ['==', ['get', 'class'], 'rail'], ['!', ['has', 'service']]]);
      });
      map.addSource('areas', { type: 'geojson', data: empty });
      map.addLayer({ id: 'areas', type: 'circle', source: 'areas', paint: {
        'circle-radius': ['interpolate', ['linear'], ['sqrt', ['get', 'n']], 0, 0, 10, 6, 60, 26],
        'circle-color': '#2a78d6', 'circle-opacity': .45, 'circle-stroke-color': '#fff', 'circle-stroke-width': 1 } });
      map.addSource('pts', { type: 'geojson', data: empty });
      map.addLayer({ id: 'pts', type: 'circle', source: 'pts', paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 2.2, 11, 3.6, 15, 6],
        'circle-color': ['match', ['get', 'c'], ...CATS.flatMap((_, i) => [i, col(i)]), '#888'],
        'circle-opacity': .85, 'circle-stroke-color': '#fff', 'circle-stroke-width': .6 } });
      // 역세권 반경(대중교통 탭에서 고른 역)
      map.addSource('stn-ring', { type: 'geojson', data: empty });
      map.addLayer({ id: 'stn-ring', type: 'line', source: 'stn-ring', filter: ['==', ['geometry-type'], 'LineString'],
        paint: { 'line-color': '#8e44ad', 'line-width': 1.6, 'line-dasharray': [3, 2] } });
      map.addLayer({ id: 'stn-ring-label', type: 'symbol', source: 'stn-ring', filter: ['==', ['geometry-type'], 'Point'],
        layout: { 'text-field': ['get', 'l'], 'text-font': font, 'text-size': 11, 'text-anchor': 'bottom' },
        paint: { 'text-color': '#5b2c6f', 'text-halo-color': '#fff', 'text-halo-width': 1.5 } });
      map.addSource('tour', { type: 'geojson', data: empty });
      map.addLayer({ id: 'tour', type: 'circle', source: 'tour', paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 3, 12, 5, 15, 7], 'circle-color': '#ffffff', 'circle-stroke-width': 2,
        'circle-stroke-color': ['match', ['get', 't'], ...TOUR_COL.flatMap((c, i) => [i, c]), '#333'] } });
      map.on('click', 'pts', e => {
        const p = e.features[0].properties;
        new maplibregl.Popup({ maxWidth: '280px' }).setLngLat(e.lngLat).setHTML(
          `<b>${esc(p.name)}</b><br>${esc(T[p.t].name)} · ${ST[p.s]}<br>${esc(p.addr)}<br><small>인허가 ${esc(p.date)}${p.closed ? ' · 폐업 ' + esc(p.closed) : ''}${p.ap ? ' · 위치는 동 단위 근사' : ''}</small>`).addTo(map);
      });
      map.on('click', 'tour', e => {
        const p = e.features[0].properties;
        new maplibregl.Popup({ maxWidth: '260px' }).setLngLat(e.lngLat).setHTML(
          `${p.img ? `<img src="${esc(p.img)}" alt="" style="width:100%;border-radius:4px;margin-bottom:6px">` : ''}<b>${esc(p.name)}</b><br>${esc(TOUR.types[p.t])}<br>${esc(p.addr)}<br>${p.n3 != null ? `영업 숙소 반경 1km ${fmt(p.n1)}곳 · 3km ${fmt(p.n3)}곳<br>` : ''}<small>출처: 한국관광공사 TourAPI</small>`).addTo(map);
      });
      map.on('click', 'areas', async e => { const p = e.features[0].properties; await setSido(p.si); setSgg(p.gi); });
      const pop = (ll, html) => new maplibregl.Popup({ maxWidth: '260px' }).setLngLat(ll).setHTML(html).addTo(map);
      map.on('click', 'airports', e => {
        const p = e.features[0].properties, nm = p['name:ko'] || p.name, k = kacOf(nm), n = k ? kac.years.length - 1 : 0;
        pop(e.lngLat, `<b>${esc(nm)}</b>${p.iata ? ` (${esc(p.iata)})` : ''}<br>${k ? `${kac.years[n]}년 여객 ${fmt(k.dom[n] + k.intl[n])}명 (국내선 ${fmt(k.dom[n])} · 국제선 ${fmt(k.intl[n])})<br>` : ''}<small>출처: OpenStreetMap${k ? ', 한국공항공사' : ''}</small>`);
      });
      map.on('click', 'subway', e => { const p = e.features[0].properties; pop(e.lngLat, `<b>${esc(p.n)}</b><br><small>출처: OpenStreetMap</small>`); });
      map.on('click', 'park-fill', e => {
        if (map.queryRenderedFeatures(e.point, { layers: ['pts', 'tour', 'areas', 'airports', 'rail-st', 'subway'].filter(l => map.getLayer(l)) }).length) return;
        const p = e.features[0].properties;
        pop(e.lngLat, `<b>${esc(p.park)}</b><br>지도상 면적 약 ${fmt(p.km2)}㎢<br><small>${p.src === 'traced' ? '지정 도면을 따라 그린 근사 경계 (지정 면적 66.859㎢) · 2026.3.3 지정' : '출처: OpenStreetMap 경계 (공식 지정 면적과 다를 수 있음)'}</small>`);
      });
      map.on('click', 'rail-st', e => { const p = e.features[0].properties; pop(e.lngLat, `<b>${esc(p['name:ko'] || p.name || '역')}</b><br><small>출처: OpenStreetMap</small>`); });
      for (const [ck, ls] of [['ck-park', ['park-fill', 'park-line', 'park-label']], ['ck-air', ['airports']], ['ck-rail', ['rail-line', 'rail-st', 'subway']]]) {
        const sync = () => ls.forEach(l => map.getLayer(l) && map.setLayoutProperty(l, 'visibility', $(ck).checked ? 'visible' : 'none'));
        $(ck).onchange = sync; sync();
      }
      for (const l of ['pts', 'areas', 'tour', 'airports', 'rail-st', 'subway', 'park-fill']) {
        map.on('mouseenter', l, () => { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', l, () => { map.getCanvas().style.cursor = ''; });
      }
      update(!!D);  // 공유 링크로 지역이 이미 골라져 있으면 그 지역으로
      if (state.cmp.length && !unionOn()) fitRegs(state.cmp);
    });
  }
  /* ---------- timeline ---------- */
  function tlRowOK(r) {
    const { mode, year: Y } = state.tl;
    if (mode === 'new') return r[7] === Y;
    if (mode === 'open') return r[7] > 0 && r[7] <= Y && !(r[6] === 2 && (!r[8] || r[8] <= Y));
    return state.status < 0 || r[6] === state.status;
  }
  function tlSeries() {
    // newY[y]: 인허가 수, openY[y]: 그 해 말 운영 중(인허가 ≤ y, 폐업 안 했거나 폐업연도 > y). 폐업일 없는 폐업은 제외.
    const n = yNow - TL0 + 1, newY = new Array(n).fill(0), diff = new Array(n + 1).fill(0);
    const ix = y => Math.max(0, Math.min(n, y - TL0));
    const span = (y, cy, w) => { if (!y || y > yNow) return; diff[ix(y)] += w; if (cy) diff[ix(cy)] -= w; };
    if (!D) {
      for (const r of cube) if (state.types.has(r[2]) && r[4] > 0) { if (r[4] >= TL0 && r[4] <= yNow) newY[r[4] - TL0] += r[5]; if (r[3] < 2) span(r[4], 0, r[5]); }
      for (const r of close) if (state.types.has(r[2]) && r[4] > 0) span(r[4], r[3], r[5]);
    } else {
      for (const r of D.rows) {
        if (!inDetail(r) || !state.types.has(r[2]) || !r[7]) continue;
        if (r[7] >= TL0 && r[7] <= yNow) newY[r[7] - TL0]++;
        if (r[6] === 2) { if (r[8]) span(r[7], r[8], 1); } else span(r[7], 0, 1);
      }
    }
    const openY = []; let acc = 0;
    for (let i = 0; i < n; i++) { acc += diff[i]; openY.push(acc); }
    return { newY, openY };
  }
  let tlCache = null;
  function drawTimeline() {
    const { newY, openY } = tlCache = tlSeries(), { mode, year } = state.tl, i0 = year - TL0;
    const vals = mode === 'new' ? newY : openY, n = vals.length;
    const W = 900, H = 120, L = 52, R = 8, Tp = 10, B = 20, iw = W - L - R, ih = H - Tp - B, bw = iw / n;
    const mx = Math.max(1, ...vals), step = niceStep(mx), top = Math.ceil(mx / step) * step;
    let s = '';
    for (let v = 0; v <= top; v += top) { const y = Tp + ih - v / top * ih; s += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y}" y2="${y}"/><text x="${L - 8}" y="${y + 4}" text-anchor="end">${fmt(v)}</text>`; }
    if (mode === 'new') vals.forEach((v, i) => { if (v) s += `<rect x="${L + i * bw + bw * .15}" y="${Tp + ih - v / top * ih}" width="${bw * .7}" height="${v / top * ih}" fill="var(--c0)" opacity="${i === i0 ? 1 : .55}"/>`; });
    else {
      const pts = vals.map((v, i) => `${L + i * bw + bw / 2},${Tp + ih - v / top * ih}`).join(' ');
      s += `<polygon points="${L + bw / 2},${Tp + ih} ${pts} ${L + (n - .5) * bw},${Tp + ih}" fill="var(--c0)" opacity=".15"/><polyline points="${pts}" fill="none" stroke="var(--c0)" stroke-width="2"/>`;
    }
    for (let y = TL0; y <= yNow; y += 5) s += `<text x="${L + (y - TL0) * bw + bw / 2}" y="${H - 4}" text-anchor="middle">${y}</text>`;
    if (mode !== 'off') { const x = L + i0 * bw + bw / 2; s += `<line x1="${x}" x2="${x}" y1="${Tp}" y2="${Tp + ih}" stroke="var(--fg)" stroke-width="1.5"/><circle cx="${x}" cy="${Tp + ih - vals[i0] / top * ih}" r="4" fill="var(--fg)"/>`; }
    s += `<rect id="tl-hit" x="${L}" y="${Tp}" width="${iw}" height="${ih}" fill="transparent" style="cursor:pointer"/>`;
    $('tl-chart').innerHTML = s;
    $('tl-chart-title').textContent = mode === 'new' ? `${regionName()} 연도별 신규 인허가` : `${regionName()} 연도별 운영 중 시설 수 (그 해 말 기준)`;
    $('tl-label').textContent = mode === 'off' ? '타임라인 꺼짐' : `${year}년 ${mode === 'new' ? '신규 인허가' : '운영 중'} ${fmt(vals[i0] || 0)}곳`;
  }
  function setTL(patch) {
    Object.assign(state.tl, patch);
    const on = state.tl.mode !== 'off';
    document.querySelectorAll('#tl-seg button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.m === state.tl.mode)));
    $('tl-year').disabled = $('tl-play').disabled = !on; $('tl-year').value = state.tl.year;
    $('f-status').disabled = on;
    $('map-sub').textContent = on ? '타임라인을 쓰는 동안 지도는 영업 상태 필터 대신 고른 연도 기준으로 보여줍니다.' : '전국 보기에서는 시군구별 원 크기가 시설 수입니다. 광역을 고르면 시설 하나하나가 점으로 나옵니다.';
    if (!on) stopPlay();
    drawTimeline(); drawMap(false);
  }
  let timer = null;
  const stopPlay = () => { clearInterval(timer); timer = null; $('tl-play').textContent = '▶ 재생'; };
  $('tl-seg').addEventListener('click', e => { const b = e.target.closest('button'); if (b) setTL({ mode: b.dataset.m }); });
  $('tl-year').min = TL0; $('tl-year').max = yNow; $('tl-year').value = yNow;
  $('tl-year').oninput = e => setTL({ year: +e.target.value });
  $('tl-play').onclick = () => {
    if (timer) { stopPlay(); return; }
    if (state.tl.year >= yNow) setTL({ year: 2000 });
    $('tl-play').textContent = '❚❚ 정지';
    timer = setInterval(() => { if (state.tl.year >= yNow) { stopPlay(); return; } setTL({ year: state.tl.year + 1 }); }, 800);
  };
  $('tl-chart').addEventListener('click', e => {
    if (state.tl.mode === 'off' || e.target.id !== 'tl-hit') return;
    const r = e.target.getBoundingClientRect(), f = (e.clientX - r.left) / r.width;
    setTL({ year: Math.max(TL0, Math.min(yNow, TL0 + Math.floor(f * (yNow - TL0 + 1)))) });
  });

  async function drawTour() {
    if (!mapReady) return;
    const regs = U ? U.regs : state.sido < 0 ? [] : [{ si: state.sido, gi: state.sgg }];
    if (!regs.length || !state.tour.size) { map.getSource('tour').setData(empty); return; }
    const key = JSON.stringify(regs), all = await Promise.all(regs.map(r => loadTour(r.si)));
    if (key !== JSON.stringify(U ? U.regs : state.sido < 0 ? [] : [{ si: state.sido, gi: state.sgg }])) return;
    const rows = regs.flatMap((g, k) => all[k].filter(r => g.gi < 0 || r[3] === g.gi));
    map.getSource('tour').setData({ type: 'FeatureCollection', features: rows.filter(r => state.tour.has(r[2])).map(r => ({
      type: 'Feature', geometry: { type: 'Point', coordinates: [r[1], r[0]] }, properties: { t: r[2], name: r[4], addr: r[5], img: r[6], n1: r[8], n3: r[9] } })) });
  }
  function drawMap(fly) {
    if (!mapReady) return;
    if (!D) {
      const cnt = {};
      const add = (r, n) => { cnt[r[0] + ':' + r[1]] = (cnt[r[0] + ':' + r[1]] || 0) + n; };
      const { mode, year: Y } = state.tl;
      for (const r of cube) {
        if (!state.types.has(r[2])) continue;
        if (mode === 'off' ? (state.status < 0 || r[3] === state.status) : mode === 'new' ? r[4] === Y : (r[3] < 2 && r[4] > 0 && r[4] <= Y)) add(r, r[5]);
      }
      if (mode === 'open') for (const r of close) if (state.types.has(r[2]) && r[4] > 0 && r[4] <= Y && r[3] > Y) add(r, r[5]);
      const feats = [];
      S.forEach((s, si) => s.sgg.forEach((g, gi) => { const c = s.sggc[gi], n = cnt[si + ':' + gi] || 0;
        if (c && n) feats.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [c[1], c[0]] }, properties: { n, si, gi } }); }));
      map.getSource('areas').setData({ type: 'FeatureCollection', features: feats });
      map.getSource('pts').setData(empty);
      drawTour();
      if (fly) map.flyTo({ center: [127.8, 36.2], zoom: 5.6 });
      return;
    }
    map.getSource('areas').setData(empty);
    const feats = [];
    for (const r of D.rows) {
      if (r[0] == null || !inDetail(r) || !state.types.has(r[2]) || !tlRowOK(r)) continue;
      feats.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [r[1], r[0]] },
        properties: { t: r[2], c: catOf[r[2]], s: r[6], name: r[9], addr: r[10], date: r[11], closed: r[12], ap: r[13] } });
    }
    map.getSource('pts').setData({ type: 'FeatureCollection', features: feats });
    drawTour();
    if (fly) fitLL(feats.map(f => f.geometry.coordinates), .01);
  }
  // 점들이 보이게 지도를 맞춤. 점이 많으면 양 끝 2%(좌표가 잘못 찍힌 시설, 멀리 떨어진 섬)는 범위에서 뺌
  function fitLL(pts, pad) {
    if (!mapReady || !pts.length) return;
    const q = (xs, f) => { xs.sort((a, b) => a - b); return xs[Math.min(xs.length - 1, Math.max(0, Math.round((xs.length - 1) * f)))]; };
    const cut = pts.length >= 40 ? .02 : 0, xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
    const b = [[q(xs, cut) - pad, q(ys, cut) - pad], [q(xs, 1 - cut) + pad, q(ys, 1 - cut) + pad]];
    map.fitBounds(b, { padding: 40, maxZoom: 14, duration: 800 });
  }
  // 비교 목록의 지역들이 한 화면에 들어오게 (시군구 중심점 기준, 전국이 끼어 있으면 전국)
  function fitRegs(regs) {
    if (!mapReady) return;
    if (regs.some(r => r.si < 0)) { map.flyTo({ center: [127.8, 36.2], zoom: 5.6 }); return; }
    fitLL(regs.flatMap(r => (gisOf(r) || S[r.si].sgg.map((_, gi) => gi)).map(gi => S[r.si].sggc[gi]).filter(Boolean).map(c => [c[1], c[0]])), .12);
  }

  /* ---------- render ---------- */
  function rowsHTML(entries, opt) {
    // entries: [{name, value, total?, color, mark?, extra}]
    const mx = Math.max(1e-9, ...entries.map(e => e.value), ...entries.map(e => e.mark || 0));
    return entries.map(e => `<${opt.button ? `button class="row" data-k="${e.k}"` : 'div class="row"'}><span class="nm">${e.color ? `<span class="sw" style="background:${e.color}"></span>` : ''}<span>${esc(e.name)}</span></span>
      <span class="track"><i style="width:${e.value / mx * 100}%;background:${e.color || 'var(--c0)'}"></i>${e.mark != null ? `<b style="left:calc(${e.mark / mx * 100}% - 1px)"></b>` : ''}</span>
      <span class="val">${e.label}<em>${e.extra}</em></span></${opt.button ? 'button' : 'div'}>`).join('');
  }
  function update(fly) {
    const a = agg(), [nb, nn] = natType(), names = childNames();
    const stLabel = state.status < 0 ? '전체 상태' : ST[state.status];
    T.forEach((_, i) => { $('tn' + i).textContent = fmt(a.allType[i]); });
    catTypes.forEach((items, ci) => { if ($('cn' + ci)) $('cn' + ci).textContent = fmt(items.reduce((p, i) => p + a.allType[i], 0)); });

    const topT = a.byType.map((v, i) => [v, i]).sort((x, y) => y[0] - x[0])[0];
    const recent = [yNow - 2, yNow - 1, yNow].reduce((s, y) => s + (a.byYear[y] ? a.byYear[y].reduce((p, q) => p + q, 0) : 0), 0);
    const topA = Object.entries(a.byArea).sort((x, y) => y[1] - x[1])[0];
    $('kpis').innerHTML = [
      [fmt(a.total), `${regionName()} · ${stLabel}`],
      [topT && topT[0] ? esc(T[topT[1]].name) : '-', topT && a.total ? `최다 업종 (${pct(topT[0], a.total)})` : '최다 업종'],
      [fmt(recent), `${yNow - 2}~${yNow}년 인허가`],
      [topA ? esc(names[topA[0]] ?? '-') : '-', topA ? `가장 많은 ${childLabel()} (${fmt(topA[1])})` : '하위 지역 없음'],
    ].map(k => `<div class="kpi"><b>${k[0]}</b><span>${k[1]}</span></div>`).join('');

    // share by sub-type
    const order = T.map((_, i) => i).filter(i => state.types.has(i)).sort((x, y) => a.byType[y] - a.byType[x]);
    $('share').innerHTML = rowsHTML(order.map(i => ({ name: T[i].name, value: a.byType[i] / (a.total || 1), color: `var(--c${catOf[i]})`,
      mark: D ? nb[i] / (nn || 1) : null, label: pct(a.byType[i], a.total), extra: fmt(a.byType[i]) + '곳' })), {}) || '<p class="note">선택한 업종이 없습니다.</p>';
    csvSet('share', ['업종', '시설 수', '비중(%)'], order.map(i => [T[i].name, a.byType[i], a.total ? (a.byType[i] / a.total * 100).toFixed(2) : '']));
    $('share-sub').textContent = topT && a.total ? `${regionName()}(${stLabel}) ${fmt(a.total)}곳 중 ${T[topT[1]].name} 비중이 ${pct(topT[0], a.total)}로 가장 큽니다.` : '';

    drawYears(a.byP);

    // ranking of child areas: 막대는 업종 구성(상위 8개 업종 + 기타)
    const ranks = Object.entries(a.byArea).sort((x, y) => y[1] - x[1]);
    const G = typeGroups(a, order), nm = k => names[k] ?? '(미상)', gN = (k, g) => g.ts.reduce((p, t) => p + ((a.areaType[k] || [])[t] || 0), 0);
    $('rank-title').textContent = level() >= 4 ? '하위 지역 없음' : `${regionName()} ${childLabel()}별 시설 수`;
    const top3 = ranks.slice(0, 3), top3n = top3.reduce((p, r) => p + r[1], 0);
    $('rank-sub').textContent = ranks.length > 3 ? `상위 3개 ${areaWord()}(${top3.map(r => nm(r[0])).join('·')})에 ${fmt(top3n)}곳, 전체의 ${pct(top3n, a.total)}가 모여 있습니다. 막대는 업종별 구성입니다.` : '';
    $('rank-legend').innerHTML = ranks.length ? G.map(g => `<span><i style="background:${g.col}"></i>${esc(g.name)}</span>`).join('') : '';
    const mxA = ranks.length ? ranks[0][1] : 1;
    $('rank').innerHTML = ranks.map(([k, v]) => {
      let acc = 0, segs = '';
      for (const g of G) { const n = gN(k, g); if (!n) continue;
        segs += `<i style="left:${acc / mxA * 100}%;width:${n / mxA * 100}%;background:${g.col};border-radius:0;box-shadow:inset -1.5px 0 var(--panel)"></i>`; acc += n; }
      return `<button class="row" data-k="${k}"><span class="nm"><span>${esc(nm(k))}</span></span><span class="track">${segs}</span><span class="val">${fmt(v)}<em>${pct(v, a.total)}</em></span></button>`;
    }).join('') || '<p class="note">더 작은 지역 단위가 없습니다.</p>';
    csvSet('rank', [childLabel() || '지역', '시설 수', '비중(%)', ...G.map(g => g.name)],
      ranks.map(([k, v]) => [nm(k), v, a.total ? (v / a.total * 100).toFixed(2) : '', ...G.map(g => gN(k, g))]));
    renderAreaTables(a, ranks, G, nm, gN);

    renderStatus(a, names);
    renderCompare();
    renderDemandVis();
    renderSupply();
    renderSummary(a, renderTrend(names));
    renderMinbak(names);
    renderStations();
    writeHash();
    drawTimeline();
    drawMap(fly);
  }
  // 상위 8개 업종은 각자 색, 나머지는 '기타'로 묶음 (지역별 막대·교차표 공용)
  const TYPE_PAL = ['var(--c0)', 'var(--c1)', 'var(--c2)', 'var(--c3)', 'var(--c4)', 'var(--c5)', 'var(--c6)', '#e04f5f'];
  function typeGroups(a, order) {
    const used = order.filter(t => a.byType[t] > 0), top = used.slice(0, 8), rest = used.slice(8);
    const G = top.map((t, i) => ({ name: T[t].name, ts: [t], col: TYPE_PAL[i] }));
    if (rest.length) G.push({ name: `기타 (${rest.slice(0, 4).map(t => T[t].name).join('·')}${rest.length > 4 ? ' 등' : ''})`, short: '기타', ts: rest, col: '#959ca6' });
    return G;
  }
  // 지역 × 연도 신규 인허가, 지역 × 업종 교차표 (상위 20개 지역)
  const areaWord = () => ({ 기초: '시군구', '': '지역' })[childLabel()] ?? childLabel();
  let ayMode = 'n';
  function renderAreaTables(a, ranks, G, nm, gN) {
    const rows = ranks.slice(0, 20), lbl = areaWord(), more = ranks.length > rows.length ? ` · 시설 수 상위 ${rows.length}개 ${lbl}` : '';
    const heat = (v, mx, rgb) => v ? `style="background:color-mix(in srgb,${rgb} ${Math.round(8 + v / mx * 62)}%,transparent)"` : '';
    $('ay-sec').hidden = $('at-sec').hidden = !rows.length;
    if (!rows.length) return;
    const years = []; for (let y = yNow - 14; y <= yNow; y++) years.push(y);
    const colT = years.map(y => rows.reduce((p, [k]) => p + ((a.areaYear[k] || {})[y] || 0), 0));
    const val = (k, j) => { const n = (a.areaYear[k] || {})[years[j]] || 0; return ayMode === 'n' ? n : colT[j] ? n / colT[j] : 0; };
    const mxY = Math.max(1e-9, ...rows.flatMap(([k]) => years.map((_, j) => val(k, j))));
    const cell = v => !v ? '·' : ayMode === 'n' ? fmt(v) : Math.round(v * 100) + '%';
    document.querySelectorAll('#ay-mode button').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.v === ayMode)));
    $('ay-title').textContent = `${lbl}별 연도별 신규 인허가, 최근 15년`;
    $('ay-table').innerHTML = `<thead><tr><th>${esc(lbl)}</th>${years.map(y => `<th>${y}${y === yNow ? '*' : ''}</th>`).join('')}</tr></thead><tbody>`
      + rows.map(([k]) => `<tr><td>${esc(nm(k))}</td>${years.map((_, j) => { const v = val(k, j); return `<td ${heat(v, mxY, 'var(--c1)')}>${cell(v)}</td>`; }).join('')}</tr>`).join('')
      + `<tr class="sum"><td>합계</td>${colT.map(v => `<td>${ayMode === 'n' ? fmt(v) : v ? '100%' : '·'}</td>`).join('')}</tr></tbody>`;
    $('ay-sub').textContent = `${regionName()} · ${state.status < 0 ? '전체 상태' : ST[state.status]} 시설의 인허가 연도${more}. ${yNow}년은 진행 중입니다.`;
    csvSet('ay-table', [lbl, ...years], rows.map(([k]) => [nm(k), ...years.map(y => (a.areaYear[k] || {})[y] || 0)]));
    const mxT = Math.max(1, ...rows.flatMap(([k]) => G.map(g => gN(k, g))));
    $('at-title').textContent = `${lbl}와 업종 교차표`;
    $('at-sub').textContent = `칸이 진할수록 그 ${lbl}에 그 업종이 많습니다${more}.`;
    $('at-table').innerHTML = `<thead><tr><th>${esc(lbl)}</th>${G.map(g => `<th><span class="sw" style="background:${g.col}"></span>${esc(g.short || g.name)}</th>`).join('')}<th>합계</th></tr></thead><tbody>`
      + rows.map(([k, v]) => `<tr><td>${esc(nm(k))}</td>${G.map(g => { const n = gN(k, g); return `<td ${heat(n, mxT, 'var(--c0)')}>${n ? fmt(n) : '·'}</td>`; }).join('')}<td><b>${fmt(v)}</b></td></tr>`).join('')
      + `<tr class="sum"><td>합계</td>${G.map(g => `<td>${fmt(rows.reduce((p, [k]) => p + gN(k, g), 0))}</td>`).join('')}<td>${fmt(rows.reduce((p, r) => p + r[1], 0))}</td></tr></tbody>`;
    csvSet('at-table', [lbl, ...G.map(g => g.name), '합계'], rows.map(([k, v]) => [nm(k), ...G.map(g => gN(k, g)), v]));
  }
  $('ay-mode').addEventListener('click', e => { const x = e.target.closest('button'); if (x) { ayMode = x.dataset.v; update(false); } });
  const drill = e => {
    const b = e.target.closest('button.row'); if (U || !b || b.dataset.k == null) return;
    const k = +b.dataset.k;
    [setSido, setSgg, setDong, setRi][level()]?.(k);
  };
  for (const id of ['rank', 'tr-up', 'tr-down', 'mb-area']) $(id).addEventListener('click', drill);

  /* ---------- 휴업·폐업 ---------- */
  function renderStatus(a, names) {
    const tot = a.st[0] + a.st[1] + a.st[2];
    $('st-kpis').innerHTML = ST.map((s, i) => `<div class="kpi"><b style="color:${STC[i]}">${fmt(a.st[i])}</b><span>${s} (${pct(a.st[i], tot)})</span></div>`).join('')
      + `<div class="kpi"><b>${pct(a.st[2], a.st[0] + a.st[2])}</b><span>누적 폐업률 (폐업 ÷ 영업+폐업)</span></div>`;
    $('st-sub').textContent = `${regionName()} · 선택한 업종 기준. 이 칸은 상단의 영업 상태 필터와 관계없이 세 상태를 모두 보여줍니다.`;
    drawOpenClose(a.openP, a.closeP);
    const order = T.map((_, i) => i).filter(i => state.types.has(i) && a.stType[i].some(Boolean))
      .sort((x, y) => (a.stType[y][2] + a.stType[y][1]) - (a.stType[x][2] + a.stType[x][1]));
    $('st-type').innerHTML = order.map(i => stackRow(T[i].name, a.stType[i], `var(--c${catOf[i]})`)).join('') || '<p class="note">자료가 없습니다.</p>';
    const areas = Object.entries(a.stArea).sort((x, y) => (y[1][1] + y[1][2]) - (x[1][1] + x[1][2]));
    $('st-area-title').textContent = level() >= 4 ? '' : `${childLabel()}별 휴업·폐업 (많은 순)`;
    $('st-area').innerHTML = areas.map(([k, v]) => stackRow(names[k] ?? '(미상)', v)).join('');
    csvSet('st-area', [childLabel() || '지역', '영업', '휴업', '폐업', '누적 폐업률(%)'], areas.map(([k, v]) => [names[k] ?? '(미상)', ...v, v[0] + v[2] ? (v[2] / (v[0] + v[2]) * 100).toFixed(2) : '']));
  }
  function stackRow(name, v, dot) {
    const n = v[0] + v[1] + v[2];
    return `<div class="row stack"><span class="nm">${dot ? `<span class="sw" style="background:${dot}"></span>` : ''}<span>${esc(name)}</span></span>
      <span class="stackbar">${v.map((x, i) => x ? `<span style="flex:${x};background:${STC[i]}" title="${ST[i]} ${fmt(x)}"></span>` : '').join('')}</span>
      <span class="val">폐업 ${pct(v[2], v[0] + v[2])}<em>휴업 ${fmt(v[1])}</em></span></div>`;
  }

  /* ---------- 관광객 추이 · 지역 비교 ----------
     비교 목록(state.cmp)이 비어 있으면 상단 필터의 지역 하나를 보여줍니다. 지역 = {si, gi} (si −1 전국, gi −1 광역 전체). */
  const short = n => n.replace(/(통합특별시|특별자치시|특별자치도|특별시|광역시)$/, '').replace(/^(.).(.)도$/, '$1$2');
  // 지역 = {si, gi} 또는 묶음 {si, gi: -1, grp}. gisOf: 해당 기초 목록 (null = 광역 전체)
  const gisOf = r => r.grp != null ? S[r.si].groups[r.grp].gis : r.gi >= 0 ? [r.gi] : null;
  const regLabel = r => r.si < 0 ? '전국' : r.grp != null ? `${short(S[r.si].name)} ${S[r.si].groups[r.grp].name}` : r.gi < 0 ? S[r.si].name : `${short(S[r.si].name)} ${S[r.si].sgg[r.gi]}`;
  const inReg = (r, si, gi) => r.si < 0 || (si === r.si && (!gisOf(r) || gisOf(r).includes(gi)));
  const curReg = () => state.sido < 0 ? { si: -1, gi: -1 } : state.grp >= 0 ? { si: state.sido, gi: -1, grp: state.grp } : { si: state.sido, gi: state.sgg };
  const regions = () => state.cmp.length ? state.cmp : [curReg()];
  const unionOn = () => $('cmp-union').checked && state.cmp.some(r => r.si >= 0);
  async function applyUnion() {
    // 합쳐 보기(비교 목록)가 켜져 있으면 그것을, 아니면 드롭다운에서 고른 묶음(예: 광주시)을 하나로 묶어 보여줍니다.
    // 묶음은 기초들로 풀고, 광역 전체가 담겨 있으면 그 광역의 기초는 중복이라 뺍니다. 전국 칩은 제외합니다.
    let regs, label = null;
    if (unionOn()) regs = state.cmp.filter(r => r.si >= 0).flatMap(r => r.grp != null ? gisOf(r).map(gi => ({ si: r.si, gi })) : [r]);
    else if (state.grp >= 0) { regs = gisOf(curReg()).map(gi => ({ si: state.sido, gi })); label = `${S[state.sido].name} ${S[state.sido].groups[state.grp].name}`; }
    else { if (U) { U = null; D = state.sido < 0 ? null : await loadDetail(state.sido); update(true); } return; }
    regs = regs.filter((r, i) => (r.gi < 0 || !regs.some(x => x.si === r.si && x.gi < 0)) && regs.findIndex(x => x.si === r.si && x.gi === r.gi) === i);
    const sis = [...new Set(regs.map(r => r.si))], det = await Promise.all(sis.map(loadDetail)), rows = [];
    regs.forEach((g, k) => { for (const x of det[sis.indexOf(g.si)].rows) if (g.gi < 0 || x[3] === g.gi) { const y = x.slice(); y[3] = k; y[4] = y[5] = -1; rows.push(y); } });
    U = { regs, names: regs.map(r => label ? S[r.si].sgg[r.gi] : regLabel(r)), label };
    D = { dongs: [], ris: {}, rows };
    update(true);
  }
  $('cmp-union').onchange = applyUnion;
  function renderChips() {
    $('union-wrap').hidden = !state.cmp.length;
    $('cmp-chips').innerHTML = state.cmp.map((r, i) => `<span class="chip"><span class="sw" style="background:var(--c${i})"></span>${esc(regLabel(r))}<button data-i="${i}" aria-label="${esc(regLabel(r))} 빼기">×</button></span>`).join('')
      + (state.cmp.length ? '<button class="btn" id="cmp-clear">비우기</button>' : '');
  }
  $('cmp-add').onclick = () => {
    const r = curReg();
    if (state.cmp.length >= 7 || state.cmp.some(x => regKey(x) === regKey(r))) return;
    state.cmp.push(r); renderChips(); renderCompare(); applyUnion(); writeHash();
    if (!unionOn()) fitRegs(state.cmp);
  };
  $('cmp-chips').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.id === 'cmp-clear') state.cmp = []; else state.cmp.splice(+b.dataset.i, 1);
    renderChips(); renderCompare(); applyUnion(); writeHash();
    if (!unionOn()) fitRegs(state.cmp.length ? state.cmp : [curReg()]);
  });
  const visOf = r => {
    if (!visits) return null;
    if (r.si >= 0 && r.grp == null) return r.gi < 0 ? visits.sido[r.si] : visits.sgg[r.si][r.gi];
    if (r.si >= 0) { // 묶음: 기초별 값을 더함 (자료가 없는 분기는 비움)
      const out = [visits.q.map(() => null), visits.q.map(() => null)];
      for (const gi of gisOf(r)) { const v = visits.sgg[r.si][gi]; if (v) for (let j = 0; j < 2; j++) v[j].forEach((x, i) => { if (x != null) out[j][i] = (out[j][i] || 0) + x; }); }
      return out;
    }
    const out = [visits.q.map(() => null), visits.q.map(() => null)];
    for (const v of visits.sido) if (v) for (let j = 0; j < 2; j++) v[j].forEach((x, i) => { if (x != null) out[j][i] = (out[j][i] || 0) + x; });
    return out;
  };
  function visPeriods(per = state.vt.per) {
    // 분기 또는 연도 단위로 묶고, 자료가 95% 미만인 기간(진행 중)을 표시
    const q = visits.q, daysIn = k => { const y = +k.slice(0, 4), leap = (y % 4 === 0) ? 1 : 0;
      return k.length === 4 ? 365 + leap : [90 + leap, 91, 92, 92][+k[5] - 1]; };
    const keys = [], idx = [];
    q.forEach((k, i) => { const key = per === 'y' ? k.slice(0, 4) : k; let j = keys.indexOf(key); if (j < 0) { keys.push(key); idx.push([]); j = keys.length - 1; } idx[j].push(i); });
    const partial = keys.map((k, j) => idx[j].reduce((a, i) => a + visits.qdays[i], 0) < daysIn(k) * .95);
    return { keys, idx, partial };
  }
  function visValues(v, P) {
    const k = state.vt.kind, val = i => k === 't' ? (v[0][i] == null || v[1][i] == null ? null : v[0][i] + v[1][i]) : v[+k][i];
    return P.idx.map(ii => { const xs = ii.map(val); return xs.some(x => x == null) ? null : xs.reduce((a, b) => a + b, 0); });
  }
  function lineChart(svg, tip, labels, series, opt) {
    // series: [{name, color, vals:[number|null]}]; opt.partial: [bool] (점선·빈 점), opt.unit(v) 축 단위
    const W = 900, H = +svg.getAttribute('viewBox').split(' ')[3], L = 64, R = 12, Tp = 14, B = 26, iw = W - L - R, ih = H - Tp - B;
    const all = series.flatMap(s => s.vals).filter(v => v != null), mx = Math.max(1, ...all);
    const step = niceStep(mx / opt.div) * opt.div, top = Math.ceil(mx / step) * step, n = labels.length, bw = iw / n;
    const X = i => L + i * bw + bw / 2, Y = v => Tp + ih - v / top * ih;
    let s = '';
    for (let v = 0; v <= top; v += step) s += `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end">${opt.unit(v)}</text>`;
    const every = Math.ceil(n / 12);
    labels.forEach((l, i) => { if ((n - 1 - i) % every === 0) s += `<text x="${X(i)}" y="${H - 8}" text-anchor="middle">${esc(l)}${opt.partial?.[i] ? '*' : ''}</text>`; });
    for (const se of series) {
      let d = '', dash = '';
      se.vals.forEach((v, i) => {
        if (v == null) return;
        const p = `${X(i)},${Y(v)}`, prev = se.vals[i - 1];
        if (opt.partial?.[i] && prev != null) dash += `M${X(i - 1)},${Y(prev)}L${p}`;
        else d += (prev == null ? 'M' : 'L') + p;
      });
      s += `<path d="${d}" fill="none" stroke="${se.color}" stroke-width="2.2"/><path d="${dash}" fill="none" stroke="${se.color}" stroke-width="2" stroke-dasharray="4 4"/>`;
      se.vals.forEach((v, i) => { if (v != null) s += `<circle cx="${X(i)}" cy="${Y(v)}" r="${n > 24 ? 2 : 3}" fill="${opt.partial?.[i] ? 'var(--panel)' : se.color}" stroke="${se.color}" stroke-width="1.5"/>`; });
    }
    labels.forEach((_, i) => { s += `<rect data-i="${i}" x="${L + i * bw}" y="${Tp}" width="${bw}" height="${ih}" fill="transparent"/>`; });
    svg.innerHTML = s;
    attachTip(svg, tip, i => `<b>${esc(labels[i])}${opt.partial?.[i] ? ' (진행 중)' : ''}</b><br>` + series.map(se => `<span class="sw" style="background:${se.color}"></span>${esc(se.name)} ${se.vals[i] == null ? '자료 없음' : opt.tip(se.vals[i])}`).join('<br>'));
  }
  function regStats(r) {
    const Y3 = yNow - 3, inW = y => y > Y3 && y <= yNow, st = [0, 0, 0], tr = { nw: 0, cl: 0, base: 0 }, py = {}, pq = {};
    for (const c of cube) {
      if (!state.types.has(c[2]) || !inReg(r, c[0], c[1])) continue;
      st[c[3]] += c[5];
      if (c[4]) py[c[4]] = (py[c[4]] || 0) + c[5];
      if (inW(c[4])) tr.nw += c[5];
      if (c[3] < 2 && c[4] && c[4] <= Y3) tr.base += c[5];
    }
    if (state.per === 'q') for (const c of cubeq) if (state.types.has(c[2]) && inReg(r, c[0], c[1])) pq[c[4]] = (pq[c[4]] || 0) + c[5];
    for (const c of close) {
      if (!state.types.has(c[2]) || !inReg(r, c[0], c[1])) continue;
      if (inW(c[3])) tr.cl += c[5];
      if (c[4] && c[4] <= Y3 && c[3] > Y3) tr.base += c[5];
    }
    let mb = 0;
    for (const m of minbak) if (m[2] === 0 && inReg(r, m[0], m[1])) mb += m[5];
    const sumV = vs => vs.reduce((a, v) => v ? [a[0] + v[0], a[1] + v[1]] : a, [0, 0]);
    const v = r.si < 0 ? sumV(S.map(s => s.vis)) : r.grp != null ? sumV(gisOf(r).map(gi => (S[r.si].visg || [])[gi])) : (r.gi < 0 ? S[r.si].vis : (S[r.si].visg || [])[r.gi]);
    return { st, tr, py: state.per === 'q' ? pq : py, mb, v };
  }
  function renderCompare() {
    const R = regions(), cols = R.map((_, i) => state.cmp.length ? `var(--c${i})` : 'var(--c0)');
    $('cmp-sub').textContent = state.cmp.length ? `비교 중: ${R.map(regLabel).join(', ')}` : `${regLabel(R[0])} · 상단 필터에서 지역을 고르고 '＋ 비교에 추가'를 누르면 여러 곳을 나란히 봅니다(광역 무관, 최대 7곳).`;
    document.querySelectorAll('#vt-per button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.v === state.vt.per)));
    document.querySelectorAll('#vt-kind button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.v === state.vt.kind)));
    const legend = R.map((r, i) => `<span><i style="background:${cols[i]}"></i>${esc(regLabel(r))}</span>`).join('');
    // 관광객 추이
    if (visits) {
      const P = visPeriods();
      const series = R.map((r, i) => { const v = visOf(r); return { name: regLabel(r), color: cols[i], vals: v ? visValues(v, P) : P.keys.map(() => null) }; });
      $('vt-legend').innerHTML = legend;
      lineChart($('vt'), $('vt-tip'), P.keys.map(k => state.vt.per === 'y' ? k : `${k.slice(2, 4)}.${k.slice(5)}Q`), series,
        { partial: P.partial, div: 1e4, unit: v => !v ? '0' : v >= 1e8 ? (v / 1e8).toFixed(v % 1e8 ? 1 : 0) + '억' : fmt(Math.round(v / 1e4)) + '만', tip: v => fmt(Math.round(v / 1e4)) + '만 명' });
      const L = visits.last;
      $('vt-note').textContent = `한국관광공사 데이터랩 휴대폰 기반 방문자 수(연인원), ${L.slice(0, 4)}.${L.slice(4, 6)}.${L.slice(6)}까지. *·점선은 아직 다 모이지 않은 기간입니다. 외국인은 기초 2019년, 광역 2020년부터 있어 합계는 그 이후만 그립니다.`
        + (R.some(r => r.si === S.findIndex(s => s.name === '인천광역시') && r.gi >= 0) ? ' 인천 신설 구는 2026년부터만 있습니다.' : '');
    } else { $('vt').innerHTML = ''; $('vt-note').textContent = '방문객 자료가 없습니다.'; }
    // 지표 표
    const stats = R.map(regStats), Y3 = yNow - 3;
    const pctS = (a, b) => b ? (a >= 0 ? '+' : '') + (a / b * 100).toFixed(1) + '%' : '-';
    $('cmp-table').innerHTML = `<thead><tr><th>지역</th><th>영업 숙소</th><th>연간 외지인</th><th>연간 외국인</th><th>외지인 100만 명당 숙소</th><th>외국인 100만 명당 숙소</th><th>${Y3 + 1}~${yNow} 증가율</th><th>누적 폐업률</th><th>영업 도시민박</th></tr></thead><tbody>`
      + R.map((r, i) => { const x = stats[i];
        return `<tr><td><span class="sw" style="background:${cols[i]}"></span>${esc(regLabel(r))}</td><td>${fmt(x.st[0])}</td>${[0, 1].map(j => `<td>${x.v && x.v[j] ? fmt(Math.round(x.v[j] / 1e4)) + '만' : '-'}</td>`).join('')}${[0, 1].map(j => `<td>${x.v && x.v[j] ? (x.st[0] / (x.v[j] / 1e6)).toFixed(1) : '-'}</td>`).join('')}<td>${pctS(x.tr.nw - x.tr.cl, x.tr.base)}</td><td>${pct(x.st[2], x.st[0] + x.st[2])}</td><td>${fmt(x.mb)}</td></tr>`; }).join('') + '</tbody>';
    csvSet('cmp-table', ['지역', '영업 숙소', '연간 외지인', '연간 외국인', '외지인 100만 명당 숙소', '외국인 100만 명당 숙소', `${Y3 + 1}~${yNow} 증가율(%)`, '누적 폐업률(%)', '영업 도시민박'],
      R.map((r, i) => { const x = stats[i];
        return [regLabel(r), x.st[0], x.v ? x.v[0] : '', x.v ? x.v[1] : '', ...[0, 1].map(j => x.v && x.v[j] ? (x.st[0] / (x.v[j] / 1e6)).toFixed(2) : ''),
          x.tr.base ? ((x.tr.nw - x.tr.cl) / x.tr.base * 100).toFixed(2) : '', x.st[0] + x.st[2] ? (x.st[2] / (x.st[0] + x.st[2]) * 100).toFixed(2) : '', x.mb]; }));
    // 연도별 신규 인허가
    const P = periods(), years = P.keys;
    $('cp-legend').innerHTML = legend;
    lineChart($('cp'), $('cp-tip'), years.map(P.label), R.map((r, i) => ({ name: regLabel(r), color: cols[i], vals: years.map(y => stats[i].py[y] || 0) })),
      { partial: years.map(P.partial), div: 1, unit: fmt, tip: v => fmt(v) + '곳' });
  }
  $('vt-per').addEventListener('click', e => { const b = e.target.closest('button'); if (b) { state.vt.per = b.dataset.v; renderCompare(); } });
  $('vt-kind').addEventListener('click', e => { const b = e.target.closest('button'); if (b) { state.vt.kind = b.dataset.v; renderCompare(); } });

  /* ---------- 한눈에 보기: 지금 고른 지역을 전국과 견준 3~4문장 ----------
     비교 표현은 ±20%를 넘을 때만 "높다/낮다"라고 씁니다. 업종 필터는 따르고, 영업 상태 필터와 관계없이 영업 중 시설 기준입니다. */
  function renderSummary(a, tr) {
    const Y3 = yNow - 3, isNat = !U && state.sido < 0;
    const nat = regStats({ si: -1, gi: -1 }), natT = T.map(() => 0);
    for (const r of cube) if (r[3] === 0 && state.types.has(r[2])) natT[r[2]] += r[5];
    const word = (x, y) => !y ? '' : x > y * 1.2 ? '보다 높습니다' : x < y * .8 ? '보다 낮습니다' : '과 비슷합니다';
    const big = v => v >= 1e8 ? (v / 1e8).toFixed(1) + '억' : fmt(Math.round(v / 1e4)) + '만';
    const pc = (x, d = 1) => (x * 100).toFixed(d) + '%', sg = x => (x >= 0 ? '+' : '') + pc(x);
    const lines = [];
    const N = a.st[0], top = T.map((_, i) => i).filter(i => state.types.has(i)).sort((x, y) => a.stType[y][0] - a.stType[x][0])[0];
    if (!N) { $('summary-title').textContent = `한눈에 보기 · ${regionName()}`; $('summary').innerHTML = '<li>영업 중인 시설이 없습니다.</li>'; return; }
    lines.push(`영업 중 숙소 ${fmt(N)}곳. 가장 많은 업종은 ${T[top].name}(${pc(a.stType[top][0] / N)}${isNat ? '' : `, 전국 ${pc(natT[top] / (nat.st[0] || 1))}`})입니다.`);
    if (tr.base) {
      const g = (tr.nw - tr.cl) / tr.base, ng = nat.tr.base ? (nat.tr.nw - nat.tr.cl) / nat.tr.base : null;
      lines.push(`${Y3 + 1}년 이후 신규 ${fmt(tr.nw)}곳·폐업 ${fmt(tr.cl)}곳으로, ${Y3}년 말보다 ${sg(g)} ${g >= 0 ? '늘었습니다' : '줄었습니다'}`
        + (isNat || ng == null ? '.' : ` (전국 ${sg(ng)}, ${g > ng + .05 ? '전국보다 빠름' : g < ng - .05 ? '전국보다 느림' : '전국과 비슷'}).`)
        + (tr.base < 30 ? ' 시설 수가 적어 비율이 크게 흔들릴 수 있습니다.' : ''));
    }
    const cr = a.st[0] + a.st[2] ? a.st[2] / (a.st[0] + a.st[2]) : null, ncr = nat.st[0] + nat.st[2] ? nat.st[2] / (nat.st[0] + nat.st[2]) : null;
    if (cr != null) lines.push(`누적 폐업률 ${pc(cr)}${isNat ? '.' : ` — 전국(${pc(ncr)})${word(cr, ncr)}.`}`);
    // 방문객 대비 공급: 방문객 자료가 시군구까지라 읍·면·동 이하에서는 생략
    const vOf = r => r.gi < 0 ? S[r.si].vis : (S[r.si].visg || [])[r.gi];
    const vp = U ? U.regs.map(vOf).reduce((s, v) => v ? [s[0] + v[0], s[1] + v[1]] : s, [0, 0])
      : isNat ? nat.v : level() <= 2 ? vOf({ si: state.sido, gi: state.sgg }) : null;
    if (VIS && vp && vp[0] && vp[1]) {
      const per = (n, v) => n / (v / 1e6), npo = per(nat.st[0], nat.v[0]), npf = per(nat.st[0], nat.v[1]);
      lines.push(`연간 외지인 ${big(vp[0])}·외국인 ${big(vp[1])} 명(연인원). 숙소는 외지인 100만 명당 ${per(N, vp[0]).toFixed(1)}곳, 외국인 100만 명당 ${per(N, vp[1]).toFixed(1)}곳`
        + (isNat ? '입니다.' : `입니다. 외지인 기준으로 전국(${npo.toFixed(1)}곳)${word(per(N, vp[0]), npo)}.`));
    }
    $('summary-title').textContent = `한눈에 보기 · ${regionName()}`;
    $('summary').innerHTML = lines.map(l => `<li>${esc(l)}</li>`).join('');
  }
  $('summary-copy').onclick = async () => {
    const text = $('summary-title').textContent + '\n' + [...$('summary').children].map(li => '- ' + li.textContent).join('\n');
    try { await navigator.clipboard.writeText(text); $('summary-copy').textContent = '복사됨 ✓'; } catch { prompt('복사하세요', text); }
    setTimeout(() => { $('summary-copy').textContent = '요약 복사'; }, 1500);
  };

  /* ---------- 대중교통: 역세권 숙소 (지하철·도시철도역 반경 안 영업 숙소, build.py → stations.json) ---------- */
  let STN = null, stnSel = -1;
  const kmLabel = km => km < 1 ? km * 1000 + 'm' : km + 'km';
  const stnCount = (s, k) => s[6].reduce((a, c) => a + (state.types.has(c[0]) ? c[k + 1] : 0), 0);
  function renderStations() {
    if (!STN || !STN.st.length) { $('stn-sub').textContent = '역 자료가 아직 없습니다. 다음 데이터 갱신 후 표시됩니다.'; $('stn-sel').disabled = true; return; }
    const regs = U ? U.regs : [curReg()];
    const ids = stnInReg();
    if (!ids.includes(stnSel)) stnSel = ids.length ? ids.reduce((a, b) => stnCount(STN.st[b], 1) > stnCount(STN.st[a], 1) ? b : a) : -1;
    // 노선별로 묶은 목록. 여러 노선이 지나는 역은 노선마다 나옵니다
    const byName = (a, b) => STN.st[a][2].localeCompare(STN.st[b][2], 'ko');
    const groups = STN.lines.map((l, li) => [l[0], ids.filter(i => STN.st[i][5].includes(li)).sort(byName)])
      .filter(g => g[1].length).sort((a, b) => a[0].localeCompare(b[0], 'ko'));
    const none = ids.filter(i => !STN.st[i][5].length).sort(byName);
    if (none.length) groups.push(['노선 미확인', none]);
    $('stn-sel').innerHTML = groups.map(([name, xs]) => `<optgroup label="${esc(name)}">${xs.map(i => `<option value="${i}">${esc(STN.st[i][2])}</option>`).join('')}</optgroup>`).join('');
    $('stn-sel').disabled = !ids.length;
    if (stnSel >= 0) $('stn-sel').value = String(stnSel);
    $('stn-sub').textContent = !ids.length ? `${regionName()}에는 지하철·광역철도역이 없습니다.`
      : `${regionName()} 역 ${fmt(ids.length)}곳 · 선택 업종의 영업 숙소를 반경별로 셉니다.`;
    renderStation();
  }
  function renderStation() {
    const s = STN.st[stnSel];
    if (!s) { $('stn-kpis').innerHTML = ''; $('stn-table').innerHTML = ''; $('stn-lines').innerHTML = ''; $('stn-rail').textContent = ''; $('stn-table-title').textContent = '업종별 숙소 수'; drawRings(null); return; }
    const R = STN.r, place = s[3] >= 0 ? `${short(S[s[3]].name)} ${S[s[3]].sgg[s[4]]}` : '';
    $('stn-lines').innerHTML = s[5].map(li => `<span class="chip" style="padding-right:10px"><span class="sw" style="background:${STN.lines[li][1] || '#7f8c8d'}"></span>${esc(STN.lines[li][0])}</span>`).join(' ')
      + (place ? ` <small style="color:var(--muted)">${esc(place)}</small>` : '');
    $('stn-kpis').innerHTML = R.map((km, k) => `<div class="kpi"><b>${fmt(stnCount(s, k))}</b><span>반경 ${kmLabel(km)} 안 영업 숙소</span></div>`).join('');
    const kr = s[7], ym = k => `${k.slice(0, 4)}.${k.slice(4)}`, K = STN.kym || [];
    if (kr) {
      const ride = kr[0].reduce((a, b) => a + b, 0), goff = kr[1].reduce((a, b) => a + b, 0), nm = kr[0].filter((v, i) => v || kr[1][i]).length || 1;
      $('stn-rail').innerHTML = `<b>코레일 광역철도 승하차</b> ${ym(K[0])}~${ym(K[K.length - 1])}: 승차 ${fmt(ride)}명 · 하차 ${fmt(goff)}명 · 월평균 ${fmt(Math.round((ride + goff) / nm))}명`
        + ` (${ym(K[K.length - 1])} ${fmt(kr[0][kr[0].length - 1] + kr[1][kr[1].length - 1])}명). 서울교통공사 등 다른 운영기관 노선 이용객은 들어 있지 않습니다.`;
    } else $('stn-rail').textContent = K.length && !s[8] ? '코레일 승하차 자료가 없는 역입니다(코레일이 운영하지 않는 노선이거나 역 이름이 맞지 않음).' : '';
    const mr = s[8], MK = STN.mym || [];
    if (mr) {
      // 매일 쌓이는 자료라 이번 달은 진행 중: 월평균은 다 찬 달만으로
      const now = new Date(), cur = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}`, part = MK.at(-1) === cur;
      const ride = mr[0].reduce((a, b) => a + b, 0), goff = mr[1].reduce((a, b) => a + b, 0);
      const full = MK.map((_, i) => i).filter(i => !(part && i === MK.length - 1) && (mr[0][i] || mr[1][i]));
      const avg = full.length ? full.reduce((a, i) => a + mr[0][i] + mr[1][i], 0) / full.length : 0;
      $('stn-rail').insertAdjacentHTML('beforeend', `${kr ? '<br>' : ''}<b>간선열차(KTX·ITX·무궁화 등) 승하차</b> ${ym(MK[0])}~${ym(MK.at(-1))}${part ? '(진행 중)' : ''}: 승차 ${fmt(ride)}명 · 하차 ${fmt(goff)}명 · 월평균 ${fmt(Math.round(avg))}명.`);
    }
    const rows = s[6].filter(c => state.types.has(c[0])).sort((a, b) => b[R.length] - a[R.length]);
    $('stn-table-title').textContent = `${s[2]} 업종별 숙소 수`;
    $('stn-table').innerHTML = `<thead><tr><th>업종</th>${R.map(km => `<th>${kmLabel(km)}</th>`).join('')}</tr></thead><tbody>`
      + rows.map(c => `<tr><td><span class="sw" style="background:var(--c${catOf[c[0]]})"></span>${esc(T[c[0]].name)}</td>${c.slice(1).map(v => `<td>${fmt(v)}</td>`).join('')}</tr>`).join('')
      + `<tr><td><b>합계</b></td>${R.map((_, k) => `<td><b>${fmt(stnCount(s, k))}</b></td>`).join('')}</tr></tbody>`;
    csvSet('stn-table', ['역', '업종', ...R.map(km => `반경 ${kmLabel(km)}`)], rows.map(c => [s[2], T[c[0]].name, ...c.slice(1)]));
    drawRings(s);
  }
  function drawRings(s, fly) {
    if (!mapReady) return;
    const feats = [];
    if (s && tab === 'transit') {
      const [lat, lon] = s, kx = 111.32 * Math.cos(lat * Math.PI / 180);
      for (const km of STN.r) {
        const g = []; for (let k = 0; k <= 72; k++) { const a = k / 72 * 2 * Math.PI; g.push([lon + km / kx * Math.sin(a), lat + km / 110.95 * Math.cos(a)]); }
        feats.push({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: g } },
          { type: 'Feature', properties: { l: kmLabel(km) }, geometry: { type: 'Point', coordinates: [lon, lat + km / 110.95] } });
      }
      if (fly) map.fitBounds([[lon - 1.05 / kx, lat - 1.05 / 110.95], [lon + 1.05 / kx, lat + 1.05 / 110.95]], { padding: 30, duration: 800 });
    }
    map.getSource('stn-ring').setData({ type: 'FeatureCollection', features: feats });
  }
  function stnInReg() {
    const regs = U ? U.regs : [curReg()];
    return STN.st.map((_, i) => i).filter(i => regs.some(r => inReg(r, STN.st[i][3], STN.st[i][4])));
  }
  // 검색: 역·노선 이름에 검색어가 들어간 역을 목록으로 보여주고, 누르거나 ↑↓·Enter로 고름 (공백 무시, 이름이 같은 역 먼저)
  let sugg = [], suggAt = 0;
  const pickStation = i => { stnSel = i; $('stn-q').value = ''; closeSugg(); renderStations(); drawRings(STN.st[i], true); };
  const closeSugg = () => { $('stn-sugg').hidden = true; sugg = []; };
  function showSugg() {
    const q = $('stn-q').value.replace(/\s/g, '');
    if (!STN || !q) return closeSugg();
    const nm = i => STN.st[i][2].replace(/\s/g, ''), hay = i => nm(i) + STN.st[i][5].map(li => STN.lines[li][0]).join('').replace(/\s/g, '');
    const all = stnInReg().filter(i => hay(i).includes(q)), bare = n => n.replace(/역$/, '');
    sugg = all.sort((a, b) => (bare(nm(b)) === bare(q)) - (bare(nm(a)) === bare(q)) || nm(b).startsWith(q) - nm(a).startsWith(q) || nm(a).localeCompare(nm(b), 'ko')).slice(0, 15);
    suggAt = 0;
    const nat = sugg.length ? 0 : STN.st.filter((s, i) => hay(i).includes(q)).length;
    $('stn-sugg').innerHTML = sugg.map((i, k) => { const s = STN.st[i];
      return `<button type="button" role="option" data-i="${i}" aria-selected="${k === 0}"><b>${esc(s[2])}</b><small>${s[5].map(li => `<span class="sw" style="background:${STN.lines[li][1] || '#7f8c8d'}"></span>${esc(STN.lines[li][0])}`).join(' ')}${s[3] >= 0 ? ` · ${esc(short(S[s[3]].name))} ${esc(S[s[3]].sgg[s[4]])}` : ''}</small></button>`; }).join('')
      + (all.length > sugg.length ? `<p class="note">${fmt(all.length - sugg.length)}곳 더 있습니다. 더 입력해 좁혀 보세요.</p>` : '')
      || `<p class="note">${regionName()}에 맞는 역이 없습니다.${nat ? ` 전국에는 ${fmt(nat)}곳 있습니다(위에서 광역을 전국으로).` : ''}</p>`;
    $('stn-sugg').hidden = false;
  }
  $('stn-q').oninput = showSugg;
  $('stn-q').onkeydown = e => {
    if ($('stn-sugg').hidden || !sugg.length) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault(); suggAt = (suggAt + (e.key === 'ArrowDown' ? 1 : sugg.length - 1)) % sugg.length;
      $('stn-sugg').querySelectorAll('button').forEach((b, k) => { b.setAttribute('aria-selected', String(k === suggAt)); if (k === suggAt) b.scrollIntoView({ block: 'nearest' }); });
    } else if (e.key === 'Enter') { e.preventDefault(); pickStation(sugg[suggAt]); }
    else if (e.key === 'Escape') closeSugg();
  };
  $('stn-sugg').addEventListener('mousedown', e => { const b = e.target.closest('button[data-i]'); if (b) { e.preventDefault(); pickStation(+b.dataset.i); } });
  $('stn-q').onblur = () => setTimeout(closeSugg, 150);
  $('stn-q').onfocus = showSugg;
  $('stn-sel').onchange = e => { stnSel = +e.target.value; renderStation(); drawRings(STN.st[stnSel], true); };
  getJSON('data/stations.json', null).then(d => { STN = d; renderStations(); });

  /* ---------- 방한 외래관광객 (전국, 월별·국적별) ---------- */
  // 월별 값(YYYYMM)을 분기·연도로 합산. 마지막 기간에 달이 덜 찼으면 진행 중(점선·*)으로 표시
  const PER_NAME = { m: '월별', q: '분기별', y: '연도별' };
  function perAgg(months, series, per) {
    const keyOf = k => per === 'y' ? k.slice(0, 4) : per === 'q' ? `${k.slice(2, 4)}.${Math.ceil(+k.slice(4) / 3)}Q` : `${k.slice(2, 4)}.${k.slice(4)}`;
    const labels = [], cnt = [], vals = series.map(() => []);
    months.forEach((k, i) => {
      const key = keyOf(k);
      if (labels[labels.length - 1] !== key) { labels.push(key); cnt.push(0); vals.forEach(v => v.push(0)); }
      cnt[cnt.length - 1]++; series.forEach((s, j) => { vals[j][vals[j].length - 1] += s[i]; });
    });
    const full = { m: 1, q: 3, y: 12 }[per];
    return { labels, vals, partial: cnt.map(c => c < full) };
  }
  let arrPer = 'm';
  $('arr-per').addEventListener('click', e => { const x = e.target.closest('button'); if (x) { arrPer = x.dataset.v; renderArrivals(); } });
  function renderArrivals() {
    $('arr-sec').hidden = !arrivals;
    if (!arrivals) return;
    const { months, total, top } = arrivals, n = months.length, sum = (arr, a, b) => arr.slice(Math.max(0, a), b).reduce((p, q) => p + q, 0);
    const ym = k => `${k.slice(0, 4)}.${k.slice(4)}`, l12 = sum(total, n - 12, n), p12 = sum(total, n - 24, n - 12);
    const y19 = months.reduce((s, k, i) => s + (k.startsWith('2019') ? total[i] : 0), 0);
    const yoy = (a, b) => b ? (a >= b ? '+' : '') + ((a / b - 1) * 100).toFixed(1) + '%' : '-';
    const man = v => fmt(Math.round(v / 1e4)) + '만';
    $('arr-kpis').innerHTML = [
      [man(l12), `최근 12개월 (${ym(months[n - 12] || months[0])}~${ym(months[n - 1])})`],
      [yoy(l12, p12), '직전 12개월 대비'],
      [man(total[n - 1]), `${ym(months[n - 1])} (전년 동월 ${yoy(total[n - 1], total[n - 13])})`],
      [y19 ? (l12 / y19 * 100).toFixed(0) + '%' : '-', '2019년 연간 대비 (최근 12개월)'],
    ].map(k => `<div class="kpi"><b>${k[0]}</b><span>${k[1]}</span></div>`).join('');
    $('arr-sub').textContent = `${ym(months[0])}~${ym(months[n - 1])} 입국자 수입니다. 지역별 숙소 수요의 배경으로 보세요.`;
    const P = perAgg(months, [total], arrPer);
    document.querySelectorAll('#arr-per button').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.v === arrPer)));
    $('arr-title').textContent = PER_NAME[arrPer] + ' 방한 외래관광객' + (P.partial[P.partial.length - 1] ? ' (* 진행 중)' : '');
    lineChart($('arr'), $('arr-tip'), P.labels, [{ name: '방한 외래관광객', color: 'var(--c0)', vals: P.vals[0] }],
      { div: 1e4, partial: P.partial, unit: v => !v ? '0' : fmt(Math.round(v / 1e4)) + '만', tip: v => fmt(v) + '명' });
    const rows = top.map(t => ({ name: t.name, v: sum(t.n, n - 12, n), p: sum(t.n, n - 24, n - 12) }));
    $('arr-top-title').textContent = `국적별 상위 10 · 최근 12개월 (괄호는 직전 12개월 대비)`;
    $('arr-top').innerHTML = rowsHTML(rows.map(r => ({ name: r.name, value: r.v, label: man(r.v), extra: `${pc1(r.v / l12)} · ${yoy(r.v, r.p)}` })), {});
    csvSet('arr-top', ['국적', '최근 12개월', '직전 12개월', '증감률(%)', '비중(%)'], rows.map(r => [r.name, r.v, r.p, r.p ? ((r.v / r.p - 1) * 100).toFixed(2) : '', (r.v / l12 * 100).toFixed(2)]));
  }
  const pc1 = x => (x * 100).toFixed(1) + '%';

  /* ---------- 인천공항 국가별 여객 (노선 기준, build.py → icn.json) ---------- */
  let icn = null, icnPer = 'm';
  function renderIcn() {
    $('icn-sec').hidden = !icn;
    if (!icn) return;
    const { months, arr, dep, top } = icn, n = months.length, sum = (v, a, b) => v.slice(Math.max(0, a), b).reduce((p, q) => p + q, 0);
    const ym = k => `${k.slice(0, 4)}.${k.slice(4)}`, yoy = (a, b) => b ? (a >= b ? '+' : '') + ((a / b - 1) * 100).toFixed(1) + '%' : '-';
    const man = v => fmt(Math.round(v / 1e4)) + '만', a12 = sum(arr, n - 12, n), p12 = sum(arr, n - 24, n - 12);
    $('icn-kpis').innerHTML = [
      [man(a12), `도착 여객 · 최근 12개월 (${ym(months[Math.max(0, n - 12)])}~${ym(months[n - 1])})`],
      [yoy(a12, p12), '직전 12개월 대비'],
      [man(arr[n - 1]), `${ym(months[n - 1])} 도착 (전년 동월 ${yoy(arr[n - 1], arr[n - 13])})`],
      [man(sum(dep, n - 12, n)), '출발 여객 · 최근 12개월'],
    ].map(k => `<div class="kpi"><b>${k[0]}</b><span>${k[1]}</span></div>`).join('');
    const P = perAgg(months, [arr, dep], icnPer);
    document.querySelectorAll('#icn-per button').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.v === icnPer)));
    $('icn-title').textContent = PER_NAME[icnPer] + ' 인천공항 여객' + (P.partial[P.partial.length - 1] ? ' (* 진행 중)' : '');
    lineChart($('icn'), $('icn-tip'), P.labels, [{ name: '도착', color: 'var(--c0)', vals: P.vals[0] }, { name: '출발', color: 'var(--c1)', vals: P.vals[1] }],
      { div: 1e4, partial: P.partial, unit: v => !v ? '0' : fmt(Math.round(v / 1e4)) + '만', tip: v => fmt(v) + '명' });
    const rows = top.map(t => ({ name: t.name, region: t.region, v: sum(t.arr, n - 12, n), p: sum(t.arr, n - 24, n - 12) }));
    $('icn-top').innerHTML = rowsHTML(rows.map(r => ({ name: `${r.name} (${r.region})`, value: r.v, label: man(r.v), extra: `${pc1(r.v / a12)} · ${yoy(r.v, r.p)}` })), {});
    csvSet('icn-top', ['국가(노선)', '지역', '최근 12개월 도착', '직전 12개월 도착', '증감률(%)', '비중(%)'],
      rows.map(r => [r.name, r.region, r.v, r.p, r.p ? ((r.v / r.p - 1) * 100).toFixed(2) : '', (r.v / a12 * 100).toFixed(2)]));
  }
  $('icn-per').addEventListener('click', e => { const x = e.target.closest('button'); if (x) { icnPer = x.dataset.v; renderIcn(); } });
  getJSON('data/icn.json', null).then(d => { icn = d; renderIcn(); });

  /* ---------- 공항별 여객 (한국공항공사, 연간, build.py → kac.json) ---------- */
  let kac = null;
  function renderKac() {
    $('kac-sec').hidden = !kac || !kac.airports.length;
    if (!kac || !kac.airports.length) return;
    const Y = kac.years, n = Y.length, tot = a => a.dom[n - 1] + a.intl[n - 1], prev = a => n > 1 ? a.dom[n - 2] + a.intl[n - 2] : 0;
    const man = v => v >= 1e4 ? fmt(Math.round(v / 1e4)) + '만' : fmt(v), yoy = (a, b) => b ? (a >= b ? '+' : '') + ((a / b - 1) * 100).toFixed(1) + '%' : '-';
    const all = kac.airports.reduce((p, a) => p + tot(a), 0);
    $('kac-title').textContent = `공항별 여객 · ${Y[n - 1]}년 (도착+출발)`;
    $('kac-list').innerHTML = rowsHTML(kac.airports.filter(a => tot(a)).map(a => ({ name: a.name, value: tot(a), label: man(tot(a)),
      extra: `국내 ${man(a.dom[n - 1])} · 국제 ${man(a.intl[n - 1])} · ${n > 1 ? `${Y[n - 2]}년 대비 ${yoy(tot(a), prev(a))}` : ''}` })), {});
    $('kac-sub').textContent = `${Y[n - 1]}년 전국 공항 여객 ${man(all)}명. 지방공항 수요는 그 지역 숙소 수요와 함께 보세요.`;
    csvSet('kac-list', ['공항', ...Y.flatMap(y => [`${y} 국내선`, `${y} 국제선`])], kac.airports.map(a => [a.name, ...Y.flatMap((_, i) => [a.dom[i], a.intl[i]])]));
  }
  const kacOf = name => kac && name ? kac.airports.find(a => name.startsWith(a.name)) : null;
  getJSON('data/kac.json', null).then(d => { kac = d; renderKac(); });

  /* ---------- 외지인·외국인 방문객 추이 (지금 고른 지역, 누적 막대 + 외국인 비중) ---------- */
  let dvPer = 'y', dvMode = 'bar';
  function renderDemandVis() {
    if (!visits) { $('dv-sec').hidden = true; return; }
    const regs = U ? U.regs : [curReg()];
    const sum = [visits.q.map(() => null), visits.q.map(() => null)];
    for (const r of regs) { const v = visOf(r); if (v) for (let j = 0; j < 2; j++) v[j].forEach((x, i) => { if (x != null) sum[j][i] = (sum[j][i] || 0) + x; }); }
    const P = visPeriods(dvPer), agg = j => P.idx.map(ii => ii.some(i => sum[j][i] == null) ? null : ii.reduce((a, i) => a + sum[j][i], 0));
    const b = agg(0), c = agg(1), labels = P.keys.map(k => dvPer === 'y' ? k : `${k.slice(2, 4)}.${k.slice(5)}Q`);
    document.querySelectorAll('#dv-per button').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.v === dvPer)));
    document.querySelectorAll('#dv-mode button').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.v === dvMode)));
    $('dv-hint').textContent = dvMode === 'line' ? '외지인 = 왼쪽 축 · 외국인 = 오른쪽 축' : '막대 위 숫자 = 외국인 비중';
    const W = 900, H = 300, L = 64, R = dvMode === 'line' ? 64 : 12, Tp = 22, B = 26, iw = W - L - R, ih = H - Tp - B, n = labels.length, bw = iw / n;
    const mx = Math.max(1, ...b.map((x, i) => (x || 0) + (c[i] || 0))), step = niceStep(mx / 1e4) * 1e4, top = Math.ceil(mx / step) * step;
    const Y = v => Tp + ih - v / top * ih, unit = v => !v ? '0' : v >= 1e8 ? (v / 1e8).toFixed(v % 1e8 ? 1 : 0) + '억' : fmt(Math.round(v / 1e4)) + '만';
    let svg = '';
    const every = Math.ceil(n / 12);
    if (dvMode === 'line') {
      // 선: 외지인(왼쪽 축)과 외국인(오른쪽 축)의 규모 차이가 커서 축을 따로 씁니다
      const scale = vals => { const m = Math.max(1, ...vals.filter(v => v != null)), st = niceStep(m / 1e4) * 1e4; return { st, top: Math.ceil(m / st) * st }; };
      const sb = scale(b), sc = scale(c), X = i => L + i * bw + bw / 2, Yb = v => Tp + ih - v / sb.top * ih, Yc = v => Tp + ih - v / sc.top * ih;
      for (let k = 0; k <= sb.top / sb.st; k++) {
        const y = Tp + ih - k / (sb.top / sb.st) * ih;
        svg += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y}" y2="${y}"/><text x="${L - 8}" y="${y + 4}" text-anchor="end" style="fill:var(--c0)">${unit(sb.st * k)}</text>`;
      }
      for (let v = 0; v <= sc.top; v += sc.st) svg += `<text x="${W - R + 8}" y="${Yc(v) + 4}" style="fill:var(--c1)">${unit(v)}</text>`;
      const line = (vals, Yf, col) => {
        let d = '', dash = '';
        vals.forEach((v, i) => { if (v == null) return; const pt = `${X(i)},${Yf(v)}`, pv = vals[i - 1];
          if (P.partial[i] && pv != null) dash += `M${X(i - 1)},${Yf(pv)}L${pt}`; else d += (pv == null ? 'M' : 'L') + pt; });
        return `<path d="${d}" fill="none" stroke="${col}" stroke-width="2.4"/><path d="${dash}" fill="none" stroke="${col}" stroke-width="2" stroke-dasharray="4 4"/>`
          + vals.map((v, i) => v == null ? '' : `<circle cx="${X(i)}" cy="${Yf(v)}" r="${n > 24 ? 2 : 3.5}" fill="${P.partial[i] ? 'var(--panel)' : col}" stroke="${col}" stroke-width="1.5"/>`).join('');
      };
      svg += line(b, Yb, 'var(--c0)') + line(c, Yc, 'var(--c1)');
      labels.forEach((l, i) => {
        if ((n - 1 - i) % every === 0) svg += `<text x="${X(i)}" y="${H - 8}" text-anchor="middle">${esc(l)}${P.partial[i] ? '*' : ''}</text>`;
        svg += `<rect data-i="${i}" x="${L + i * bw}" y="${Tp}" width="${bw}" height="${ih}" fill="transparent"/>`;
      });
    } else for (let v = 0; v <= top; v += step) svg += `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end">${unit(v)}</text>`;
    if (dvMode === 'bar') labels.forEach((l, i) => {
      const x = L + i * bw + bw * .15, w = bw * .7, op = P.partial[i] ? .45 : 1;
      if (b[i]) svg += `<rect x="${x}" y="${Y(b[i])}" width="${w}" height="${Tp + ih - Y(b[i])}" fill="var(--c0)" opacity="${op}"/>`;
      if (b[i] && c[i]) svg += `<rect x="${x}" y="${Y(b[i] + c[i])}" width="${w}" height="${Y(b[i]) - Y(b[i] + c[i])}" fill="var(--c1)" opacity="${op}"/>`;
      if (b[i] && c[i] && n <= 20) svg += `<text class="tot" x="${x + w / 2}" y="${Y(b[i] + c[i]) - 5}" text-anchor="middle">${(c[i] / (b[i] + c[i]) * 100).toFixed(1)}%</text>`;
      if ((n - 1 - i) % every === 0) svg += `<text x="${x + w / 2}" y="${H - 8}" text-anchor="middle">${esc(l)}${P.partial[i] ? '*' : ''}</text>`;
      svg += `<rect data-i="${i}" x="${L + i * bw}" y="${Tp}" width="${bw}" height="${ih}" fill="transparent"/>`;
    });
    $('dv').innerHTML = svg;
    attachTip($('dv'), $('dv-tip'), i => `<b>${esc(labels[i])}${P.partial[i] ? ' (진행 중)' : ''}</b><br><span class="sw" style="background:var(--c0)"></span>외지인 ${b[i] == null ? '자료 없음' : fmt(Math.round(b[i] / 1e4)) + '만 명'}<br><span class="sw" style="background:var(--c1)"></span>외국인 ${c[i] == null ? '자료 없음' : fmt(Math.round(c[i] / 1e4)) + '만 명'}${b[i] && c[i] ? `<br>외국인 비중 ${(c[i] / (b[i] + c[i]) * 100).toFixed(2)}%` : ''}`);
    const name = U ? regionName() : regLabel(curReg());
    $('dv-sub').textContent = `${name}${!U && state.dong >= 0 ? ' (방문객 자료는 시군구 단위)' : ''} · 한국관광공사 데이터랩 휴대폰 기반 연인원, ${visits.last.slice(0, 4)}.${visits.last.slice(4, 6)}.${visits.last.slice(6)}까지`;
    $('dv-note').textContent = (dvMode === 'line' ? '선 보기는 외지인(왼쪽 축)과 외국인(오른쪽 축)의 눈금이 다릅니다. ' : '')
      + '외지인은 다른 지역에서 온 내국인입니다. 외국인 자료는 기초 2019년·광역 2020년부터라 그 전에는 외지인만 그립니다. 흐린 막대·점선(*)은 아직 다 모이지 않은 기간입니다.'
      + (regs.length > 1 ? ' 여러 기초를 합친 값이라 여러 곳을 들른 사람은 중복으로 셉니다.' : '');
  }
  $('dv-per').addEventListener('click', e => { const x = e.target.closest('button'); if (x) { dvPer = x.dataset.v; renderDemandVis(); } });
  $('dv-mode').addEventListener('click', e => { const x = e.target.closest('button'); if (x) { dvMode = x.dataset.v; renderDemandVis(); } });

  /* ---------- 관광 수요 대비 숙소 ----------
     관광지·방문객 수는 시군구까지만 있으므로 이 칸은 시군구 단위에서 멈춥니다. */
  const VIS = meta.visitors;
  const tourSel = g => g ? g.reduce((s, v, i) => s + (state.tour.has(i) ? v : 0), 0) : 0;
  let supToken = 0, supRows = [];
  async function renderSupply() {
    const token = ++supToken, si = state.sido, gi = state.sgg, mode = state.sup;
    for (const id of ['sup-kpis', 'sup-ratio-card', 'sup-tour']) $(id).hidden = !!U;
    if (U) { $('sup-sub').textContent = ''; $('sup-note').textContent = '여러 지역을 묶어 보는 중(합쳐 보기·광주시 등)에는 이 칸 대신 "지역 비교" 탭의 지표 표에서 방문객 대비 숙소를 보세요.'; return; }
    const atSgg = si >= 0 && gi >= 0;
    const regName = si < 0 ? '전국' : S[si].name + (atSgg ? ' ' + S[si].sgg[gi] : '');
    // 영업 중 숙소 (선택 업종) by child area: 광역 (전국 보기) or 기초 (광역 보기)
    const lod = {};
    if (!D) { for (const r of cube) if (r[3] === 0 && state.types.has(r[2])) lod[r[0]] = (lod[r[0]] || 0) + r[5]; }
    else for (const r of D.rows) if (r[6] === 0 && state.types.has(r[2])) lod[r[3]] = (lod[r[3]] || 0) + 1;
    const kids = si < 0 ? S.map((s, i) => ({ k: i, name: s.name, vis: s.vis, tour: (s.tour || []).reduce((a, g) => a + tourSel(g), 0), lod: lod[i] || 0 }))
      : S[si].sgg.map((g, i) => ({ k: i, name: g, vis: (S[si].visg || [])[i], tour: tourSel((S[si].tour || [])[i]), lod: lod[i] || 0 }));
    const sel = atSgg ? kids.filter(c => c.k === gi) : kids;
    const sum = f => sel.reduce((a, c) => a + (c[f] || 0), 0);
    const vj = mode === 'for' ? 1 : 0, vOf = c => c.vis ? c.vis[vj] : null, vName = mode === 'for' ? '외국인' : '외지인';
    const L = sum('lod'), TT = sum('tour'), VO = sel.reduce((a, c) => a + (c.vis ? c.vis[0] : 0), 0), VF = sel.reduce((a, c) => a + (c.vis ? c.vis[1] : 0), 0);
    const perVis = (l, v) => v ? l / (v / 1e6) : null, perTour = (l, t) => t ? l / t : null;
    const man = v => VIS && v ? fmt(Math.round(v / 1e4)) + '만' : '-';
    $('sup-kpis').innerHTML = [
      [fmt(L), `${regName} 영업 숙소 (선택 업종)`],
      [man(VO), VIS ? '연간 외지인 방문객' : '방문객 자료 없음'],
      [man(VF), VIS ? '연간 외국인 방문객' : '방문객 자료 없음'],
      mode === 'tour' ? [TT ? perTour(L, TT).toFixed(1) : '-', state.tour.size ? '관광지 1곳당 숙소 (선택 관광 유형)' : '관광 유형을 고르세요']
        : [perVis(L, vj ? VF : VO)?.toFixed(1) ?? '-', `${vName} 100만 명당 숙소`],
    ].map(k => `<div class="kpi"><b>${k[0]}</b><span>${k[1]}</span></div>`).join('');
    $('sup-sub').textContent = `${regName} 기준. 숙소가 수요보다 적은 곳과 관광지 주변 숙소 공백을 봅니다.`;

    // child-area ranking, fewest lodgings per demand first
    $('sup-ratio-card').hidden = atSgg;
    document.querySelectorAll('#sup-seg button').forEach(b => { b.setAttribute('aria-pressed', String(b.dataset.m === mode)); b.disabled = b.dataset.m !== 'tour' && !VIS; });
    if (!atSgg) {
      const isVis = mode !== 'tour';
      const f = isVis ? c => perVis(c.lod, vOf(c)) : c => perTour(c.lod, c.tour);
      const minD = si < 0 ? 1 : 5;
      const list = kids.filter(c => isVis ? vOf(c) : c.tour && c.tour >= minD).map(c => ({ ...c, r: f(c) })).sort((a, b) => a.r - b.r);
      const avg = isVis ? perVis(L, vj ? VF : VO) : perTour(L, TT);
      $('sup-ratio-title').textContent = `${childLabel()}별 ${isVis ? vName + ' 100만 명당' : '관광지 1곳당'} 숙소 · 적은 순`;
      $('sup-ratio').innerHTML = rowsHTML(list.map(c => ({ k: c.k, name: c.name, value: c.r, mark: avg, label: c.r.toFixed(1) + '곳',
        extra: isVis ? fmt(Math.round(vOf(c) / 1e4)) + '만 명' : '관광지 ' + fmt(c.tour), color: c.r < avg * .5 ? 'var(--closed)' : 'var(--c0)' })), { button: true })
        || '<p class="note">비교할 자료가 없습니다.</p>';
      csvSet('sup-ratio', [childLabel(), '영업 숙소', isVis ? `연간 ${vName}` : '관광지', isVis ? `${vName} 100만 명당 숙소` : '관광지 1곳당 숙소'],
        list.map(c => [c.name, c.lod, isVis ? vOf(c) : c.tour, c.r.toFixed(2)]));
      const miss = isVis ? kids.filter(c => !vOf(c)).map(c => c.name) : [];
      $('sup-ratio-note').textContent = (isVis
        ? `세로선은 ${regName} 평균, 빨간 막대는 평균의 절반 미만입니다. 방문객은 한국관광공사 데이터랩 ${VIS.from.slice(0, 4)}.${VIS.from.slice(4, 6)}~${VIS.to.slice(0, 4)}.${VIS.to.slice(4, 6)} 기준 연인원을 1년치로 환산했습니다.`
        : `세로선은 ${regName} 평균, 빨간 막대는 평균의 절반 미만입니다. 관광 유형은 지도 옆 체크박스를 따릅니다${si >= 0 ? ' · 관광지 5곳 미만 지역은 뺐습니다' : ''}.`)
        + (miss.length ? ` 방문객 자료 없음: ${miss.join(', ')}.` : '')
        + ((p => p.length && isVis ? ` ${p.join(', ')}는 신설 구라 집계 기간이 짧아 연간으로 환산했습니다.` : '')(si < 0 || !VIS ? [] : VIS.partial.filter(x => x.startsWith(S[si].name + ' ')).map(x => x.slice(S[si].name.length + 1))));
    }

    // attractions with the fewest / most lodgings nearby (광역을 골랐을 때)
    $('sup-tour').hidden = si < 0;
    if (si < 0) { $('sup-note').textContent = '광역을 고르면 관광지별 주변 숙소 수가 나옵니다.'; return; }
    const rows = await loadTour(si);
    if (token !== supToken) return;
    supRows = rows.filter(r => state.tour.has(r[2]) && (gi < 0 || r[3] === gi) && r[9] != null);
    const idx = supRows.map((_, i) => i);
    const gap = [...idx].sort((a, b) => supRows[a][9] - supRows[b][9] || supRows[a][8] - supRows[b][8]).slice(0, 12);
    const dense = [...idx].sort((a, b) => supRows[b][8] - supRows[a][8]).slice(0, 12);
    const mx3 = Math.max(1, ...gap.map(i => supRows[i][9])), mx1 = Math.max(1, ...dense.map(i => supRows[i][8]));
    const row = (i, v, mx, label, extra) => { const r = supRows[i];
      return `<button class="row" data-ti="${i}"><span class="nm"><span class="sw ring" style="border-color:${TOUR_COL[r[2]]}"></span><span title="${esc(r[5])}">${esc(r[4])}</span></span><span class="track"><i style="width:${v / mx * 100}%;background:${TOUR_COL[r[2]]}"></i></span><span class="val">${label}<em>${extra}</em></span></button>`; };
    $('sup-gap').innerHTML = gap.map(i => row(i, supRows[i][9], mx3, `${fmt(supRows[i][9])}곳`, `1km ${fmt(supRows[i][8])}`)).join('') || '<p class="note">관광지가 없습니다.</p>';
    $('sup-dense').innerHTML = dense.map(i => row(i, supRows[i][8], mx1, `${fmt(supRows[i][8])}곳`, `3km ${fmt(supRows[i][9])}`)).join('') || '<p class="note">관광지가 없습니다.</p>';
    const zero = supRows.filter(r => r[9] === 0).length;
    $('sup-note').textContent = supRows.length ? `${regName} 관광지 ${fmt(supRows.length)}곳 중 ${fmt(zero)}곳(${pct(zero, supRows.length)})은 반경 3km 안에 영업 중인 숙소가 없습니다. 주변 숙소 수는 업종 선택과 관계없이 야영장을 뺀 영업 중 숙소 전체입니다. 이름을 누르면 지도로 이동합니다.` : '';
  }
  $('sup-seg').addEventListener('click', e => { const b = e.target.closest('button'); if (b && !b.disabled) { state.sup = b.dataset.m; renderSupply(); } });
  const flyTo = e => {
    const b = e.target.closest('button[data-ti]'); if (!b || !mapReady) return;
    const r = supRows[+b.dataset.ti];
    map.flyTo({ center: [r[1], r[0]], zoom: 14 });
    new maplibregl.Popup({ maxWidth: '260px' }).setLngLat([r[1], r[0]]).setHTML(`<b>${esc(r[4])}</b><br>${esc(TOUR.types[r[2]])}<br>영업 숙소 반경 1km ${fmt(r[8])}곳 · 3km ${fmt(r[9])}곳`).addTo(map);
    $('map').scrollIntoView({ behavior: 'smooth', block: 'center' });
  };
  $('sup-gap').addEventListener('click', flyTo);
  $('sup-dense').addEventListener('click', flyTo);

  /* ---------- 뜨는 지역 · 지는 지역 ----------
     최근 3년(올해 포함) 신규 인허가 − 폐업 = 순증, 증가율 = 순증 ÷ 3년 전 말 운영 중(영업+휴업) 시설 수. */
  function renderTrend(names) {
    const Y3 = yNow - 3, inW = y => y > Y3 && y <= yNow;
    const m = {}, tot = { nw: 0, cl: 0, base: 0 };
    const add = (ch, f, w) => { tot[f] += w; if (ch != null && ch >= 0) (m[ch] ||= { nw: 0, cl: 0, base: 0 })[f] += w; };
    if (!D) {
      for (const r of cube) { if (!state.types.has(r[2])) continue; if (inW(r[4])) add(r[0], 'nw', r[5]); if (r[3] < 2 && r[4] && r[4] <= Y3) add(r[0], 'base', r[5]); }
      for (const r of close) { if (!state.types.has(r[2])) continue; if (inW(r[3])) add(r[0], 'cl', r[5]); if (r[4] && r[4] <= Y3 && r[3] > Y3) add(r[0], 'base', r[5]); }
    } else for (const r of D.rows) {
      if (!inDetail(r) || !state.types.has(r[2])) continue;
      const ch = childOfRow(r);
      if (inW(r[7])) add(ch, 'nw', 1);
      if (inW(r[8])) add(ch, 'cl', 1);
      if (r[7] && r[7] <= Y3 && (r[6] < 2 || r[8] > Y3)) add(ch, 'base', 1);
    }
    const g = x => x.base ? (x.nw - x.cl) / x.base : null, sg = v => (v >= 0 ? '+' : '') + fmt(v);
    const net = tot.nw - tot.cl;
    $('tr-kpis').innerHTML = [
      [fmt(tot.nw), `${Y3 + 1}~${yNow} 신규 인허가`], [fmt(tot.cl), '같은 기간 폐업'], [sg(net), '순증'],
      [tot.base ? (net >= 0 ? '+' : '') + (net / tot.base * 100).toFixed(1) + '%' : '-', `증가율 (${Y3}년 말 ${fmt(tot.base)}곳 대비)`],
    ].map(k => `<div class="kpi"><b>${k[0]}</b><span>${k[1]}</span></div>`).join('');
    $('tr-sub').textContent = `${regionName()} · 선택 업종 · ${yNow}년은 진행 중`;
    const minBase = [0, 30, 10, 5, 0][level()];
    const list = Object.entries(m).filter(([, x]) => x.base >= Math.max(1, minBase)).map(([k, x]) => ({ k, x, g: g(x) }));
    const mx = Math.max(1e-9, ...list.map(e => Math.abs(e.g)));
    const row = e => `<button class="row" data-k="${e.k}" title="신규 ${fmt(e.x.nw)} · 폐업 ${fmt(e.x.cl)} · ${Y3}년 말 ${fmt(e.x.base)}곳"><span class="nm"><span>${esc(names[e.k] ?? '(미상)')}</span></span>
      <span class="track"><i style="width:${Math.abs(e.g) / mx * 100}%;background:${e.g >= 0 ? 'var(--ok)' : 'var(--closed)'}"></i></span>
      <span class="val">${e.g >= 0 ? '+' : ''}${(e.g * 100).toFixed(1)}%<em>${sg(e.x.nw - e.x.cl)}곳</em></span></button>`;
    const up = [...list].sort((a, b) => b.g - a.g), n = Math.min(10, Math.ceil(list.length / 2));
    const empty = level() >= 4 ? '<p class="note">더 작은 지역 단위가 없습니다.</p>' : '<p class="note">비교할 지역이 부족합니다.</p>';
    $('tr-up').innerHTML = up.slice(0, n).map(row).join('') || empty;
    $('tr-down').innerHTML = up.slice(-n).reverse().map(row).join('') || empty;
    $('tr-note').textContent = `${Y3}년 말 운영 시설이 ${Math.max(1, minBase)}곳 이상인 ${childLabel() || '지역'}만 비교합니다. 막대에 마우스를 올리면 신규·폐업 수가 보입니다. 폐업일이 없는 폐업 시설은 빠집니다.`;
    return tot;
  }

  /* ---------- 외국인관광 도시민박 입지 ---------- */
  const MB = T.findIndex(t => t.cat === '외국인관광 도시민박업');
  const ZN = meta.zones || [], BD = meta.bldgs || [];
  const ZC = ['var(--c0)', 'var(--c1)', 'var(--c3)', 'var(--c2)', '#9aa3ab'];
  const BC = ['var(--c6)', 'var(--c4)', 'var(--c0)', 'var(--c3)', '#9aa3ab'];
  $('mb-sec').hidden = MB < 0 || !ZN.length;
  $('mb-legend').innerHTML = BD.map((z, i) => `<span><i style="background:${BC[i]}"></i>${esc(z)}</span>`).join('');
  function renderMinbak(names) {
    if (MB < 0 || !ZN.length) return;
    const z = ZN.map(() => 0), b = BD.map(() => 0), area = {};
    let n = 0;
    const add = (ch, zi, bi, w) => { n += w; z[zi] += w; b[bi] += w; if (ch != null && ch >= 0) (area[ch] ||= BD.map(() => 0))[bi] += w; };
    if (!D) { for (const r of minbak) if (r[2] === 0) add(r[0], r[3], r[4], r[5]); }
    else for (const r of D.rows) if (r[2] === MB && r[6] === 0 && inDetail(r) && r[14] >= 0) add(childOfRow(r), r[14], r[15], 1);
    const known = n - z[ZN.length - 1];
    // 외국인 방문객 대비: 시군구까지만
    const visF = r => ((r.gi < 0 ? S[r.si].vis : (S[r.si].visg || [])[r.gi]) || [0, 0])[1];
    const v = U ? U.regs.reduce((a, r) => a + visF(r), 0) : state.sido < 0 ? S.reduce((a, s) => a + (s.vis ? s.vis[1] : 0), 0)
      : state.sgg < 0 ? (S[state.sido].vis || [0, 0])[1] : ((S[state.sido].visg || [])[state.sgg] || [0, 0])[1];
    const vReg = U ? '선택 지역' : state.sido < 0 ? '전국' : state.sgg < 0 ? S[state.sido].name : S[state.sido].sgg[state.sgg];
    $('mb-kpis').innerHTML = [
      [fmt(n), `${regionName()} 영업 중 도시민박`],
      [pct(z[0], known), `주거지역 비율 (용도지역 확인된 ${fmt(known)}곳 중)`],
      [pct(z[ZN.length - 1], n), '용도지역 미상'],
      [VIS && v && level() <= 2 ? (n / (v / 1e6)).toFixed(1) : '-', VIS ? `외국인 방문객 100만 명당 (${esc(vReg)})` : '방문객 자료 없음'],
    ].map(k => `<div class="kpi"><b>${k[0]}</b><span>${k[1]}</span></div>`).join('');
    $('mb-sub').textContent = '도시민박은 주민이 사는 주택에서만 할 수 있어 주거지역 비중이 높은 것은 정상입니다. 볼 것은 특정 동네에 몰리는지입니다.';
    const bars = (vals, labels, cols) => rowsHTML(vals.map((x, i) => ({ name: labels[i], value: x / (n || 1), color: cols[i], label: pct(x, n), extra: fmt(x) + '곳' })), {});
    $('mb-zone').innerHTML = n ? bars(z, ZN, ZC) : '<p class="note">자료가 없습니다.</p>';
    $('mb-bldg').innerHTML = n ? bars(b, BD, BC) : '';
    const areas = Object.entries(area).map(([k, x]) => [k, x, x.reduce((p, q) => p + q, 0)]).sort((p, q) => q[2] - p[2]);
    $('mb-area-title').textContent = level() >= 4 ? '' : `도시민박이 몰린 ${childLabel()} · 건물 용도별`;
    csvSet('mb-area', [childLabel() || '지역', '영업 도시민박', ...BD], areas.map(([k, x, t]) => [names[k] ?? '(미상)', t, ...x]));
    $('mb-area').innerHTML = areas.map(([k, x, t]) => `<button class="row" data-k="${k}"><span class="nm"><span>${esc(names[k] ?? '(미상)')}</span></span>
      <span class="stackbar" style="width:${t / areas[0][2] * 100}%">${x.map((c, i) => c ? `<span style="flex:${c};background:${BC[i]}" title="${esc(BD[i])} ${fmt(c)}"></span>` : '').join('')}</span>
      <span class="val">${fmt(t)}곳<em>${pct(t, n)}</em></span></button>`).join('');
  }

  /* ---------- charts ---------- */
  function axis(top, step, L, R, Tp, ih, W) {
    let s = '';
    for (let v = 0; v <= top; v += step) { const y = Tp + ih - v / top * ih; s += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y}" y2="${y}"/><text x="${L - 8}" y="${y + 4}" text-anchor="end">${fmt(v)}</text>`; }
    return s;
  }
  const niceStep = mx => [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000].find(s => mx / s <= 5) || 50000;
  function attachTip(svg, tip, html) {
    const wrap = svg.parentElement;
    svg.onmousemove = e => {
      const r = e.target.closest('rect[data-i]'); if (!r) { tip.hidden = true; return; }
      tip.innerHTML = html(+r.dataset.i); tip.hidden = false;
      const b = wrap.getBoundingClientRect();
      tip.style.left = Math.min(e.clientX - b.left + 14, b.width - tip.offsetWidth - 4) + 'px'; tip.style.top = (e.clientY - b.top + 10) + 'px';
    };
    svg.onmouseleave = () => { tip.hidden = true; };
  }
  function drawYears(byYear) {
    const P = periods(), years = P.keys;
    const m = years.map(y => byYear[y] || CATS.map(() => 0)), tot = m.map(r => r.reduce((p, q) => p + q, 0));
    const step = niceStep(Math.max(1, ...tot)), top = Math.ceil(Math.max(1, ...tot) / step) * step;
    const L = 52, R = 8, Tp = 18, B = 26, W = 900, H = 300, iw = W - L - R, ih = H - Tp - B, bw = iw / years.length;
    let s = axis(top, step, L, R, Tp, ih, W);
    years.forEach((yv, i) => {
      const x = L + i * bw + bw * .16, w = bw * .68; let acc = 0;
      m[i].forEach((c, ci) => { if (!c) return; const y = Tp + ih - (acc + c) / top * ih; acc += c;
        s += `<rect x="${x}" y="${y}" width="${w}" height="${Math.max(c / top * ih, .5)}" fill="var(--c${ci})" stroke="var(--panel)" stroke-width="1.5"/>`; });
      if (tot[i]) s += `<text class="tot" x="${x + w / 2}" y="${Tp + ih - tot[i] / top * ih - 4}" text-anchor="middle">${fmt(tot[i])}</text>`;
      if ((years.length - 1 - i) % 2 === 0) s += `<text x="${x + w / 2}" y="${H - 8}" text-anchor="middle">${P.label(yv)}${P.partial(yv) ? '*' : ''}</text>`;
      s += `<rect data-i="${i}" x="${L + i * bw}" y="${Tp}" width="${bw}" height="${ih}" fill="transparent"/>`;
    });
    $('year').innerHTML = s;
    $('year-legend').innerHTML = CATS.map((c, i) => `<span><i style="background:var(--c${i})"></i>${esc(c)}</span>`).join('');
    $('year-sub').textContent = `${regionName()} · ${P.span} · ${P.q ? '이번 분기' : yNow + '년'}는 진행 중`;
    attachTip($('year'), $('year-tip'), i => `<b>${P.title(years[i])} ${fmt(tot[i])}곳</b><br>` + m[i].map((c, ci) => c ? `<span class="sw" style="background:var(--c${ci})"></span>${esc(CATS[ci])} ${fmt(c)}<br>` : '').join(''));
  }
  function drawOpenClose(openY, closeY) {
    const P = periods(), years = P.keys;
    const o = years.map(y => openY[y] || 0), c = years.map(y => closeY[y] || 0);
    const mx = Math.max(1, ...o, ...c), step = niceStep(mx), top = Math.ceil(mx / step) * step;
    const L = 52, R = 8, Tp = 18, B = 26, W = 900, H = 280, iw = W - L - R, ih = H - Tp - B, bw = iw / years.length;
    let s = axis(top, step, L, R, Tp, ih, W);
    years.forEach((yv, i) => {
      const w = bw * .34, x1 = L + i * bw + bw * .14, x2 = x1 + w + 1;
      if (o[i]) s += `<rect x="${x1}" y="${Tp + ih - o[i] / top * ih}" width="${w}" height="${o[i] / top * ih}" fill="var(--c0)" rx="1.5"/>`;
      if (c[i]) s += `<rect x="${x2}" y="${Tp + ih - c[i] / top * ih}" width="${w}" height="${c[i] / top * ih}" fill="var(--closed)" rx="1.5"/>`;
      if ((years.length - 1 - i) % 2 === 0) s += `<text x="${L + i * bw + bw / 2}" y="${H - 8}" text-anchor="middle">${P.label(yv)}${P.partial(yv) ? '*' : ''}</text>`;
      s += `<rect data-i="${i}" x="${L + i * bw}" y="${Tp}" width="${bw}" height="${ih}" fill="transparent"/>`;
    });
    $('oc').innerHTML = s;
    attachTip($('oc'), $('oc-tip'), i => `<b>${P.title(years[i])}</b><br><span class="sw" style="background:var(--c0)"></span>인허가 ${fmt(o[i])}<br><span class="sw" style="background:var(--closed)"></span>폐업 ${fmt(c[i])}<br>순증 ${o[i] - c[i] >= 0 ? '+' : ''}${fmt(o[i] - c[i])}`);
  }

  /* ---------- 연도별 / 분기별 (인허가 차트들이 함께 바뀜) ---------- */
  document.addEventListener('click', e => {
    const b = e.target.closest('.per-seg button'); if (!b || b.dataset.v === state.per) return;
    state.per = b.dataset.v;
    document.querySelectorAll('.per-seg button').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.v === state.per)));
    update(false);
  });

  /* ---------- 탭 ---------- */
  const TABS = ['now', 'demand', 'trend', 'minbak', 'compare', 'transit'];
  let tab = TABS.includes(initHash.get('tab')) ? initHash.get('tab') : 'now';
  function setTab(t) {
    tab = t;
    document.querySelectorAll('[data-tab]').forEach(el => el.classList.toggle('tab-off', el.dataset.tab !== t));
    document.querySelectorAll('#tabs button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.t === t)));
    if (t === 'now' && mapReady) map.resize();
    if (STN) drawRings(STN.st[stnSel], t === 'transit');
    writeHash();
  }
  $('tabs').addEventListener('click', e => { const b = e.target.closest('button[data-t]'); if (b) { setTab(b.dataset.t); scrollTo({ top: 0, behavior: 'smooth' }); } });

  /* ---------- 긴 목록은 10줄까지만 보이고 '더 보기'로 펼침 ---------- */
  const FOLD = 10, unfolded = new Set();
  function fold(el) {
    let more = el.nextElementSibling?.classList.contains('more') ? el.nextElementSibling : null;
    const n = [...el.children].filter(c => !c.classList.contains('note')).length;
    if (n <= FOLD) { el.classList.remove('folded'); if (more) more.hidden = true; return; }
    if (!more) { more = document.createElement('button'); more.className = 'btn more'; el.after(more);
      more.onclick = () => { unfolded.has(el.id) ? unfolded.delete(el.id) : unfolded.add(el.id); fold(el); }; }
    const open = unfolded.has(el.id);
    el.classList.toggle('folded', !open); more.hidden = false;
    more.textContent = open ? '접기' : `더 보기 (${fmt(n - FOLD)}개 더)`;
  }
  for (const id of ['share', 'rank', 'st-type', 'st-area', 'sup-ratio', 'mb-area']) { fold($(id)); new MutationObserver(() => fold($(id))).observe($(id), { childList: true }); }

  /* ---------- CSV 내려받기 ---------- */
  function csvSet(id, head, rows) { csvStore[id] = [head, rows]; }
  document.addEventListener('click', e => {
    const b = e.target.closest('button[data-csv]'); if (!b) return;
    const d = csvStore[b.dataset.csv]; if (!d) return;
    const cell = v => { const t = String(v ?? ''); return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
    const text = '\ufeff' + [d[0], ...d[1]].map(r => r.map(cell).join(',')).join('\r\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
    a.download = `${b.dataset.name}_${(state.cmp.length && b.dataset.csv === 'cmp-table') ? '비교' : regionName()}.csv`.replace(/[\\/:*?"<>|\s]+/g, '_');
    document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });

  /* ---------- 공유 링크: 탭·지역·영업 상태·비교 목록을 주소(#)에 담음 ---------- */
  let restoring = true;
  function regKey(r) { return r.si < 0 ? '전국' : S[r.si].name + (r.grp != null ? '/' + S[r.si].groups[r.grp].name : r.gi >= 0 ? '/' + S[r.si].sgg[r.gi] : ''); }
  function writeHash() {
    if (restoring) return;
    const h = new URLSearchParams();
    if (tab !== 'now') h.set('tab', tab);
    if (state.sido >= 0) h.set('r', state.grp >= 0 ? regKey(curReg()) : [S[state.sido].name, state.sgg >= 0 && S[state.sido].sgg[state.sgg], state.dong >= 0 && dongList()[state.dong], state.ri >= 0 && riList()[state.ri]].filter(Boolean).join('/'));
    if (state.status !== 0) h.set('st', state.status);
    if (state.cmp.length) h.set('cmp', state.cmp.map(regKey).join(','));
    if (U && unionOn()) h.set('u', '1');
    history.replaceState(null, '', h.toString() ? '#' + h : location.pathname + location.search);
  }
  const parseReg = k => { // '전국', '부산광역시', '부산광역시/해운대구' → {si, gi}; 이름이 바뀌어 없으면 null
    if (k === '전국') return { si: -1, gi: -1 };
    const [a, b] = k.split('/'), si = S.findIndex(s => s.name === a), gi = si >= 0 && b ? S[si].sgg.indexOf(b) : -1;
    const grp = si >= 0 && b ? (S[si].groups || []).findIndex(g => g.name === b) : -1;
    if (grp >= 0) return { si, gi: -1, grp };
    return si < 0 || (b && gi < 0) ? null : { si, gi };
  };
  async function restore() {
    const st = initHash.get('st');
    if (st != null && ['-1', '0', '1', '2'].includes(st)) { state.status = +st; $('f-status').value = st; }
    for (const k of (initHash.get('cmp') || '').split(',').filter(Boolean)) { const r = parseReg(k); if (r) state.cmp.push(r); }
    if (state.cmp.length) renderChips();
    const [a, b, c, d] = (initHash.get('r') || '').split('/');
    const si = a ? S.findIndex(s => s.name === a) : -1;
    if (si >= 0) {
      await setSido(si);
      const gi = b ? S[si].sgg.indexOf(b) : -1, grp = b ? (S[si].groups || []).findIndex(g => g.name === b) : -1;
      if (gi >= 0) setSgg(gi); else if (grp >= 0) await setGroup(grp);
      const di = c ? dongList().indexOf(c) : -1; if (di >= 0) setDong(di);
      const ri = d ? riList().indexOf(d) : -1; if (ri >= 0) setRi(ri);
    }
    if (initHash.get('u') === '1' && state.cmp.length) { $('cmp-union').checked = true; await applyUnion(); }
    restoring = false;
    setTab(tab);
  }
  $('share-link').onclick = async () => {
    writeHash();
    try { await navigator.clipboard.writeText(location.href); $('share-link').textContent = '복사됨 ✓'; }
    catch { prompt('이 주소를 복사하세요', location.href); }
    setTimeout(() => { $('share-link').textContent = '🔗 링크 복사'; }, 1500);
  };

  /* ---------- tour / terrain controls, footer ---------- */
  $('tourlist').innerHTML = TOUR.types.map((n, i) => `<div class="chk"><input type="checkbox" id="tour${i}" data-i="${i}"${state.tour.has(i) ? ' checked' : ''}><label for="tour${i}"><span class="sw ring" style="border-color:${TOUR_COL[i]}"></span>${esc(n)}</label><span class="n">${fmt(TOUR.counts[i] || 0)}</span></div>`).join('');
  $('tourlist').addEventListener('change', e => { const i = +e.target.dataset.i; e.target.checked ? state.tour.add(i) : state.tour.delete(i); drawTour(); renderSupply(); });
  $('ck-shade').onchange = e => { if (mapReady) map.setLayoutProperty('hillshade', 'visibility', e.target.checked ? 'visible' : 'none'); };
  $('ck-3d').onchange = e => {
    if (!mapReady) return;
    if (e.target.checked) { map.setTerrain({ source: 'dem3d', exaggeration: 1.5 }); map.easeTo({ pitch: 55, duration: 800 }); }
    else { map.setTerrain(null); map.easeTo({ pitch: 0, duration: 600 }); }
  };
  const c = meta.coords, d = meta.dedupe;
  $('foot').textContent = `숙박업과 관광숙박업에 함께 등록된 시설 ${fmt(d.removed)}건은 관광숙박업으로만 셌습니다. 좌표가 없는 야영장 ${fmt(c.dropped_campgrounds)}곳은 제외했고, 좌표가 없는 그 밖의 시설 ${fmt(c.no_coords)}곳은 통계에는 넣고 지도에서는 뺐습니다. 읍·면·동과 리는 주소의 법정동 기준입니다. 출처: 행정안전부 지방행정인허가 API, 한국관광공사 TourAPI·데이터랩(공공데이터포털), 지형 AWS Terrain Tiles.`;
  renderArrivals();
  update(false);
  await restore();
})();
