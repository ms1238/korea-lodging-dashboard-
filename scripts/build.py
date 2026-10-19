"""Normalize raw/<endpoint>.jsonl into the compact files the dashboard reads (site/data/).

Steps
1. Map each API's own columns onto one schema (name, address, type, status, dates, coordinates).
2. Convert CRD_INFO_X/Y from EPSG:5174 (Bessel TM, central belt) to WGS84.
3. Derive 시도/시군구 from the address and unify renamed provinces.
4. Drop 숙박업 records that duplicate a 관광숙박업 record (same address + similar name).
5. Drop campground records without coordinates; give other records without coordinates
   the median position of the same 시군구+동 when possible.
6. Write meta.json, cube.json / close.json (national aggregates; close rows carry 폐업 and 인허가 year) and
   pts/<sido>.json (every record of the province with 읍면동·리 indices, for detail views).
7. Tourist attractions (TourAPI): tour/<sido>.json, already in WGS84, with the number of
   operating lodgings within 1 km and 3 km of each attraction.
8. 외국인관광 도시민박: 용도지역·건물용도 groups (minbak.json for the national view).
9. Visitors (KTO DataLab): 외지인 and 외국인 visitors per 시도 and 시군구 over the latest 12 months (meta.json)
   and per quarter since 2018 (visits.json).
10. Foreign arrivals (한국문화관광연구원 출입국관광통계): national monthly totals and the top nationalities (arrivals.json).
11. National parks: TourAPI attractions named "…국립공원" (plus 한라산·금정산, listed without the word) for the map (parks.json).
12. cubeq.json / closeq.json: the last six years by quarter (year*10 + quarter) for the quarterly charts.
13. subway.json: subway / light-rail lines (OpenStreetMap) as GeoJSON with each line's colour.
14. park_areas.json: national-park boundaries (OpenStreetMap) as simplified polygons with their map area;
    금정산 falls back to the boundary traced from the designation map (scripts/static/geumjeongsan.json).
15. stations.json: subway / light-rail stations (OpenStreetMap) with their lines, 시도/시군구 and the number of
    operating lodgings per type within 0.5 / 1 / 3 / 5 km (records with an exact position only), plus the monthly
    boardings / alightings of 코레일 광역철도 stations matched by name (latest 12 months).
16. icn.json: 인천공항 arriving / departing passengers per month and the top countries of the route.
17. kac.json: passengers per airport and year, domestic / international (한국공항공사 공항별 여객실적).
"""
import difflib
import glob
import json
import math
import os
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from pyproj import Transformer

ROOT = os.path.join(os.path.dirname(__file__), "..")
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "site", "data")

# endpoint -> (category, column holding the sub-type or None, fixed sub-type)
SOURCES = {
    "lodgings": ("숙박업", ["SNTTN_BZSTAT_NM", "BZSTAT_SE_NM"], "숙박업(기타)"),
    "tourist_accommodations": ("관광숙박업", ["TOUR_LDGBIZ_DTL_NM"], "관광숙박업(기타)"),
    "foreigner_city_homestays": ("외국인관광 도시민박업", [], "외국인관광 도시민박업"),
    "rural_homestays": ("농어촌민박업", [], "농어촌민박업"),
    "tourist_pensions": ("관광펜션업", [], "관광펜션업"),
    "hanok_experience": ("한옥체험업", [], "한옥체험업"),
    "general_campgrounds": ("야영장업", [], "일반야영장업"),
    "auto_campgrounds": ("야영장업", [], "자동차야영장업"),
}
CATEGORIES = ["숙박업", "관광숙박업", "외국인관광 도시민박업", "농어촌민박업", "관광펜션업", "한옥체험업", "야영장업"]
CAMP = {"general_campgrounds", "auto_campgrounds"}
TOUR_TYPES = [("12", "관광지"), ("14", "문화시설"), ("28", "레포츠")]
STATUS = ["영업", "휴업", "폐업"]  # 폐업 also covers 취소·말소·만료 etc.
ZONES = ["주거지역", "상업지역", "공업지역", "녹지·관리지역", "미상"]
BLDGS = ["아파트", "다세대·연립", "단독·다가구", "기타", "미상"]


def zone_of(s):
    s = clean(s)
    if not s:
        return 4
    return 0 if "주거" in s else 1 if "상업" in s else 2 if "공업" in s else 3


def bldg_of(s):
    s = clean(s)
    if not s:
        return 4
    if "아파트" in s:
        return 0
    if "다세대" in s or "연립" in s:
        return 1
    if "단독" in s or "다가구" in s or "다중" in s:
        return 2
    return 3

SIDO_ALIASES = {
    "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시",
    "광주": "광주광역시", "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시",
    "경기": "경기도", "강원": "강원특별자치도", "강원도": "강원특별자치도",
    "충북": "충청북도", "충남": "충청남도", "전북": "전북특별자치도", "전라북도": "전북특별자치도",
    "전남": "전라남도", "경북": "경상북도", "경남": "경상남도", "제주": "제주특별자치도",
    "제주도": "제주특별자치도",
}
MERGED_GWANGJU_JEONNAM = "전남광주통합특별시"
GWANGJU_GU = ["동구", "서구", "남구", "북구", "광산구"]  # 통합 이전 광주광역시; the page offers them as one group "광주시"

to_wgs84 = Transformer.from_crs("EPSG:5174", "EPSG:4326", always_xy=True)
KST = timezone(timedelta(hours=9))


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def status_of(rec):
    s = clean(rec.get("SALS_STTS_NM")) + " " + clean(rec.get("DTL_SALS_STTS_NM"))
    if "휴업" in s:
        return 1
    if "영업" in s or "정상" in s:
        return 0
    return 2


def ymd(s):
    s = re.sub(r"[^0-9]", "", str(s or ""))
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) >= 8 else ""


def coords(rec):
    try:
        x, y = float(rec.get("CRD_INFO_X")), float(rec.get("CRD_INFO_Y"))
    except (TypeError, ValueError):
        return None
    if not (x and y):
        return None
    lon, lat = to_wgs84.transform(x, y)
    if 32.8 < lat < 38.9 and 124.2 < lon < 132.2:  # Korea incl. Jeju, Ulleung, Dokdo
        return round(lat, 5), round(lon, 5)
    return None


def region(addr, merged):
    toks = clean(addr).split(" ")
    if not toks or not toks[0]:
        return None, None
    sido = SIDO_ALIASES.get(toks[0], toks[0])
    if merged and sido in ("광주광역시", "전라남도"):
        sido = MERGED_GWANGJU_JEONNAM
    if not re.search(r"(특별시|광역시|특별자치시|특별자치도|도|통합특별시)$", sido):
        return None, None
    if sido == "세종특별자치시":
        return sido, "세종특별자치시"
    sgg = toks[1] if len(toks) > 1 else ""
    if not re.search(r"(시|군|구)$", sgg):
        return sido, None
    return sido, sgg  # 일반구(예: 수원시 영통구)는 시 단위로 묶음


def emd_ri(lot, road, sgg):
    """법정 읍·면·동 and 리 from the lot address (road address as fallback for 동/읍/면)."""
    toks = clean(lot).split(" ")[2:]
    if toks and re.search(r"구$", toks[0]) and sgg.endswith("시"):
        toks = toks[1:]  # 일반구 (예: 수원시 영통구)
    emd = ri = None
    if toks and re.search(r"(읍|면|동|가|로)$", toks[0]) and not re.match(r"^\d", toks[0]):
        emd = toks[0]
        if emd.endswith(("읍", "면")) and len(toks) > 1 and toks[1].endswith("리"):
            ri = toks[1]
    if not emd:
        m = re.search(r"\s(\S+[읍면])\s", " " + clean(road) + " ")
        if m:
            emd = m.group(1)
        else:
            m = re.search(r"\(([^,()]+?[동가])(?:,|\))", clean(road))
            emd = m.group(1) if m else None
    return emd, ri


def addr_key(addr):
    """Road address without unit/floor detail: '부산광역시 동구 중앙대로 179번길 17'."""
    a = clean(addr)
    a = re.sub(r"\(.*?\)", "", a)
    a = a.split(",")[0]
    return re.sub(r"\s+", "", a)


def name_key(name):
    n = clean(name).lower()
    n = re.sub(r"\(.*?\)", "", n)
    n = re.sub(r"[^0-9a-z가-힣]", "", n)
    for w in ("관광호텔", "호텔", "hotel", "모텔", "motel", "호스텔", "hostel", "레지던스", "주식회사", "㈜"):
        n = n.replace(w, "")
    return n


def similar(a, b):
    a, b = name_key(a), name_key(b)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.6


def load():
    rows = []
    for ep, (cat, cols, default) in SOURCES.items():
        path = os.path.join(RAW, f"{ep}.jsonl")
        if not os.path.exists(path):
            raise SystemExit(f"missing {path}; run scripts/fetch.py first")
        with open(path, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                sub = next((clean(rec.get(c)) for c in cols if clean(rec.get(c))), default)
                rows.append({
                    "src": ep, "cat": cat, "type": sub,
                    "name": clean(rec.get("BPLC_NM")),
                    "road": clean(rec.get("ROAD_NM_ADDR")), "lot": clean(rec.get("LOTNO_ADDR")),
                    "status": status_of(rec),
                    "date": ymd(rec.get("LCPMT_YMD")), "closed": ymd(rec.get("CLSBIZ_YMD")),
                    "ll": coords(rec), "id": clean(rec.get("MNG_NO")),
                    "zone": zone_of(rec.get("RGN_SE_NM")) if ep == "foreigner_city_homestays" else -1,
                    "bldg": bldg_of(rec.get("BLDG_USG_NM")) if ep == "foreigner_city_homestays" else -1,
                })
    return rows


def dedupe(rows):
    """Remove 숙박업 rows that are the same facility as a 관광숙박업 row."""
    tour = [r for r in rows if r["src"] == "tourist_accommodations"]
    by_addr = defaultdict(list)
    for r in tour:
        for a in (r["road"], r["lot"]):
            if a:
                by_addr[addr_key(a)].append(r)
    removed, examples = 0, []
    keep = []
    for r in rows:
        if r["src"] == "lodgings":
            cands = by_addr.get(addr_key(r["road"]), []) + by_addr.get(addr_key(r["lot"]), [])
            hit = next((t for t in cands if similar(r["name"], t["name"])), None)
            if hit:
                removed += 1
                if len(examples) < 20:
                    examples.append([r["name"], r["type"], hit["name"], hit["type"], r["road"] or r["lot"]])
                continue
        keep.append(r)
    return keep, removed, examples


def add_visitors(sidos, sgg_of, sido_meta):
    """Visitors from KTO DataLab monthly sums (외지인 kind 2, 외국인 kind 3).

    sido_meta[i]["vis"] / ["visg"]: [외지인, 외국인] over the latest 12 months, scaled to 365 days; areas reported
    for fewer days (e.g. 인천 구 created in 2026) are listed under "partial".
    Returns (meta block, quarterly series for visits.json). Old 광주광역시/전라남도 rows count toward
    전남광주통합특별시; a 시군구 that moved between 시도 (군위군) is matched by its unique name."""
    def read(name):
        path = os.path.join(RAW, f"{name}.jsonl")
        return [json.loads(l) for l in open(path, encoding="utf-8")] if os.path.exists(path) else []
    sido_rows, sgg_rows = read("datalab_sido"), read("datalab_sgg")
    if not sido_rows:
        return None, None

    def norm(name):
        if name in ("광주광역시", "전라남도") and MERGED_GWANGJU_JEONNAM in sidos:
            return MERGED_GWANGJU_JEONNAM
        return SIDO_ALIASES.get(name, name)
    code_sido = {r["code"]: norm(r["name"]) for r in sido_rows}
    by_name = defaultdict(list)
    for s in sidos:
        for g in sgg_of[s]:
            by_name[g].append(s)
    unmatched = set()

    def key_of(r, level):
        if level == "sido":
            sido = norm(r["name"])
            return (sido, None) if sido in sidos else unmatched.add(r["name"])
        if " " in r["name"]:  # 구 of a 시 (e.g. "수원시 장안구") are also reported at 시 level
            return None
        sido = code_sido.get(r["code"][:2])
        name = sido if r["name"] == sido else r["name"]  # 세종 reports itself as its only 시군구
        if sido in sidos and name in sgg_of[sido]:
            return (sido, name)
        if len(by_name.get(name, [])) == 1:
            return (by_name[name][0], name)
        unmatched.add(f"{sido} {r['name']}")

    months = sorted({r["ym"] for r in sido_rows})
    window = set(months[-12:])
    last = max(r["last"] for r in sido_rows)
    quarters = sorted({f"{ym[:4]}Q{(int(ym[4:]) - 1) // 3 + 1}" for ym in months})
    qi = {q: i for i, q in enumerate(quarters)}
    year_sum, year_days = defaultdict(lambda: [0, 0]), defaultdict(lambda: defaultdict(int))
    series = defaultdict(lambda: [[None] * len(quarters), [None] * len(quarters)])
    for level, rows in (("sido", sido_rows), ("sgg", sgg_rows)):
        for r in rows:
            if r["kind"] not in ("2", "3"):
                continue
            k = key_of(r, level)
            if not k:
                continue
            j = int(r["kind"]) - 2
            arr = series[k][j]
            q = qi[f"{r['ym'][:4]}Q{(int(r['ym'][4:]) - 1) // 3 + 1}"]
            arr[q] = (arr[q] or 0) + r["n"]
            if r["ym"] in window:
                year_sum[k][j] += r["n"]
                year_days[k][r["ym"]] = max(year_days[k][r["ym"]], r["days"])
    full = max(sum(year_days[(s, None)].values()) for s in sidos if (s, None) in year_days)
    partial = []

    def year(k):
        if k not in year_sum:
            return None
        n = sum(year_days[k].values())
        if n < full * 0.95:
            partial.append(" ".join(x for x in k if x))
        return [round(v * 365 / n) for v in year_sum[k]]
    for s, sm in zip(sidos, sido_meta):
        sm["vis"] = year((s, None))
        sm["visg"] = [year((s, g)) for g in sm["sgg"]]
    # days covered per quarter (national), so the page can mark the quarter still in progress
    qdays = [0] * len(quarters)
    for ym in months:
        days = max(r["days"] for r in sido_rows if r["ym"] == ym)
        qdays[qi[f"{ym[:4]}Q{(int(ym[4:]) - 1) // 3 + 1}"]] += days
    visits = {"q": quarters, "qdays": qdays, "last": last,
              "sido": [series.get((s, None)) for s in sidos],
              "sgg": [[series.get((s, g)) for g in sgg_of[s]] for s in sidos]}
    first_month = min(window)
    meta = {"from": first_month + "01", "to": last, "partial": partial, "unmatched": sorted(unmatched)}
    return meta, visits


def write_parks():
    """TourAPI has no national-park category of its own, so take attractions whose title names a 국립공원
    (skipping parking lots, campsites, centres and viewpoints). Some parks appear only under the mountain's name."""
    aliases = {"한라산": "한라산국립공원", "금정산": "금정산국립공원"}  # 금정산: 24th national park, in force from 2026-03-03
    seen, out = set(), []
    for path in sorted(glob.glob(os.path.join(RAW, "tour_*.jsonl"))):
        for line in open(path, encoding="utf-8"):
            rec = json.loads(line)
            title = clean(rec.get("title"))
            t = title.replace(" ", "")
            if not ("국립공원" in t or t in aliases) or re.search(r"(사무소|탐방안내소|주차장|야영장|센터|전망대|캠핑|박물관)", t):
                continue
            if rec.get("contentid") in seen or not rec.get("mapx"):
                continue
            seen.add(rec.get("contentid"))
            m = re.match(r"국립공원공단(.+?)생태탐방원", t)  # e.g. 국립공원공단 한려해상생태탐방원
            park = aliases.get(t) or (m.group(1) + "국립공원" if m else re.sub(r"국립공원.*", "국립공원", t))
            out.append([round(float(rec["mapy"]), 5), round(float(rec["mapx"]), 5), park, title])
    with open(os.path.join(OUT, "parks.json"), "w", encoding="utf-8") as f:
        json.dump(sorted(out, key=lambda r: r[2]), f, ensure_ascii=False, separators=(",", ":"))


def write_subway():
    """One LineString per OSM way; a way shared by several routes (both directions, through-running) is drawn once
    with the colour of the first route that has one."""
    path = os.path.join(RAW, "subway.json")
    if not os.path.exists(path):
        return
    ways = {}
    for rel in json.load(open(path, encoding="utf-8")):
        colour = rel["colour"] if re.fullmatch(r"#?[0-9A-Fa-f]{6}", rel["colour"] or "") else ""
        colour = ("#" + colour.lstrip("#")) if colour else ""
        name = rel["name"] or rel["ref"]
        for wid, coords in rel["ways"]:
            if wid not in ways or (colour and not ways[wid][0]):
                ways[wid] = (colour, name, coords)
    feats = [{"type": "Feature", "properties": {"c": c or "#7f8c8d", "n": n},
              "geometry": {"type": "LineString", "coordinates": g}} for c, n, g in ways.values() if len(g) > 1]
    with open(os.path.join(OUT, "subway.json"), "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f, ensure_ascii=False, separators=(",", ":"))


def _rings(ways, tol=2e-4, gap=0.02):
    """Join member ways end to end into closed rings (OSM multipolygons split their outline into many ways).
    Endpoints within tol degrees (~20 m) count as the same node; a chain left open with its ends less than
    gap degrees (~2 km) apart, e.g. where a coastal park's outline is cut, is closed. Returns (rings, dropped)."""
    near = lambda p, q: abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol
    pending, rings, dropped = [list(w) for w in ways if len(w) > 1], [], 0
    while pending:
        ring = pending.pop()
        while not near(ring[0], ring[-1]) or len(ring) < 4:
            for i, w in enumerate(pending):
                if near(w[0], ring[-1]):
                    ring += w[1:]
                elif near(w[-1], ring[-1]):
                    ring += w[::-1][1:]
                elif near(w[-1], ring[0]):
                    ring = w[:-1] + ring
                elif near(w[0], ring[0]):
                    ring = w[::-1][:-1] + ring
                else:
                    continue
                pending.pop(i)
                break
            else:
                break
        if len(ring) >= 4 and (near(ring[0], ring[-1]) or math.dist(ring[0], ring[-1]) < gap):
            rings.append(ring if ring[0] == ring[-1] else ring + [ring[0]])
        else:
            dropped += 1
    return rings, dropped


def _simplify(pts, tol=0.0003):
    """Douglas-Peucker in degrees (~30 m)."""
    if len(pts) < 5:
        return pts
    keep, stack = [0, len(pts) - 1], [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy, best, idx = x2 - x1, y2 - y1, 0, None
        norm = math.hypot(dx, dy) or 1e-12
        for i in range(a + 1, b):
            d = abs(dy * (pts[i][0] - x1) - dx * (pts[i][1] - y1)) / norm
            if d > best:
                best, idx = d, i
        if idx is not None and best > tol:
            keep.append(idx)
            stack += [(a, idx), (idx, b)]
    return [pts[i] for i in sorted(set(keep))]


def _km2(ring):
    lat0 = sum(p[1] for p in ring) / len(ring)
    kx, ky = 111.32 * math.cos(math.radians(lat0)), 110.57
    return abs(sum(ring[i][0] * kx * ring[i + 1][1] * ky - ring[i + 1][0] * kx * ring[i][1] * ky for i in range(len(ring) - 1))) / 2


# the 24 national parks; the OSM query box also reaches Kyushu (아소쿠주국립공원)
KOREAN_PARKS = {"지리산", "경주", "계룡산", "한려해상", "설악산", "속리산", "한라산", "내장산", "가야산", "덕유산", "오대산", "주왕산",
                "태안해안", "다도해해상", "북한산", "치악산", "월악산", "소백산", "변산반도", "월출산", "무등산", "태백산", "팔공산", "금정산"}


def write_park_areas():
    """One polygon set per park; when several OSM objects describe the same park, the largest is kept."""
    best = {}
    path = os.path.join(RAW, "parks_osm.json")
    for el in json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []:
        name = el["name"].replace(" ", "")
        if "국립공원" not in name:
            continue
        park = re.sub(r"국립공원.*", "국립공원", name)
        if park.removesuffix("국립공원") not in KOREAN_PARKS:
            continue
        outer, lost = _rings([w for role, w in el["ways"] if role != "inner"])
        inner, _ = _rings([w for role, w in el["ways"] if role == "inner"])
        print(f"  park_areas {el['id']} {park}: {len(el['ways'])} ways -> {len(outer)} rings, {lost} open chains dropped", flush=True)
        if not outer:
            continue
        area = sum(_km2(r) for r in outer) - sum(_km2(r) for r in inner)
        polys = [[_simplify(r)] for r in outer]  # holes are dropped for drawing; the area above subtracts them
        if park not in best or area > best[park][0]:
            best[park] = (area, polys, "osm")
    if not any("금정산" in k for k in best):
        f = json.load(open(os.path.join(ROOT, "scripts", "static", "geumjeongsan.json"), encoding="utf-8"))
        polys = f["geometry"]["coordinates"]
        best["금정산국립공원"] = (sum(_km2(p[0]) for p in polys), polys, "traced")
    print(f"park_areas: {len(best)} parks: " + ", ".join(f"{k} {a:.0f}㎢" for k, (a, _, _) in sorted(best.items())), flush=True)
    feats = [{"type": "Feature", "properties": {"park": k, "km2": round(a, 1), "src": src},
              "geometry": {"type": "MultiPolygon", "coordinates": polys}} for k, (a, polys, src) in sorted(best.items())]
    with open(os.path.join(OUT, "park_areas.json"), "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f, ensure_ascii=False, separators=(",", ":"))


RADII = (0.5, 1, 3, 5)  # km, station catchment rings


def write_stations(rows, sidos, sgg_of, tidx):
    """Stations of the same name within 500 m (one node per line in OSM) become one station. Lines come from the
    route relations of subway.json passing within 150 m. 시도/시군구: the most common among lodgings within 1 km,
    else the nearest lodging within 10 km."""
    path = os.path.join(RAW, "stations.json")
    if not os.path.exists(path):
        return
    km_lat = 110.95

    def dist2(lat, lon, la, lo):
        kx = 111.32 * math.cos(math.radians(lat))
        return ((la - lat) * km_lat) ** 2 + ((lo - lon) * kx) ** 2

    # merge same-name nodes; railway stations join only when 코레일 광역철도 serves a station of that name
    nodes = json.load(open(path, encoding="utf-8"))
    rail, kw = os.path.join(RAW, "rail_stations.json"), os.path.join(RAW, "korail_wide.json")
    if os.path.exists(rail) and os.path.exists(kw):
        served = {korail_norm(r["name"]) for r in json.load(open(kw, encoding="utf-8"))}
        extra = [dict(s, korail=1) for s in json.load(open(rail, encoding="utf-8")) if korail_norm(s["name"]) in served]
        print(f"stations: {len(extra)} railway stations named like a 광역철도 station", flush=True)
        nodes += extra
    st = []
    for s in nodes:
        key = re.sub(r"역$", "", s["name"].strip())
        for m in st:
            if m["key"] == key and dist2(m["lat"], m["lon"], s["lat"], s["lon"]) <= 0.25:
                m["pts"].append((s["lat"], s["lon"]))
                break
        else:
            st.append({"key": key, "name": s["name"].strip(), "lat": s["lat"], "lon": s["lon"], "pts": [(s["lat"], s["lon"])], "korail": s.get("korail")})
    for m in st:
        m["lat"] = round(sum(p[0] for p in m["pts"]) / len(m["pts"]), 5)
        m["lon"] = round(sum(p[1] for p in m["pts"]) / len(m["pts"]), 5)

    # lines: route segments on a 0.01° grid
    lines, lidx, seg = [], {}, defaultdict(list)
    sub = os.path.join(RAW, "subway.json")
    for rel in json.load(open(sub, encoding="utf-8")) if os.path.exists(sub) else []:
        label = (rel["name"] or "").split(":")[0].strip() or f"{rel['network']} {rel['ref']}".strip()
        if not label:
            continue
        colour = rel["colour"] if re.fullmatch(r"#?[0-9A-Fa-f]{6}", rel["colour"] or "") else ""
        if label not in lidx:
            lidx[label] = len(lines)
            lines.append([label, ("#" + colour.lstrip("#")) if colour else ""])
        elif colour and not lines[lidx[label]][1]:
            lines[lidx[label]][1] = "#" + colour.lstrip("#")
        li = lidx[label]
        for _, coords in rel["ways"]:
            for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
                for cell in {(int(y1 * 100), int(x1 * 100)), (int(y2 * 100), int(x2 * 100))}:
                    seg[cell].append((li, x1, y1, x2, y2))

    def lines_near(lat, lon):
        kx = 111.32 * math.cos(math.radians(lat))
        found = set()
        ci, cj = int(lat * 100), int(lon * 100)
        for i in range(ci - 1, ci + 2):
            for j in range(cj - 1, cj + 2):
                for li, x1, y1, x2, y2 in seg.get((i, j), ()):
                    if li in found:
                        continue
                    ax, ay, bx, by = (x1 - lon) * kx, (y1 - lat) * km_lat, (x2 - lon) * kx, (y2 - lat) * km_lat
                    dx, dy = bx - ax, by - ay
                    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy))) if dx or dy else 0.0
                    if (ax + t * dx) ** 2 + (ay + t * dy) ** 2 <= 0.0225:
                        found.add(li)
        return sorted(found)

    grid = defaultdict(list)
    for r in rows:
        if r["ll"] and not r.get("approx"):
            grid[(int(r["ll"][0] * 100), int(r["ll"][1] * 100))].append(r)
    out = []
    for m in st:
        lat, lon = m["lat"], m["lon"]
        ci, cj = int(lat * 100), int(lon * 100)
        cnt = defaultdict(lambda: [0] * len(RADII))
        near1, nearest = Counter(), (101, None)
        for i in range(ci - 10, ci + 11):
            for j in range(cj - 12, cj + 13):
                for r in grid.get((i, j), ()):
                    d2 = dist2(lat, lon, *r["ll"])
                    if d2 <= 1:
                        near1[(r["sido"], r["sgg"])] += 1
                    if d2 < nearest[0]:
                        nearest = (d2, (r["sido"], r["sgg"]))
                    if r["status"] == 0 and d2 <= 25:
                        c = cnt[tidx[r["type"]]]
                        for k, rad in enumerate(RADII):
                            if d2 <= rad * rad:
                                c[k] += 1
        reg = near1.most_common(1)[0][0] if near1 else nearest[1]
        if not reg or not re.search("[가-힣]", m["name"]):  # no lodging within 10 km: outside Korea (the query box reaches Kyushu)
            continue
        if m["korail"] and len(m["pts"]) == 1 and reg[0] not in KORAIL_SIDO:  # a same-named station elsewhere
            continue
        si = sidos.index(reg[0])
        gi = sgg_of[reg[0]].index(reg[1])
        ln = lines_near(lat, lon)
        if not ln and m["korail"]:  # Korail lines are route=train in OSM, so not in subway.json
            if "코레일 광역철도" not in lidx:
                lidx["코레일 광역철도"] = len(lines)
                lines.append(["코레일 광역철도 (노선 미확인)", "#0052A4"])
            ln = [lidx["코레일 광역철도"]]
        out.append([lat, lon, m["name"], si, gi, ln, [[t, *c] for t, c in sorted(cnt.items())]])
    print(f"stations: {len(out)} after merging, {sum(1 for o in out if o[5])} on a known line, {len(lines)} lines", flush=True)
    kym = add_korail(out, lines, sidos)
    with open(os.path.join(OUT, "stations.json"), "w", encoding="utf-8") as f:
        json.dump({"r": RADII, "lines": lines, "st": out, "kym": kym}, f, ensure_ascii=False, separators=(",", ":"))


KORAIL_SIDO = ("서울특별시", "경기도", "인천광역시", "강원특별자치도", "충청남도", "부산광역시", "울산광역시", "대구광역시", "경상북도")  # where 코레일 광역철도 runs (동해선, 대경선 included)


def korail_norm(n):
    return re.sub(r"역$", "", re.sub(r"\(.*?\)|\s", "", n))
KORAIL_LINE = re.compile(r"코레일|동해|대경|경의|중앙|수인|분당|경춘|경강|1호선|3호선|4호선|서해|경부|경원|경인|안산|과천|일산|장항")


def add_korail(out, lines, sidos):
    """Append [[boardings], [alightings]] for the latest 12 months to each station row (0 when unmatched).
    Names are matched within the regions 광역철도 serves; when two stations share a name there (e.g. 양평, on
    경의중앙선 and on 5호선), the one on a Korail-run line wins."""
    path = os.path.join(RAW, "korail_wide.json")
    for o in out:
        o.append(0)
    if not os.path.exists(path):
        return []
    norm = korail_norm
    data = json.load(open(path, encoding="utf-8"))
    kym = sorted({r["ym"] for r in data})[-12:]
    by = defaultdict(dict)
    for r in data:
        if r["ym"] in kym:
            by[norm(r["name"])][r["ym"]] = (r["ride"], r["goff"])
    cand = defaultdict(list)
    for i, o in enumerate(out):
        if o[3] >= 0 and sidos[o[3]] in KORAIL_SIDO:
            cand[norm(o[2])].append(i)
    hit = amb = 0
    missing = []
    for name, series in by.items():
        ids = cand.get(name, [])
        if len(ids) > 1:
            ids = [i for i in ids if any(KORAIL_LINE.search(lines[li][0]) for li in out[i][5])]
        if len(ids) != 1:
            amb += bool(cand.get(name))
            if not cand.get(name):
                missing.append(name)
            continue
        out[ids[0]][-1] = [[series.get(m, (0, 0))[0] for m in kym], [series.get(m, (0, 0))[1] for m in kym]]
        hit += 1
    print(f"korail_wide: {len(by)} stations, {hit} matched to a map station, {amb} ambiguous, months {kym[:1]}~{kym[-1:]}; "
          f"not on the map: {' '.join(sorted(missing))}", flush=True)
    return kym


def write_kac():
    """한국공항공사 공항별 여객 per year (one odcloud table per publication; the newest table wins for a year).
    Passengers = adults + infants, arriving + departing, scheduled + unscheduled."""
    path = os.path.join(RAW, "kac_years.json")
    if not os.path.exists(path):
        return
    per = {}
    for t in sorted(json.load(open(path, encoding="utf-8")), key=lambda t: (re.findall(r"\d{8}", t["title"]) or ["0"])[0]):
        by = defaultdict(lambda: [0, 0])
        for r in t["rows"]:
            n = sum(int(r.get(k) or 0) for k in ("여객성인도착", "여객성인출발", "여객유아도착", "여객유아출발"))
            by[(int(r["연도"]), r["공항"])][1 if r["노선"] == "국제선" else 0] += n
        for (y, a), v in by.items():
            per.setdefault(y, {})[a] = v
    years = sorted(per)[-6:]
    names = sorted({a for y in years for a in per[y]}, key=lambda a: -sum(per[years[-1]].get(a, [0, 0])))
    out = {"years": years, "airports": [{"name": a.split("_")[0], "dom": [per[y].get(a, [0, 0])[0] for y in years],
                                         "intl": [per[y].get(a, [0, 0])[1] for y in years]} for a in names]}
    print(f"kac: years {years}, {len(names)} airports", flush=True)
    with open(os.path.join(OUT, "kac.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))


def write_icn():
    path = os.path.join(RAW, "icn.jsonl")
    if not os.path.exists(path):
        return
    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    months = sorted({r["ym"] for r in rows})
    mi = {m: i for i, m in enumerate(months)}
    arr, dep, by = [0] * len(months), [0] * len(months), defaultdict(lambda: [0] * len(months))
    region = {}
    for r in rows:
        arr[mi[r["ym"]]] += r["arr"]
        dep[mi[r["ym"]]] += r["dep"]
        by[r["country"]][mi[r["ym"]]] += r["arr"]
        region[r["country"]] = r["region"]
    last12 = range(max(0, len(months) - 12), len(months))
    top = sorted(by, key=lambda k: -sum(by[k][i] for i in last12))[:12]
    with open(os.path.join(OUT, "icn.json"), "w", encoding="utf-8") as f:
        json.dump({"months": months, "arr": arr, "dep": dep, "top": [{"name": k, "region": region[k], "arr": by[k]} for k in top]},
                  f, ensure_ascii=False, separators=(",", ":"))


def write_arrivals():
    path = os.path.join(RAW, "arrivals.jsonl")
    if not os.path.exists(path):
        return
    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    months = sorted({r["ym"] for r in rows})
    mi = {m: i for i, m in enumerate(months)}
    total, by_nat = [0] * len(months), defaultdict(lambda: [0] * len(months))
    for r in rows:
        total[mi[r["ym"]]] += r["n"]
        by_nat["".join(r["name"].split())][mi[r["ym"]]] += r["n"]  # "중  국" -> "중국"
    last12 = range(max(0, len(months) - 12), len(months))
    top = sorted(by_nat, key=lambda k: -sum(by_nat[k][i] for i in last12))[:10]
    with open(os.path.join(OUT, "arrivals.json"), "w", encoding="utf-8") as f:
        json.dump({"months": months, "total": total, "top": [{"name": k, "n": by_nat[k]} for k in top]},
                  f, ensure_ascii=False, separators=(",", ":"))


def main():
    rows = load()
    merged = any((r["road"] or r["lot"]).startswith(MERGED_GWANGJU_JEONNAM) for r in rows)
    for r in rows:
        r["sido"], r["sgg"] = region(r["road"] or r["lot"], merged)
        if r["sido"] and not r["sgg"]:
            r["sido"], r["sgg"] = region(r["lot"] or r["road"], merged)
    for r in rows:
        r["emd"], r["ri"] = emd_ri(r["lot"], r["road"], r["sgg"] or "") if r["sgg"] else (None, None)
    raw_counts = Counter(r["src"] for r in rows)

    rows, dup_removed, dup_examples = dedupe(rows)

    # coordinates: drop campgrounds without them, fill others from 시군구+동 medians
    dropped_camp = sum(1 for r in rows if r["src"] in CAMP and not r["ll"])
    rows = [r for r in rows if not (r["src"] in CAMP and not r["ll"])]
    dong_pts = defaultdict(list)

    def dong_of(r):
        m = re.search(r"\s(\S+?(?:동|가|리|읍|면))\s", " " + r["lot"] + " ")
        return m.group(1) if m else None

    for r in rows:
        if r["ll"] and r["sgg"]:
            dong_pts[(r["sido"], r["sgg"], dong_of(r))].append(r["ll"])
    filled = nocoord = 0
    for r in rows:
        if not r["ll"]:
            pts = dong_pts.get((r["sido"], r["sgg"], dong_of(r))) if dong_of(r) else None
            if pts:
                r["ll"] = (round(statistics.median(p[0] for p in pts), 5), round(statistics.median(p[1] for p in pts), 5))
                r["approx"] = 1
                filled += 1
            else:
                nocoord += 1
    unknown_region = sum(1 for r in rows if not r["sgg"])
    rows = [r for r in rows if r["sgg"]]

    # indices
    types = sorted({(r["cat"], r["type"]) for r in rows}, key=lambda t: (CATEGORIES.index(t[0]), -sum(1 for r in rows if r["type"] == t[1])))
    tidx = {t[1]: i for i, t in enumerate(types)}
    sido_n = Counter(r["sido"] for r in rows)
    sidos = [s for s, _ in sido_n.most_common()]
    sgg_of = {s: sorted({r["sgg"] for r in rows if r["sido"] == s}) for s in sidos}

    os.makedirs(os.path.join(OUT, "pts"), exist_ok=True)
    for f in glob.glob(os.path.join(OUT, "pts", "*.json")):
        os.remove(f)

    cube = Counter()
    close = Counter()
    cubeq, closeq = Counter(), Counter()
    Q_FROM = datetime.now(KST).year - 5

    def quarter(d):
        return (int(d[5:7]) - 1) // 3 + 1 if d[5:7].isdigit() and 1 <= int(d[5:7]) <= 12 else 1
    minbak = Counter()
    sido_meta = []
    for si, s in enumerate(sidos):
        sggs = sgg_of[s]
        gi = {g: i for i, g in enumerate(sggs)}
        recs = [r for r in rows if r["sido"] == s]
        dongs = [sorted({r["emd"] for r in recs if r["sgg"] == g and r["emd"]}) for g in sggs]
        di = [{d: i for i, d in enumerate(ds)} for ds in dongs]
        ris = defaultdict(set)
        for r in recs:
            if r["emd"] and r["ri"]:
                ris[(gi[r["sgg"]], di[gi[r["sgg"]]][r["emd"]])].add(r["ri"])
        ris = {k: sorted(v) for k, v in ris.items()}
        rix = {k: {x: i for i, x in enumerate(v)} for k, v in ris.items()}
        out, cen = [], defaultdict(list)
        for r in recs:
            g = gi[r["sgg"]]
            d = di[g].get(r["emd"], -1) if r["emd"] else -1
            q = rix.get((g, d), {}).get(r["ri"], -1) if r["ri"] else -1
            y = int(r["date"][:4]) if r["date"][:4].isdigit() else 0
            cy = int(r["closed"][:4]) if r["status"] == 2 and r["closed"][:4].isdigit() else 0
            cube[(si, g, tidx[r["type"]], r["status"], y)] += 1
            if y >= Q_FROM:
                cubeq[(si, g, tidx[r["type"]], r["status"], y * 10 + quarter(r["date"]))] += 1
            if cy >= Q_FROM:
                closeq[(si, g, tidx[r["type"]], cy * 10 + quarter(r["closed"]))] += 1
            if cy:
                close[(si, g, tidx[r["type"]], cy, y)] += 1
            if r["zone"] >= 0:
                minbak[(si, g, r["status"], r["zone"], r["bldg"])] += 1
            lat, lon = r["ll"] if r["ll"] else (None, None)
            out.append([lat, lon, tidx[r["type"]], g, d, q, r["status"], y, cy,
                        r["name"], re.sub(r"^\S+\s", "", r["road"] or r["lot"]), r["date"], r["closed"], r.get("approx", 0),
                        r["zone"], r["bldg"]])
            if r["ll"]:
                cen[r["sgg"]].append(r["ll"])
        with open(os.path.join(OUT, "pts", f"{si}.json"), "w", encoding="utf-8") as f:
            json.dump({"dongs": dongs, "ris": {f"{k[0]}:{k[1]}": v for k, v in ris.items()}, "rows": out},
                      f, ensure_ascii=False, separators=(",", ":"))
        sgg_c = []
        for g in sggs:
            c = cen.get(g)
            sgg_c.append([round(statistics.median(p[0] for p in c), 4), round(statistics.median(p[1] for p in c), 4)] if c else None)
        allc = [p for v in cen.values() for p in v]
        sido_meta.append({
            "name": s, "n": sido_n[s], "sgg": sggs, "sggc": sgg_c,
            "c": [round(statistics.median(p[0] for p in allc), 4), round(statistics.median(p[1] for p in allc), 4)] if allc else None,
        })
        if s == MERGED_GWANGJU_JEONNAM:
            sido_meta[-1]["groups"] = [{"name": "광주시", "gis": [sggs.index(g) for g in GWANGJU_GU if g in sggs]}]
    with open(os.path.join(OUT, "close.json"), "w", encoding="utf-8") as f:
        json.dump([[*k, v] for k, v in sorted(close.items())], f, separators=(",", ":"))
    for name, data in (("cubeq.json", cubeq), ("closeq.json", closeq)):
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
            json.dump([[*k, v] for k, v in sorted(data.items())], f, separators=(",", ":"))
    with open(os.path.join(OUT, "minbak.json"), "w", encoding="utf-8") as f:
        json.dump([[*k, v] for k, v in sorted(minbak.items())], f, separators=(",", ":"))

    # operating lodgings (campgrounds excluded) on a ~1 km grid, for attraction proximity counts
    grid = defaultdict(list)
    for r in rows:
        if r["status"] == 0 and r["ll"] and r["src"] not in CAMP:
            grid[(int(r["ll"][0] * 100), int(r["ll"][1] * 100))].append(r["ll"])

    def near(lat, lon):
        n1 = n3 = 0
        ci, cj = int(lat * 100), int(lon * 100)
        kx = 111.32 * math.cos(math.radians(lat))
        for i in range(ci - 3, ci + 4):
            for j in range(cj - 4, cj + 5):
                for la, lo in grid.get((i, j), ()):
                    d2 = ((la - lat) * 110.95) ** 2 + ((lo - lon) * kx) ** 2
                    if d2 <= 9:
                        n3 += 1
                        if d2 <= 1:
                            n1 += 1
        return n1, n3

    # tourist attractions, grouped by the same 시도/시군구 indices
    os.makedirs(os.path.join(OUT, "tour"), exist_ok=True)
    for f in glob.glob(os.path.join(OUT, "tour", "*.json")):
        os.remove(f)
    tour_by = defaultdict(list)
    tour_n = Counter()
    for ti, (ct, _) in enumerate(TOUR_TYPES):
        path = os.path.join(RAW, f"tour_{ct}.jsonl")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                try:
                    lon, lat = float(rec.get("mapx")), float(rec.get("mapy"))
                except (TypeError, ValueError):
                    continue
                if not (32.8 < lat < 38.9 and 124.2 < lon < 132.2):
                    continue
                sido, sgg = region(rec.get("addr1"), merged)
                if sido not in sidos:
                    continue
                si = sidos.index(sido)
                gi = sgg_of[sido].index(sgg) if sgg in sgg_of[sido] else -1
                img = clean(rec.get("firstimage2") or rec.get("firstimage")).replace("http://", "https://")
                n1, n3 = near(lat, lon)
                tour_by[si].append([round(lat, 5), round(lon, 5), ti, gi, clean(rec.get("title")),
                                    re.sub(r"^\S+\s", "", clean(rec.get("addr1"))), img, clean(rec.get("contentid")), n1, n3])
                tour_n[ti] += 1
    for si, sm in enumerate(sido_meta):
        cnt = [[0] * len(TOUR_TYPES) for _ in sm["sgg"]]
        for r in tour_by.get(si, []):
            if r[3] >= 0:
                cnt[r[3]][r[2]] += 1
        sm["tour"] = cnt
    visitors, visits = add_visitors(sidos, sgg_of, sido_meta)
    write_arrivals()
    write_icn()
    write_kac()
    write_parks()
    write_subway()
    write_park_areas()
    write_stations(rows, sidos, sgg_of, tidx)
    if visits:
        with open(os.path.join(OUT, "visits.json"), "w", encoding="utf-8") as f:
            json.dump(visits, f, separators=(",", ":"))
    for si in range(len(sidos)):
        with open(os.path.join(OUT, "tour", f"{si}.json"), "w", encoding="utf-8") as f:
            json.dump(tour_by.get(si, []), f, ensure_ascii=False, separators=(",", ":"))

    with open(os.path.join(OUT, "cube.json"), "w", encoding="utf-8") as f:
        json.dump([[*k, v] for k, v in sorted(cube.items())], f, separators=(",", ":"))
    meta = {
        "updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "status": STATUS,
        "categories": CATEGORIES,
        "types": [{"cat": c, "name": t} for c, t in types],
        "sido": sido_meta,
        "counts": {"raw": raw_counts, "kept": len(rows)},
        "dedupe": {"removed": dup_removed, "examples": dup_examples},
        "coords": {"dropped_campgrounds": dropped_camp, "filled_from_dong": filled, "no_coords": nocoord},
        "unknown_region": unknown_region,
        "tour": {"types": [n for _, n in TOUR_TYPES], "counts": [tour_n[i] for i in range(len(TOUR_TYPES))]},
        "zones": ZONES, "bldgs": BLDGS,
        "visitors": visitors,
    }
    with open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))
    print(json.dumps({k: meta[k] for k in ("counts", "dedupe", "coords", "unknown_region")}, ensure_ascii=False)[:1500])


if __name__ == "__main__":
    main()
