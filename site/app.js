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
  const $ = id => document.getElementById(id);
  const fmt = n => n.toLocaleString('ko-KR');
  const pct = (a, b) => b ? (a / b * 100).toFixed(1) + '%' : '-';
  const esc = s => String(s ?? '').replace(/[&<>"]/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[m]));
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const getJSON = (u, fb) => fetch(u).then(r => r.ok ? r.json() : fb).catch(() => fb);
  const [meta, cube, close, minbak, visits] = await Promise.all([getJSON('data/meta.json'), getJSON('data/cube.json', []), getJSON('data/close.json', []), getJSON('data/minbak.json', []), getJSON('data/visits.json', null)]);
  const T = meta.types, CATS = meta.categories, S = meta.sido, ST = meta.status;
  const catOf = T.map(t => CATS.indexOf(t.cat));
  const col = c => css('--c' + c);
  const STC = ['var(--ok)', 'var(--pause)', 'var(--closed)'];
  const TOUR = meta.tour || { types: [], counts: [] };
  const TOUR_COL = ['#c4153c', '#8a4fb0', '#0e9aa7'];
  const yNow = new Date().getFullYear();

  const TL0 = 1990;
  const state = { sido: -1, sgg: -1, dong: -1, ri: -1, status: 0, types: new Set(T.map((_, i) => i)), tour: new Set([0]), tl: { mode: 'off', year: yNow }, sup: meta.visitors ? 'out' : 'tour', cmp: [], vt: { per: 'y', kind: '0' } };
  let D = null; // detail file of the selected 시도
  const detailCache = {}, tourCache = {};
  const loadDetail = si => (detailCache[si] ||= getJSON(`data/pts/${si}.json`, { dongs: [], ris: {}, rows: [] }));
  const loadTour = si => (tourCache[si] ||= getJSON(`data/tour/${si}.json`, []));
  $('updated').textContent = `마지막 갱신 ${meta.updated}.`;

  /* ---------- region dropdowns: 광역 → 기초 → 읍면동 → 리 ---------- */
  const level = () => state.sido < 0 ? 0 : state.sgg < 0 ? 1 : state.dong < 0 ? 2 : state.ri < 0 ? 3 : 4;
  const dongList = () => (D && state.sgg >= 0) ? D.dongs[state.sgg] || [] : [];
  const riList = () => (D && state.dong >= 0) ? D.ris[`${state.sgg}:${state.dong}`] || [] : [];
  const opts = (sel, list, all) => { sel.innerHTML = `<option value="-1">${all}</option>` + list.map((n, i) => `<option value="${i}">${esc(n)}</option>`).join(''); sel.disabled = !list.length; };
  function fillBelow(from) {
    if (from <= 1) opts($('f-sgg'), state.sido < 0 ? [] : S[state.sido].sgg, '전체');
    if (from <= 2) opts($('f-dong'), dongList(), '전체');
    if (from <= 3) opts($('f-ri'), riList(), '전체');
  }
  $('f-sido').insertAdjacentHTML('beforeend', S.map((s, i) => `<option value="${i}">${esc(s.name)}</option>`).join(''));
  async function setSido(i) {
    state.sido = i; state.sgg = state.dong = state.ri = -1;
    D = i < 0 ? null : await loadDetail(i);
    if (state.sido !== i) return;
    $('f-sido').value = i; fillBelow(1); update(true);
  }
  function setSgg(i) { state.sgg = i; state.dong = state.ri = -1; $('f-sgg').value = i; fillBelow(2); update(true); }
  function setDong(i) { state.dong = i; state.ri = -1; $('f-dong').value = i; fillBelow(3); update(true); }
  function setRi(i) { state.ri = i; $('f-ri').value = i; update(true); }
  $('f-sido').onchange = e => setSido(+e.target.value);
  $('f-sgg').onchange = e => setSgg(+e.target.value);
  $('f-dong').onchange = e => setDong(+e.target.value);
  $('f-ri').onchange = e => setRi(+e.target.value);
  $('f-status').onchange = e => { state.status = +e.target.value; update(false); };
  fillBelow(1);

  function regionName() {
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
      case 1: return S[state.sido].sgg;
      case 2: return dongList();
      case 3: return riList();
      default: return [];
    }
  }
  const childLabel = () => ['광역', '기초', '읍·면·동', '리', ''][level()];

  /* ---------- type filter ---------- */
  $('typelist').innerHTML = CATS.map((c, ci) => {
    const items = T.map((t, i) => [t, i]).filter(([t]) => t.cat === c);
    if (!items.length) return '';
    return `<div class="cat">${esc(c)}</div>` + items.map(([t, i]) =>
      `<div class="chk"><input type="checkbox" id="t${i}" data-i="${i}" checked><label for="t${i}"><span class="sw" style="background:var(--c${ci})"></span>${esc(t.name)}</label><span class="n" id="tn${i}"></span></div>`).join('');
  }).join('');
  $('typelist').addEventListener('change', e => { const i = +e.target.dataset.i; e.target.checked ? state.types.add(i) : state.types.delete(i); update(false); });
  $('t-all').onclick = () => { T.forEach((_, i) => { state.types.add(i); $('t' + i).checked = true; }); update(false); };
  $('t-none').onclick = () => { state.types.clear(); T.forEach((_, i) => { $('t' + i).checked = false; }); update(false); };

  /* ---------- aggregation ----------
     scanOpen(fn(type, status, year, child, weight)), scanClose(fn(type, closeYear, child, weight)) */
  const inDetail = r => (state.sgg < 0 || r[3] === state.sgg) && (state.dong < 0 || r[4] === state.dong) && (state.ri < 0 || r[5] === state.ri);
  const childOfRow = r => [null, r[3], r[4], r[5], null][level()];
  function scanOpen(fn) {
    if (!D) { for (const r of cube) fn(r[2], r[3], r[4], r[0], r[5]); return; }
    for (const r of D.rows) if (inDetail(r)) fn(r[2], r[6], r[7], childOfRow(r), 1);
  }
  function scanClose(fn) {
    if (!D) { for (const r of close) fn(r[2], r[3], r[0], r[5]); return; }
    for (const r of D.rows) if (r[8] && inDetail(r)) fn(r[2], r[8], childOfRow(r), 1);
  }
  function agg() {
    const a = { total: 0, byType: T.map(() => 0), allType: T.map(() => 0), byYear: {}, byArea: {}, st: [0, 0, 0],
      stType: T.map(() => [0, 0, 0]), stArea: {}, openY: {}, closeY: {} };
    scanOpen((t, s, y, ch, w) => {
      const okS = state.status < 0 || s === state.status;
      if (okS) a.allType[t] += w;
      if (!state.types.has(t)) return;
      a.st[s] += w; a.stType[t][s] += w;
      if (ch != null && ch >= 0) (a.stArea[ch] ||= [0, 0, 0])[s] += w;
      if (y) a.openY[y] = (a.openY[y] || 0) + w;
      if (!okS) return;
      a.total += w; a.byType[t] += w;
      if (ch != null && ch >= 0) a.byArea[ch] = (a.byArea[ch] || 0) + w;
      if (y) (a.byYear[y] ||= CATS.map(() => 0))[catOf[t]] += w;
    });
    scanClose((t, cy, ch, w) => { if (state.types.has(t)) a.closeY[cy] = (a.closeY[cy] || 0) + w; });
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
      map.addSource('areas', { type: 'geojson', data: empty });
      map.addLayer({ id: 'areas', type: 'circle', source: 'areas', paint: {
        'circle-radius': ['interpolate', ['linear'], ['sqrt', ['get', 'n']], 0, 0, 10, 6, 60, 26],
        'circle-color': '#2a78d6', 'circle-opacity': .45, 'circle-stroke-color': '#fff', 'circle-stroke-width': 1 } });
      map.addSource('pts', { type: 'geojson', data: empty });
      map.addLayer({ id: 'pts', type: 'circle', source: 'pts', paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 2.2, 11, 3.6, 15, 6],
        'circle-color': ['match', ['get', 'c'], ...CATS.flatMap((_, i) => [i, col(i)]), '#888'],
        'circle-opacity': .85, 'circle-stroke-color': '#fff', 'circle-stroke-width': .6 } });
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
      for (const l of ['pts', 'areas', 'tour']) {
        map.on('mouseenter', l, () => { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', l, () => { map.getCanvas().style.cursor = ''; });
      }
      update(false);
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
    if (state.sido < 0 || !state.tour.size) { map.getSource('tour').setData(empty); return; }
    const si = state.sido, rows = await loadTour(si);
    if (si !== state.sido) return;
    map.getSource('tour').setData({ type: 'FeatureCollection', features: rows.filter(r => state.tour.has(r[2]) && (state.sgg < 0 || r[3] === state.sgg)).map(r => ({
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
    let minx = 180, miny = 90, maxx = -180, maxy = -90;
    for (const r of D.rows) {
      if (r[0] == null || !inDetail(r) || !state.types.has(r[2]) || !tlRowOK(r)) continue;
      feats.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [r[1], r[0]] },
        properties: { t: r[2], c: catOf[r[2]], s: r[6], name: r[9], addr: r[10], date: r[11], closed: r[12], ap: r[13] } });
      minx = Math.min(minx, r[1]); maxx = Math.max(maxx, r[1]); miny = Math.min(miny, r[0]); maxy = Math.max(maxy, r[0]);
    }
    map.getSource('pts').setData({ type: 'FeatureCollection', features: feats });
    drawTour();
    if (fly && feats.length) map.fitBounds([[minx, miny], [maxx, maxy]], { padding: 40, maxZoom: 15, duration: 800 });
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
    $('share-sub').textContent = topT && a.total ? `${regionName()}(${stLabel}) ${fmt(a.total)}곳 중 ${T[topT[1]].name} 비중이 ${pct(topT[0], a.total)}로 가장 큽니다.` : '';

    drawYears(a.byYear);

    // ranking of child areas
    const ranks = Object.entries(a.byArea).sort((x, y) => y[1] - x[1]);
    $('rank-title').textContent = level() >= 4 ? '하위 지역 없음' : `${regionName()} ${childLabel()}별 시설 수`;
    $('rank').innerHTML = rowsHTML(ranks.map(([k, v]) => ({ k, name: names[k] ?? '(미상)', value: v, label: fmt(v), extra: pct(v, a.total) })), { button: true })
      || '<p class="note">더 작은 지역 단위가 없습니다.</p>';

    renderStatus(a, names);
    renderCompare();
    renderSupply();
    renderTrend(names);
    renderMinbak(names);
    drawTimeline();
    drawMap(fly);
  }
  const drill = e => {
    const b = e.target.closest('button.row'); if (!b || b.dataset.k == null) return;
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
    drawOpenClose(a.openY, a.closeY);
    const order = T.map((_, i) => i).filter(i => state.types.has(i) && a.stType[i].some(Boolean))
      .sort((x, y) => (a.stType[y][2] + a.stType[y][1]) - (a.stType[x][2] + a.stType[x][1]));
    $('st-type').innerHTML = order.map(i => stackRow(T[i].name, a.stType[i], `var(--c${catOf[i]})`)).join('') || '<p class="note">자료가 없습니다.</p>';
    const areas = Object.entries(a.stArea).sort((x, y) => (y[1][1] + y[1][2]) - (x[1][1] + x[1][2])).slice(0, 25);
    $('st-area-title').textContent = level() >= 4 ? '' : `${childLabel()}별 휴업·폐업 (상위 25곳)`;
    $('st-area').innerHTML = areas.map(([k, v]) => stackRow(names[k] ?? '(미상)', v)).join('');
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
  const regLabel = r => r.si < 0 ? '전국' : r.gi < 0 ? S[r.si].name : `${short(S[r.si].name)} ${S[r.si].sgg[r.gi]}`;
  const inReg = (r, si, gi) => r.si < 0 || (si === r.si && (r.gi < 0 || gi === r.gi));
  const regions = () => state.cmp.length ? state.cmp : [{ si: state.sido, gi: state.sido < 0 ? -1 : state.sgg }];
  function renderChips() {
    $('cmp-chips').innerHTML = state.cmp.map((r, i) => `<span class="chip"><span class="sw" style="background:var(--c${i})"></span>${esc(regLabel(r))}<button data-i="${i}" aria-label="${esc(regLabel(r))} 빼기">×</button></span>`).join('')
      + (state.cmp.length ? '<button class="btn" id="cmp-clear">비우기</button>' : '');
  }
  $('cmp-add').onclick = () => {
    const r = { si: state.sido, gi: state.sido < 0 ? -1 : state.sgg };
    if (state.cmp.length >= 7 || state.cmp.some(x => x.si === r.si && x.gi === r.gi)) return;
    state.cmp.push(r); renderChips(); renderCompare();
  };
  $('cmp-chips').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.id === 'cmp-clear') state.cmp = []; else state.cmp.splice(+b.dataset.i, 1);
    renderChips(); renderCompare();
  });
  const visOf = r => {
    if (!visits) return null;
    if (r.si >= 0) return r.gi < 0 ? visits.sido[r.si] : visits.sgg[r.si][r.gi];
    const out = [visits.q.map(() => null), visits.q.map(() => null)];
    for (const v of visits.sido) if (v) for (let j = 0; j < 2; j++) v[j].forEach((x, i) => { if (x != null) out[j][i] = (out[j][i] || 0) + x; });
    return out;
  };
  function visPeriods() {
    // 분기 또는 연도 단위로 묶고, 자료가 95% 미만인 기간(진행 중)을 표시
    const q = visits.q, daysIn = k => { const y = +k.slice(0, 4), leap = (y % 4 === 0) ? 1 : 0;
      return k.length === 4 ? 365 + leap : [90 + leap, 91, 92, 92][+k[5] - 1]; };
    const keys = [], idx = [];
    q.forEach((k, i) => { const key = state.vt.per === 'y' ? k.slice(0, 4) : k; let j = keys.indexOf(key); if (j < 0) { keys.push(key); idx.push([]); j = keys.length - 1; } idx[j].push(i); });
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
    const Y3 = yNow - 3, inW = y => y > Y3 && y <= yNow, st = [0, 0, 0], tr = { nw: 0, cl: 0, base: 0 }, py = {};
    for (const c of cube) {
      if (!state.types.has(c[2]) || !inReg(r, c[0], c[1])) continue;
      st[c[3]] += c[5];
      if (c[4]) py[c[4]] = (py[c[4]] || 0) + c[5];
      if (inW(c[4])) tr.nw += c[5];
      if (c[3] < 2 && c[4] && c[4] <= Y3) tr.base += c[5];
    }
    for (const c of close) {
      if (!state.types.has(c[2]) || !inReg(r, c[0], c[1])) continue;
      if (inW(c[3])) tr.cl += c[5];
      if (c[4] && c[4] <= Y3 && c[3] > Y3) tr.base += c[5];
    }
    let mb = 0;
    for (const m of minbak) if (m[2] === 0 && inReg(r, m[0], m[1])) mb += m[5];
    const v = r.si < 0 ? S.reduce((a, s) => s.vis ? [a[0] + s.vis[0], a[1] + s.vis[1]] : a, [0, 0]) : (r.gi < 0 ? S[r.si].vis : (S[r.si].visg || [])[r.gi]);
    return { st, tr, py, mb, v };
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
    // 연도별 신규 인허가
    const years = []; for (let y = yNow - 19; y <= yNow; y++) years.push(y);
    $('cp-legend').innerHTML = legend;
    lineChart($('cp'), $('cp-tip'), years.map(String), R.map((r, i) => ({ name: regLabel(r), color: cols[i], vals: years.map(y => stats[i].py[y] || 0) })),
      { partial: years.map(y => y === yNow), div: 1, unit: fmt, tip: v => fmt(v) + '곳' });
  }
  $('vt-per').addEventListener('click', e => { const b = e.target.closest('button'); if (b) { state.vt.per = b.dataset.v; renderCompare(); } });
  $('vt-kind').addEventListener('click', e => { const b = e.target.closest('button'); if (b) { state.vt.kind = b.dataset.v; renderCompare(); } });

  /* ---------- 관광 수요 대비 숙소 ----------
     관광지·방문객 수는 시군구까지만 있으므로 이 칸은 시군구 단위에서 멈춥니다. */
  const VIS = meta.visitors;
  const tourSel = g => g ? g.reduce((s, v, i) => s + (state.tour.has(i) ? v : 0), 0) : 0;
  let supToken = 0, supRows = [];
  async function renderSupply() {
    const token = ++supToken, si = state.sido, gi = state.sgg, mode = state.sup;
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
    const v = state.sido < 0 ? S.reduce((a, s) => a + (s.vis ? s.vis[1] : 0), 0)
      : state.sgg < 0 ? (S[state.sido].vis || [0, 0])[1] : ((S[state.sido].visg || [])[state.sgg] || [0, 0])[1];
    const vReg = state.sido < 0 ? '전국' : state.sgg < 0 ? S[state.sido].name : S[state.sido].sgg[state.sgg];
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
    const areas = Object.entries(area).map(([k, x]) => [k, x, x.reduce((p, q) => p + q, 0)]).sort((p, q) => q[2] - p[2]).slice(0, 20);
    $('mb-area-title').textContent = level() >= 4 ? '' : `도시민박이 몰린 ${childLabel()} (상위 20곳) · 건물 용도별`;
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
    const Y0 = yNow - 19, years = [];
    for (let y = Y0; y <= yNow; y++) years.push(y);
    const m = years.map(y => byYear[y] || CATS.map(() => 0)), tot = m.map(r => r.reduce((p, q) => p + q, 0));
    const step = niceStep(Math.max(1, ...tot)), top = Math.ceil(Math.max(1, ...tot) / step) * step;
    const L = 52, R = 8, Tp = 18, B = 26, W = 900, H = 300, iw = W - L - R, ih = H - Tp - B, bw = iw / years.length;
    let s = axis(top, step, L, R, Tp, ih, W);
    years.forEach((yv, i) => {
      const x = L + i * bw + bw * .16, w = bw * .68; let acc = 0;
      m[i].forEach((c, ci) => { if (!c) return; const y = Tp + ih - (acc + c) / top * ih; acc += c;
        s += `<rect x="${x}" y="${y}" width="${w}" height="${Math.max(c / top * ih, .5)}" fill="var(--c${ci})" stroke="var(--panel)" stroke-width="1.5"/>`; });
      if (tot[i]) s += `<text class="tot" x="${x + w / 2}" y="${Tp + ih - tot[i] / top * ih - 4}" text-anchor="middle">${fmt(tot[i])}</text>`;
      if (i % 2 === 0 || i === years.length - 1) s += `<text x="${x + w / 2}" y="${H - 8}" text-anchor="middle">${yv === yNow ? yv + '*' : yv}</text>`;
      s += `<rect data-i="${i}" x="${L + i * bw}" y="${Tp}" width="${bw}" height="${ih}" fill="transparent"/>`;
    });
    $('year').innerHTML = s;
    $('year-legend').innerHTML = CATS.map((c, i) => `<span><i style="background:var(--c${i})"></i>${esc(c)}</span>`).join('');
    $('year-sub').textContent = `${regionName()} · 최근 20년 · ${yNow}년은 진행 중`;
    attachTip($('year'), $('year-tip'), i => `<b>${years[i]}년 ${fmt(tot[i])}곳</b><br>` + m[i].map((c, ci) => c ? `<span class="sw" style="background:var(--c${ci})"></span>${esc(CATS[ci])} ${fmt(c)}<br>` : '').join(''));
  }
  function drawOpenClose(openY, closeY) {
    const Y0 = yNow - 19, years = [];
    for (let y = Y0; y <= yNow; y++) years.push(y);
    const o = years.map(y => openY[y] || 0), c = years.map(y => closeY[y] || 0);
    const mx = Math.max(1, ...o, ...c), step = niceStep(mx), top = Math.ceil(mx / step) * step;
    const L = 52, R = 8, Tp = 18, B = 26, W = 900, H = 280, iw = W - L - R, ih = H - Tp - B, bw = iw / years.length;
    let s = axis(top, step, L, R, Tp, ih, W);
    years.forEach((yv, i) => {
      const w = bw * .34, x1 = L + i * bw + bw * .14, x2 = x1 + w + 1;
      if (o[i]) s += `<rect x="${x1}" y="${Tp + ih - o[i] / top * ih}" width="${w}" height="${o[i] / top * ih}" fill="var(--c0)" rx="1.5"/>`;
      if (c[i]) s += `<rect x="${x2}" y="${Tp + ih - c[i] / top * ih}" width="${w}" height="${c[i] / top * ih}" fill="var(--closed)" rx="1.5"/>`;
      if (i % 2 === 0 || i === years.length - 1) s += `<text x="${L + i * bw + bw / 2}" y="${H - 8}" text-anchor="middle">${yv === yNow ? yv + '*' : yv}</text>`;
      s += `<rect data-i="${i}" x="${L + i * bw}" y="${Tp}" width="${bw}" height="${ih}" fill="transparent"/>`;
    });
    $('oc').innerHTML = s;
    attachTip($('oc'), $('oc-tip'), i => `<b>${years[i]}년</b><br><span class="sw" style="background:var(--c0)"></span>인허가 ${fmt(o[i])}<br><span class="sw" style="background:var(--closed)"></span>폐업 ${fmt(c[i])}<br>순증 ${o[i] - c[i] >= 0 ? '+' : ''}${fmt(o[i] - c[i])}`);
  }

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
  update(false);
})();
