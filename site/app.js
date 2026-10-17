/* Dashboard logic. Data files (built by scripts/build.py):
   data/meta.json  – lists (types, 시도/시군구, centroids) and build stats
   data/cube.json  – [sidoIdx, sggIdx, typeIdx, status, year, count] aggregates for charts
   data/pts/<sidoIdx>.json – [lat, lon, typeIdx, sggIdx, status, year, name, addr, date, closed, approx] */
(async function () {
  const $ = id => document.getElementById(id);
  const fmt = n => n.toLocaleString('ko-KR');
  const esc = s => String(s ?? '').replace(/[&<>"]/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[m]));
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const [meta, cube] = await Promise.all([fetch('data/meta.json').then(r => r.json()), fetch('data/cube.json').then(r => r.json())]);
  const T = meta.types, CATS = meta.categories, S = meta.sido, ST = meta.status;
  const catOf = T.map(t => CATS.indexOf(t.cat));
  const col = c => css('--c' + c);

  const state = { sido: -1, sgg: -1, status: 0, types: new Set(T.map((_, i) => i)) };
  $('updated').textContent = `마지막 갱신 ${meta.updated}.`;

  /* ---------- filters ---------- */
  $('f-sido').insertAdjacentHTML('beforeend', S.map((s, i) => `<option value="${i}">${esc(s.name)}</option>`).join(''));
  function fillSgg() {
    const sel = $('f-sgg');
    sel.innerHTML = '<option value="-1">전체</option>' + (state.sido < 0 ? '' : S[state.sido].sgg.map((g, i) => `<option value="${i}">${esc(g)}</option>`).join(''));
    sel.disabled = state.sido < 0;
  }
  $('f-sido').onchange = e => { state.sido = +e.target.value; state.sgg = -1; fillSgg(); update(true); };
  $('f-sgg').onchange = e => { state.sgg = +e.target.value; update(true); };
  $('f-status').onchange = e => { state.status = +e.target.value; update(false); };

  // type list grouped by category
  const typeTotals = T.map(() => 0);
  cube.forEach(r => { typeTotals[r[2]] += r[5]; });
  $('typelist').innerHTML = CATS.map((c, ci) => {
    const items = T.map((t, i) => [t, i]).filter(([t]) => t.cat === c);
    if (!items.length) return '';
    return `<div class="cat">${esc(c)}</div>` + items.map(([t, i]) =>
      `<div class="chk"><input type="checkbox" id="t${i}" data-i="${i}" checked><label for="t${i}"><span class="sw" style="background:var(--c${ci})"></span>${esc(t.name)}</label><span class="n" id="tn${i}"></span></div>`).join('');
  }).join('');
  $('typelist').addEventListener('change', e => { const i = +e.target.dataset.i; e.target.checked ? state.types.add(i) : state.types.delete(i); update(false); });
  $('t-all').onclick = () => { T.forEach((_, i) => { state.types.add(i); $('t' + i).checked = true; }); update(false); };
  $('t-none').onclick = () => { state.types.clear(); T.forEach((_, i) => { $('t' + i).checked = false; }); update(false); };

  /* ---------- aggregation ---------- */
  const inRegion = r => (state.sido < 0 || r[0] === state.sido) && (state.sgg < 0 || r[1] === state.sgg);
  const inStatus = r => state.status < 0 || r[3] === state.status;
  function agg(regionFn = inRegion, useTypes = true) {
    const byType = T.map(() => 0), byYear = {}, byArea = {};
    let total = 0;
    for (const r of cube) {
      if (!regionFn(r) || !inStatus(r)) continue;
      if (useTypes && !state.types.has(r[2])) continue;
      byType[r[2]] += r[5]; total += r[5];
      const key = state.sido < 0 ? r[0] : r[1];
      byArea[key] = (byArea[key] || 0) + r[5];
      if (r[4]) { (byYear[r[4]] ||= CATS.map(() => 0))[catOf[r[2]]] += r[5]; }
    }
    return { byType, byYear, byArea, total };
  }
  const regionName = () => state.sido < 0 ? '전국' : S[state.sido].name + (state.sgg < 0 ? '' : ' ' + S[state.sido].sgg[state.sgg]);

  /* ---------- map ---------- */
  if (typeof maplibregl === 'undefined') { $('map').innerHTML = '<p class="note" style="padding:16px">지도 라이브러리를 불러오지 못했습니다. 새로고침해 주세요.</p>'; }
  const map = typeof maplibregl === 'undefined' ? null : new maplibregl.Map({
    container: 'map', style: 'https://tiles.openfreemap.org/styles/positron',
    center: [127.8, 36.2], zoom: 5.6, attributionControl: { compact: true }
  });
  const ptsCache = {};
  let mapReady = false;
  if (map) map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
  if (map) map.on('load', () => {
    mapReady = true;
    map.addSource('areas', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    map.addLayer({ id: 'areas', type: 'circle', source: 'areas', paint: {
      'circle-radius': ['interpolate', ['linear'], ['sqrt', ['get', 'n']], 0, 0, 10, 6, 60, 26],
      'circle-color': '#2a78d6', 'circle-opacity': .45, 'circle-stroke-color': '#fff', 'circle-stroke-width': 1 } });
    map.addSource('pts', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    map.addLayer({ id: 'pts', type: 'circle', source: 'pts', paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 2.2, 11, 3.6, 15, 6],
      'circle-color': ['match', ['get', 'c'], ...CATS.flatMap((_, i) => [i, col(i)]), '#888'],
      'circle-opacity': .85, 'circle-stroke-color': '#fff', 'circle-stroke-width': .6 } });
    map.on('click', 'pts', e => {
      const p = e.features[0].properties;
      new maplibregl.Popup({ maxWidth: '280px' }).setLngLat(e.lngLat).setHTML(
        `<b>${esc(p.name)}</b><br>${esc(T[p.t].name)} · ${ST[p.s]}<br>${esc(p.addr)}<br><small>인허가 ${esc(p.date)}${p.closed ? ' · 폐업 ' + esc(p.closed) : ''}${p.ap ? ' · 위치는 동 단위 근사' : ''}</small>`).addTo(map);
    });
    map.on('click', 'areas', e => {
      const p = e.features[0].properties;
      $('f-sido').value = p.si; state.sido = p.si; fillSgg(); state.sgg = p.gi; $('f-sgg').value = p.gi; update(true);
    });
    for (const l of ['pts', 'areas']) {
      map.on('mouseenter', l, () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', l, () => { map.getCanvas().style.cursor = ''; });
    }
    update(true);
  });

  async function loadPts(si) {
    if (!ptsCache[si]) ptsCache[si] = fetch(`data/pts/${si}.json`).then(r => r.json());
    return ptsCache[si];
  }
  async function drawMap(fly) {
    if (!mapReady) return;
    if (state.sido < 0) {
      // national: one bubble per 시군구 (count under current filters)
      const cnt = {};
      for (const r of cube) if (inStatus(r) && state.types.has(r[2])) cnt[r[0] + ':' + r[1]] = (cnt[r[0] + ':' + r[1]] || 0) + r[5];
      const feats = [];
      S.forEach((s, si) => s.sgg.forEach((g, gi) => {
        const c = s.sggc[gi], n = cnt[si + ':' + gi] || 0;
        if (c && n) feats.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [c[1], c[0]] }, properties: { n, si, gi } });
      }));
      map.getSource('areas').setData({ type: 'FeatureCollection', features: feats });
      map.getSource('pts').setData({ type: 'FeatureCollection', features: [] });
      if (fly) map.flyTo({ center: [127.8, 36.2], zoom: 5.6 });
      return;
    }
    map.getSource('areas').setData({ type: 'FeatureCollection', features: [] });
    const si = state.sido, pts = await loadPts(si);
    if (si !== state.sido) return;
    const feats = [];
    let minx = 180, miny = 90, maxx = -180, maxy = -90;
    for (const p of pts) {
      if (state.sgg >= 0 && p[3] !== state.sgg) continue;
      if (!state.types.has(p[2]) || (state.status >= 0 && p[4] !== state.status)) continue;
      feats.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [p[1], p[0]] },
        properties: { t: p[2], c: catOf[p[2]], s: p[4], name: p[6], addr: p[7], date: p[8], closed: p[9], ap: p[10] } });
      minx = Math.min(minx, p[1]); maxx = Math.max(maxx, p[1]); miny = Math.min(miny, p[0]); maxy = Math.max(maxy, p[0]);
    }
    map.getSource('pts').setData({ type: 'FeatureCollection', features: feats });
    if (fly && feats.length) map.fitBounds([[minx, miny], [maxx, maxy]], { padding: 40, maxZoom: 14, duration: 800 });
  }

  /* ---------- KPIs and charts ---------- */
  function update(fly) {
    const a = agg(), nat = agg(() => true);
    T.forEach((_, i) => { $('tn' + i).textContent = fmt(agg(inRegion, false).byType[i]); });
    const topT = a.byType.map((v, i) => [v, i]).sort((x, y) => y[0] - x[0])[0];
    const yNow = new Date().getFullYear();
    const recent = [yNow - 2, yNow - 1, yNow].reduce((s, y) => s + (a.byYear[y] ? a.byYear[y].reduce((p, q) => p + q, 0) : 0), 0);
    const areaNames = state.sido < 0 ? S.map(s => s.name) : S[state.sido].sgg;
    const topA = Object.entries(a.byArea).sort((x, y) => y[1] - x[1])[0];
    const stLabel = state.status < 0 ? '전체 상태' : ST[state.status];
    $('kpis').innerHTML = [
      [fmt(a.total), `${regionName()} · ${stLabel}`],
      [topT && topT[0] ? esc(T[topT[1]].name) : '-', topT && a.total ? `최다 업종 (${(topT[0] / a.total * 100).toFixed(1)}%)` : '최다 업종'],
      [fmt(recent), `${yNow - 2}~${yNow}년 인허가`],
      [topA && state.sgg < 0 ? esc(areaNames[topA[0]]) : '-', topA && state.sgg < 0 ? `가장 많은 ${state.sido < 0 ? '광역' : '기초'} (${fmt(topA[1])})` : '가장 많은 지역'],
    ].map(k => `<div class="kpi"><b>${k[0]}</b><span>${k[1]}</span></div>`).join('');

    // share by sub-type (compares with national share when a region is chosen)
    const order = T.map((_, i) => i).filter(i => state.types.has(i)).sort((x, y) => a.byType[y] - a.byType[x]);
    const mx = Math.max(1e-9, ...order.map(i => a.byType[i] / (a.total || 1)), ...(state.sido < 0 ? [] : order.map(i => nat.byType[i] / (nat.total || 1))));
    $('share').innerHTML = order.map(i => {
      const p = a.byType[i] / (a.total || 1), np = nat.byType[i] / (nat.total || 1);
      return `<div class="row"><span class="nm"><span class="sw" style="background:var(--c${catOf[i]})"></span><span>${esc(T[i].name)}</span></span>
        <span class="track"><i style="width:${p / mx * 100}%;background:var(--c${catOf[i]})"></i>${state.sido < 0 ? '' : `<b style="left:calc(${np / mx * 100}% - 1px)"></b>`}</span>
        <span class="val">${(p * 100).toFixed(1)}%<em>${fmt(a.byType[i])}곳</em></span></div>`;
    }).join('') || '<p class="note">선택한 업종이 없습니다.</p>';
    $('share-sub').textContent = topT && a.total ? `${regionName()}(${stLabel}) ${fmt(a.total)}곳 중 ${T[topT[1]].name} 비중이 ${(topT[0] / a.total * 100).toFixed(1)}%로 가장 큽니다.` : '';

    drawYears(a.byYear);

    // ranking
    $('rank-title').textContent = state.sido < 0 ? '광역별 시설 수' : `${S[state.sido].name} 기초별 시설 수`;
    const ranks = Object.entries(a.byArea).sort((x, y) => y[1] - x[1]);
    const rmax = ranks.length ? ranks[0][1] : 1;
    $('rank').innerHTML = ranks.map(([k, v]) => `<button class="row" data-k="${k}"><span class="nm"><span>${esc(areaNames[k])}</span></span>
      <span class="track"><i style="width:${v / rmax * 100}%;background:var(--c0)"></i></span><span class="val">${fmt(v)}<em>${(v / (a.total || 1) * 100).toFixed(1)}%</em></span></button>`).join('');
    drawMap(fly);
  }
  $('rank').addEventListener('click', e => {
    const b = e.target.closest('button.row'); if (!b) return;
    const k = +b.dataset.k;
    if (state.sido < 0) { state.sido = k; $('f-sido').value = k; fillSgg(); state.sgg = -1; }
    else { state.sgg = k; $('f-sgg').value = k; }
    update(true);
  });

  function drawYears(byYear) {
    const yNow = new Date().getFullYear(), Y0 = yNow - 19, years = [];
    for (let y = Y0; y <= yNow; y++) years.push(y);
    const m = years.map(y => byYear[y] || CATS.map(() => 0)), tot = m.map(r => r.reduce((p, q) => p + q, 0));
    const mx = Math.max(1, ...tot), step = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000].find(s => mx / s <= 5) || 10000, top = Math.ceil(mx / step) * step;
    const L = 52, R = 8, Tp = 18, B = 26, W = 900, H = 300, iw = W - L - R, ih = H - Tp - B, bw = iw / years.length;
    let s = '';
    for (let v = 0; v <= top; v += step) { const y = Tp + ih - v / top * ih; s += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y}" y2="${y}"/><text x="${L - 8}" y="${y + 4}" text-anchor="end">${fmt(v)}</text>`; }
    years.forEach((yv, i) => {
      const x = L + i * bw + bw * .16, w = bw * .68; let acc = 0;
      m[i].forEach((c, ci) => { if (!c) return; const y = Tp + ih - (acc + c) / top * ih; acc += c;
        s += `<rect x="${x}" y="${y}" width="${w}" height="${Math.max(c / top * ih, .5)}" fill="var(--c${ci})" stroke="var(--panel)" stroke-width="1.5"/>`; });
      if (tot[i]) s += `<text class="tot" x="${x + w / 2}" y="${Tp + ih - tot[i] / top * ih - 4}" text-anchor="middle">${fmt(tot[i])}</text>`;
      if (i % 2 === 0 || i === years.length - 1) s += `<text x="${x + w / 2}" y="${H - 8}" text-anchor="middle">${yv === yNow ? yv + '*' : yv}</text>`;
      s += `<rect data-i="${i}" x="${L + i * bw}" y="${Tp}" width="${bw}" height="${ih}" fill="transparent"/>`;
    });
    const svg = $('year'); svg.innerHTML = s;
    $('year-legend').innerHTML = CATS.map((c, i) => `<span><i style="background:var(--c${i})"></i>${esc(c)}</span>`).join('');
    $('year-sub').textContent = `${regionName()} · 최근 20년 · ${yNow}년은 진행 중`;
    const tip = $('year-tip'), wrap = svg.parentElement;
    svg.onmousemove = e => {
      const r = e.target.closest('rect[data-i]'); if (!r) { tip.hidden = true; return; }
      const i = +r.dataset.i;
      tip.innerHTML = `<b>${years[i]}년 ${fmt(tot[i])}곳</b><br>` + m[i].map((c, ci) => c ? `<span class="sw" style="background:var(--c${ci})"></span>${esc(CATS[ci])} ${fmt(c)}<br>` : '').join('');
      tip.hidden = false; const b = wrap.getBoundingClientRect();
      tip.style.left = Math.min(e.clientX - b.left + 14, b.width - tip.offsetWidth - 4) + 'px'; tip.style.top = (e.clientY - b.top + 10) + 'px';
    };
    svg.onmouseleave = () => { tip.hidden = true; };
  }

  const c = meta.coords, d = meta.dedupe;
  $('foot').textContent = `숙박업과 관광숙박업에 함께 등록된 시설 ${fmt(d.removed)}건은 관광숙박업으로만 셌습니다. 좌표가 없는 야영장 ${fmt(c.dropped_campgrounds)}곳은 제외했고, 좌표가 없는 그 밖의 시설 ${fmt(c.no_coords)}곳은 통계에는 넣고 지도에서는 뺐습니다. 출처: 행정안전부 지방행정인허가 API(공공데이터포털).`;
  update(false);
})();
