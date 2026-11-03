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
12. cubeq.json / closeq.json: the last six years by quarter (year*10 + quarter) for the quarterly charts.
13. subway.json: subway / light-rail and 광역·도시철도 lines (OpenStreetMap) as GeoJSON with each line's colour; KTX as k=1.
14. park_areas.json: national-park boundaries (OpenStreetMap) as simplified polygons with their map area;
    금정산 falls back to the boundary traced from the designation map (scripts/static/geumjeongsan.json).
15. stations.json: subway / light-rail, 코레일 광역철도 and 간선열차 stations (OpenStreetMap, gaps filled from 전국도시철도역사정보표준데이터) with their lines, 시도/시군구 and the number of
    operating lodgings per type within 0.5 / 1 / 3 / 5 km (records with an exact position only), plus the monthly
    boardings / alightings of 코레일 광역철도 and 간선열차 stations matched by name (latest 12 months).
16. icn.json: 인천공항 arriving / departing passengers per month and the top countries of the route.
17. kac.json: passengers per airport and year, domestic / international (한국공항공사 공항별 여객실적).
18. kto_index.json: 관광수요지수 세부 지표 (체류·소비 강도, 다양성, 관광 자원 수요: 숙박업 소비액·숙박 검색량 등) per 시도 / 시군구 and month (한국관광데이터랩, indices).
19. festivals.json: TourAPI festivals with every edition collected so far and the operating lodgings per type within
    0.5 / 1 / 3 / 5 km, as for stations.
20. park_lodging.json: per national park, lodgings inside it or within 1 / 3 / 5 km of its boundary (every status,
    exact positions) with permit and closing month, for the stock over time; "vis" = monthly visitors (국립공원공단) where published.
21. food.json: 모범음식점 (designated, open) and 백년가게 at the coordinates of their 일반음식점 인허가 record (raw/food_coords.json).
22. admin/<si>.json: 시도 and 시군구 outlines merged from 행정동 boundaries (vuski/admdongkor, 통계청 SGIS) for drawing the selected region.
23. meta.json "decl": 인구감소지역 / 관심지역 per 시군구 (scripts/static/decline_areas.json, 2026-10-07 지정).
24. pts/<si>.json "dpop": population per 법정 읍·면·동 (국립환경과학원 생활계 인구현황, latest year).
25. survival.json: Kaplan-Meier survival by 업종 대분류 for the nation, 시도 and 시군구 (permits since 2010).
26. download/lodging.csv.gz: every facility, for download (columns in site/codebook.html); the workflow keeps a
    monthly copy as a GitHub Release. Its last two columns: distance to the nearest bus stop (within 1.5 km) and
    that stop's 정차 노선수, for facilities with exact positions. download/panel_sgg.csv: 시군구 × year panel (stock by 대분류,
    객실, 신규·폐업, 신생률·소멸률, visitors).
27. meta.json "brief": national new permits / closings this year vs the same dates last year, and the share of operating
    facilities licensed 20+ years ago, per 업종.
28. meta.json sido[]["r12"] / ["old"]: per 시군구 new permits and closings over the last 365 days (per 업종), and
    operating 여관·여인숙 with those licensed 20+ and 30+ years ago, for the map colouring and the 동향 table;
    ["stk"] / "stock_years" / "room_cov": per 시군구 and 업종 the stock and its 객실 수 at the end of each of the last
    four years, and per 업종 the share of operating facilities with a 객실 수 (supply vs demand chart).
29. bus.json: bus terminals and intercity bus 정류장 (OpenStreetMap amenity=bus_station) as [lat, lon, 1 = name has 터미널, name];
    terminals also get 시도/시군구 and the operating lodgings per type within 1 / 3 km, for the 대중교통 tab;
    meta.json "bus" = the official national count (한국교통안전공단 전국 버스터미널 현황, latest table).
30. meta.json sido[]["land"] / ["land_sido"] / "land_year": 지가변동률 per 시군구 and 시도 (한국부동산원 R-ONE, latest year).
31. trrsrt.json: 관광지·관광단지 (전국관광지정보표준데이터) with the operating lodgings and 객실 수 within 1 / 3 / 5 km.
32. meta.json sido[]["oldland"] / ["oldland_sido"] / "vworld_year": median 개별공시지가 and 상업지역 count of 여관·여인숙
    licensed 30+ years ago (VWorld, scripts/static/vworld_land.csv from scripts/vworld_land.py); also 3 download columns.
33. meta.json sido[]["urban"] / ["urban_sido"] / groups[]["urban"] / "urban_year": 법정 도시지역 area and population
    (국토교통부 도시계획현황, scripts/static/upis.csv).
34. stations.json "near" [4..6] / meta.json "transit": lodgings within 0.5 km of a bus stop, of a stop with a known route
    count and of a stop with 3+ routes (stops and 정차 노선수 from the korea-transit-gap dashboard), and the route-count dates;
    "near" [7]: within 1 km of a station or 0.5 km of a bus stop (UN SDG 11.2.1 distances).
35. meta.json "valid": 문화체육관광부 전국 관광숙박시설 현황 per 시도 next to the permit records' 관광숙박업 on the same date.
36. meta.json "typology" / sido[]["typ"] / ["typz"]: 시군구 유형 (k-means on structural indicators, add_typology).
"""
import calendar
import csv
import difflib
import gzip
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
# 객실 수 columns per source (summed): 숙박업 한실 + 양실, the others 객실수; 관광펜션업 and campgrounds have none.
# (면적 columns exist too but are unusable: 숙박업 소재지면적 stops below 1,000㎡ and 관광 시설면적 often holds land areas.)
ROOM_COLS = {"lodgings": ("KSRM_CNT", "WSRM_CNT"), "tourist_accommodations": ("GSRM_CNT",), "foreigner_city_homestays": ("GSRM_CNT",),
             "rural_homestays": ("GSRM_CNT",), "hanok_experience": ("GSRM_CNT",)}
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
# 인천 2026 개편: 옛 중구·동구·서구 → 제물포구·영종구·서해구·검단구. 방문객 등 옛 구 기준 자료를 이어 보도록 새 4개 구를 한 묶음으로도 제공
INCHEON_OLD, INCHEON_NEW, INCHEON_GROUP = ("중구", "동구", "서구"), ("제물포구", "영종구", "서해구", "검단구"), "옛 중구·동구·서구"

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
    m = re.fullmatch(r"(\S+시)\S+구", sgg)  # 일반구를 붙여 쓴 주소(전주시완산구)는 시로
    if m:
        sgg = m.group(1)
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


def rooms_of(rec, cols):
    """Sum of the 객실 columns, or None when none of them holds a positive number."""
    n = 0
    for c in cols:
        try:
            n += max(0, int(float(rec.get(c))))
        except (TypeError, ValueError):
            pass
    return n or None


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
                    "rooms": rooms_of(rec, ROOM_COLS[ep]) if ep in ROOM_COLS else None,
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
    mlist = months[-24:]  # monthly 외지인 for the seasonality index; months reported for fewer days than the month has are flagged
    mix = {m: i for i, m in enumerate(mlist)}
    mseries = defaultdict(lambda: [None] * len(mlist))
    # 인천 옛 중·동·서구 묶음: 새 구가 나온 달부터는 새 4개 구만, 그 전은 옛 3개 구를 더함(옛 이름이 몇 달 더 남아 있어 겹치지 않게)
    inc = "인천광역시" if "인천광역시" in sidos else None
    new_ym = {(r["ym"], r["kind"]) for r in sgg_rows if inc and code_sido.get(r["code"][:2]) == inc and r["name"] in INCHEON_NEW}
    def grp_key(r, level):
        if level != "sgg" or not inc or code_sido.get(r["code"][:2]) != inc:
            return None
        if r["name"] in INCHEON_NEW or (r["name"] in INCHEON_OLD and (r["ym"], r["kind"]) not in new_ym):
            return (inc, "@" + INCHEON_GROUP)
        return None

    for level, rows in (("sido", sido_rows), ("sgg", sgg_rows)):
        for r in rows:
            if r["kind"] not in ("2", "3"):
                continue
            for k in (key_of(r, level), grp_key(r, level)):
                if not k:
                    continue
                j = int(r["kind"]) - 2
                arr = series[k][j]
                q = qi[f"{r['ym'][:4]}Q{(int(r['ym'][4:]) - 1) // 3 + 1}"]
                arr[q] = (arr[q] or 0) + r["n"]
                if j == 0 and r["ym"] in mix:
                    mseries[k][mix[r["ym"]]] = (mseries[k][mix[r["ym"]]] or 0) + r["n"]
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
        for g in sm.get("groups", []):
            if g.get("own"):
                g["vis"] = year((s, "@" + g["name"]))
    # days covered per quarter (national), so the page can mark the quarter still in progress
    qdays = [0] * len(quarters)
    for ym in months:
        days = max(r["days"] for r in sido_rows if r["ym"] == ym)
        qdays[qi[f"{ym[:4]}Q{(int(ym[4:]) - 1) // 3 + 1}"]] += days
    mfull = [max(r["days"] for r in sido_rows if r["ym"] == m) >= calendar.monthrange(int(m[:4]), int(m[4:]))[1] for m in mlist]
    visits = {"q": quarters, "qdays": qdays, "last": last,
              "m": mlist, "mfull": mfull, "msido": [mseries.get((s, None)) for s in sidos],
              "msgg": [[mseries.get((s, g)) for g in sgg_of[s]] for s in sidos],
              "sido": [series.get((s, None)) for s in sidos],
              "sgg": [[series.get((s, g)) for g in sgg_of[s]] for s in sidos],
              "gsgg": [[series.get((s, "@" + g["name"])) for g in sm.get("groups", [])] for s, sm in zip(sidos, sido_meta)]}
    first_month = min(window)
    meta = {"from": first_month + "01", "to": last, "partial": partial, "unmatched": sorted(unmatched)}
    return meta, visits


KTX_COLOUR = "#1f2d3d"


def write_subway():
    """One LineString per OSM way; a way shared by several routes (both directions, through-running) is drawn once
    with the colour of the first route that has one. Subway / light rail first, then 광역·도시철도 tagged route=train
    with their line colour (rail_routes.json; ITX and other intercity trains left out), then KTX (k=1) on the ways
    no other line uses, so KTX shows where it has its own track or runs on conventional lines."""
    path = os.path.join(RAW, "subway.json")
    if not os.path.exists(path):
        return
    rels = json.load(open(path, encoding="utf-8"))
    extra = os.path.join(RAW, "rail_routes.json")
    rail = json.load(open(extra, encoding="utf-8")) if os.path.exists(extra) else []
    is_ktx = lambda r: "KTX" in r["name"] or r.get("network") in ("KTX", "고속철도") or r.get("service") in ("high_speed", "highspeed")
    ktx = [r for r in rail if is_ktx(r)]
    rels += [r for r in rail if not is_ktx(r) and not r["name"].startswith("ITX") and r["colour"]]
    ways = {}
    for rel in rels:
        colour = rel["colour"] if re.fullmatch(r"#?[0-9A-Fa-f]{6}", rel["colour"] or "") else ""
        colour = ("#" + colour.lstrip("#")) if colour else ""
        name = rel["name"] or rel["ref"]
        for wid, coords in rel["ways"]:
            if wid not in ways or (colour and not ways[wid][0]):
                ways[wid] = (colour, name, coords, 0)
    for rel in ktx:
        name = re.sub(r":.*", "", rel["name"]).strip() or "KTX"
        for wid, coords in rel["ways"]:
            if wid not in ways:
                ways[wid] = (KTX_COLOUR, name, coords, 1)
    print(f"subway: {sum(1 for w in ways.values() if not w[3])} line ways, {sum(1 for w in ways.values() if w[3])} KTX ways", flush=True)
    feats = [{"type": "Feature", "properties": {"c": c or "#7f8c8d", "n": n, **({"k": 1} if k else {})},
              "geometry": {"type": "LineString", "coordinates": g}} for c, n, g, k in ways.values() if len(g) > 1]
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
    """Douglas-Peucker in degrees (~30 m). A closed ring (first point = last) is split at its farthest point first:
    measured against a zero-length chord every point has distance 0 and the ring would collapse to two points."""
    if len(pts) < 5:
        return pts
    if pts[0] == pts[-1]:
        far = max(range(len(pts)), key=lambda i: (pts[i][0] - pts[0][0]) ** 2 + (pts[i][1] - pts[0][1]) ** 2)
        return _simplify(pts[:far + 1], tol)[:-1] + _simplify(pts[far:], tol)
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
    print(f"park_areas: {len(best)} parks: " + ", ".join(f"{k} {a:.0f}㎢ ({sum(len(p[0]) for p in polys)} pts)" for k, (a, polys, _) in sorted(best.items())), flush=True)
    feats = [{"type": "Feature", "properties": {"park": k, "km2": round(a, 1), "src": src},
              "geometry": {"type": "MultiPolygon", "coordinates": polys}} for k, (a, polys, src) in sorted(best.items())]
    # one name label per park, at the middle of its largest part (a sea park has dozens of island parts)
    for k, (_, polys, _) in sorted(best.items()):
        ring = max((p[0] for p in polys), key=_km2)
        feats.append({"type": "Feature", "properties": {"park": k},
                      "geometry": {"type": "Point", "coordinates": [round(sum(x for x, _ in ring) / len(ring), 5), round(sum(y for _, y in ring) / len(ring), 5)]}})
    with open(os.path.join(OUT, "park_areas.json"), "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f, ensure_ascii=False, separators=(",", ":"))
    return best


def _outline(polys):
    """Outline of the union of polygons (lists of rings) as lines: an edge two polygons share is inside the union and
    dropped, the remaining edges are joined end to end. Needs shared vertices to be identical (true for 행정동 data)."""
    key = lambda a, b: (a, b) if a < b else (b, a)
    cnt = Counter(key(tuple(a), tuple(b)) for rings in polys for ring in rings for a, b in zip(ring, ring[1:]) if a != b)
    free, adj = {e for e, n in cnt.items() if n == 1}, defaultdict(list)
    for a, b in free:
        adj[a].append(b)
        adj[b].append(a)
    lines = []
    while free:
        a, b = free.pop()
        line = [a, b]
        for end in (1, 0):  # extend forward from the last point, then backward from the first
            while True:
                tip = line[-1] if end else line[0]
                nxt = next((n for n in adj[tip] if key(tip, n) in free), None)
                if nxt is None:
                    break
                free.discard(key(tip, nxt))
                line.append(nxt) if end else line.insert(0, nxt)
        lines.append([list(p) for p in line])
    return lines


def write_admin(sidos, sido_meta, merged):
    """시도 / 시군구 outlines per 시도: admin/<si>.json = {"sido": [lines], "sgg": [[lines] or null per 시군구]}, merged
    from 행정동 boundaries (vuski/admdongkor, 통계청 SGIS). A 시 with 일반구 ("수원시장안구") counts as the 시. Closed
    lines under 0.05 km² (islets) are dropped and the rest simplified (~50 m)."""
    os.makedirs(os.path.join(OUT, "admin"), exist_ok=True)
    for f in glob.glob(os.path.join(OUT, "admin", "*.json")):
        os.remove(f)
    path = os.path.join(RAW, "admin_dong.json")
    if not os.path.exists(path):
        return
    raw = json.load(open(path, encoding="utf-8"))
    dongs = raw["dongs"] if isinstance(raw, dict) else raw  # older caches hold the bare list
    by_sido = defaultdict(lambda: defaultdict(list))
    for d in dongs:
        sido = SIDO_ALIASES.get(d["sido"], d["sido"])
        if merged and sido in ("광주광역시", "전라남도"):
            sido = MERGED_GWANGJU_JEONNAM
        m = re.fullmatch(r"(\S+?시)\s?\S+구", d["sgg"])
        by_sido[sido][m.group(1) if m else d["sgg"] or sido].append(d["rings"])

    def lines(polys):
        return [_simplify(l, 0.0005) for l in _outline(polys) if l[0] != l[-1] or _km2(l) >= 0.05]
    missing = []
    edge_of = defaultdict(set)  # 행정동 edge -> the (시도, 시군구) owning it, for the neighbours below
    pts_of = defaultdict(list)  # (시도, 시군구) -> every 5th boundary point, for islands' neighbours across the sea
    for si, s in enumerate(sidos):
        groups = by_sido.get(s, {})
        sgg = []
        for gi, g in enumerate(sido_meta[si]["sgg"]):
            polys = groups.get(g) or (groups.get(s) if g == s else None) or ([p for v in groups.values() for p in v] if g == s else None)
            sgg.append(lines(polys) if polys else None)
            if not polys:
                missing.append(f"{s} {g}")
            for ring in (r for rings in polys or [] for r in rings):
                pts_of[(si, gi)].extend(ring[::5])
                for a, b in zip(ring, ring[1:]):
                    if a != b:
                        edge_of[(tuple(a), tuple(b)) if a < b else (tuple(b), tuple(a))].add((si, gi))
        with open(os.path.join(OUT, "admin", f"{si}.json"), "w", encoding="utf-8") as f:
            json.dump({"sido": lines([p for v in groups.values() for p in v]) if groups else None, "sgg": sgg}, f, separators=(",", ":"))
    print(f"admin: 시도 {sum(1 for s in sidos if by_sido.get(s))} of {len(sidos)} outlined; 시군구 without an outline: {' '.join(missing) or '-'}", flush=True)
    add_neighbours(edge_of, pts_of, sido_meta)
    return raw.get("ver") if isinstance(raw, dict) else None


ADJ_MIN_KM = 0.2  # shared boundary needed to count as neighbours (not a corner touch)
ADJ_SEA_KM = 5  # a 시군구 with no land neighbour (거제·남해·영도 …) takes those this close across the sea (bridges)


def add_neighbours(edge_of, pts_of, sido_meta):
    """Neighbours from the 행정동 edges two areas share (shared vertices are identical in that data): sido_meta[si]["adj"]
    = per 시군구 [[si, gi], …] and ["adj_sido"] = [si, …], longest shared boundary first. A 시군구 without any takes the
    ones within ADJ_SEA_KM across the sea, nearest first (울릉군 stays without)."""
    km = lambda a, b: math.hypot((a[0] - b[0]) * 88.8, (a[1] - b[1]) * 111.0)  # ~km at Korean latitudes
    pair, spair = Counter(), Counter()
    for (a, b), own in edge_of.items():
        if len(own) == 2:
            p, q = sorted(own)
            pair[(p, q)] += km(a, b)
            if p[0] != q[0]:
                spair[(p[0], q[0])] += km(a, b)
    for sm in sido_meta:
        sm["adj"], sm["adj_sido"] = [[] for _ in sm["sgg"]], []
    for (p, q), d in pair.most_common():
        if d >= ADJ_MIN_KM:
            sido_meta[p[0]]["adj"][p[1]].append(list(q))
            sido_meta[q[0]]["adj"][q[1]].append(list(p))
    for (p, q), d in spair.most_common():
        if d >= ADJ_MIN_KM:
            sido_meta[p]["adj_sido"].append(q)
            sido_meta[q]["adj_sido"].append(p)
    box = {k: (min(x for x, _ in v), min(y for _, y in v), max(x for x, _ in v), max(y for _, y in v)) for k, v in pts_of.items()}
    sea = []
    for p in [(si, gi) for si, sm in enumerate(sido_meta) for gi, a in enumerate(sm["adj"]) if not a and pts_of.get((si, gi))]:
        bx, pad = box[p], ADJ_SEA_KM / 80
        near = []
        for q, qb in box.items():
            if q != p and qb[0] < bx[2] + pad and qb[2] > bx[0] - pad and qb[1] < bx[3] + pad and qb[3] > bx[1] - pad:
                d = min(km(a, b) for a in pts_of[p] for b in pts_of[q])
                if d <= ADJ_SEA_KM:
                    near.append((d, q))
        sido_meta[p[0]]["adj"][p[1]] = [list(q) for _, q in sorted(near)]
        sea.append(f"{sido_meta[p[0]]['sgg'][p[1]]}({len(near)})")
    n = [len(a) for sm in sido_meta for a in sm["adj"]]
    print(f"neighbours: 시군구 with none {sum(1 for x in n if not x)}, max {max(n, default=0)}, mean {sum(n) / max(len(n), 1):.1f}; "
          f"across the sea: {' '.join(sea) or '-'}; 시도 pairs {sum(len(sm['adj_sido']) for sm in sido_meta) // 2}", flush=True)


PARK_BANDS = (1, 3, 5)  # km from a national park's boundary


def write_park_lodging(rows, parks, sidos, sgg_of, tidx):
    """Lodgings with an exact position (every status) inside each national park or within PARK_BANDS km of its
    boundary, with permit and closing month, so the park tab can draw the operating stock over time.
    band 0 = inside, 1..3 = within 1 / 3 / 5 km outside. Holes of the polygons are ignored (they were dropped)."""
    km_lat = 110.95
    grid = defaultdict(list)  # lodgings on a 0.1° grid
    for r in rows:
        if r["ll"] and not r.get("approx"):
            grid[(int(r["ll"][0] * 10), int(r["ll"][1] * 10))].append(r)
    ym = lambda d: int(d[:4] + d[5:7]) if re.match(r"\d{4}-\d{2}", d or "") else 0
    gi_of = {s: {g: i for i, g in enumerate(sgg_of[s])} for s in sidos}
    out = []
    for park, (area, polys, _) in sorted(parks.items()):
        rings = [p[0] for p in polys]
        pts = [pt for ring in rings for pt in ring]
        lat0 = sum(y for _, y in pts) / len(pts)
        kx = 111.32 * math.cos(math.radians(lat0))
        segs, strips = defaultdict(list), defaultdict(list)  # 0.02° cells for distances, 0.01° latitude strips for inside
        for ring in rings:
            for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
                sg = (x1, y1, x2, y2)
                for i in range(int(min(y1, y2) * 50), int(max(y1, y2) * 50) + 1):
                    for j in range(int(min(x1, x2) * 50), int(max(x1, x2) * 50) + 1):
                        segs[(i, j)].append(sg)
                for k in range(int(min(y1, y2) * 100), int(max(y1, y2) * 100) + 1):
                    strips[k].append(sg)
        x0, x1_, y0, y1_ = min(x for x, _ in pts), max(x for x, _ in pts), min(y for _, y in pts), max(y for _, y in pts)
        pad_y, pad_x = PARK_BANDS[-1] / km_lat, PARK_BANDS[-1] / kx
        res, regs, near = [], Counter(), Counter()
        for i in range(int((y0 - pad_y) * 10), int((y1_ + pad_y) * 10) + 1):
            for j in range(int((x0 - pad_x) * 10), int((x1_ + pad_x) * 10) + 1):
                for r in grid.get((i, j), ()):
                    lat, lon = r["ll"]
                    if not (y0 - pad_y <= lat <= y1_ + pad_y and x0 - pad_x <= lon <= x1_ + pad_x):
                        continue
                    inside = sum(1 for xa, ya, xb, yb in strips.get(int(lat * 100), ())
                                 if (ya > lat) != (yb > lat) and xa + (lat - ya) / (yb - ya) * (xb - xa) > lon) % 2
                    if inside:
                        band = 0
                    else:
                        d2 = 99.0
                        ci, cj = int(lat * 50), int(lon * 50)
                        for a in range(ci - 3, ci + 4):
                            for b in range(cj - 3, cj + 4):
                                for xa, ya, xb, yb in segs.get((a, b), ()):
                                    ax, ay, bx, by = (xa - lon) * kx, (ya - lat) * km_lat, (xb - lon) * kx, (yb - lat) * km_lat
                                    dx, dy = bx - ax, by - ay
                                    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy))) if dx or dy else 0.0
                                    d2 = min(d2, (ax + t * dx) ** 2 + (ay + t * dy) ** 2)
                        band = next((k + 1 for k, km in enumerate(PARK_BANDS) if d2 <= km * km), None)
                        if band is None:
                            continue
                    res.append([tidx[(r["cat"], r["type"])], band, ym(r["date"]), ym(r["closed"]) if r["status"] == 2 else 0, r["status"]])
                    (regs if band <= 1 else near)[(sidos.index(r["sido"]), gi_of[r["sido"]][r["sgg"]])] += 1
        out.append({"name": park, "km2": round(area, 1), "bbox": [round(x0, 4), round(y0, 4), round(x1_, 4), round(y1_, 4)],
                    "regs": [list(k) for k, _ in (regs or near).most_common()], "rows": res})  # 시군구 of the lodgings within 1 km (else 5 km)
        print(f"  park_lodging {park}: {len(res)} lodgings ({sum(1 for x in res if x[1] == 0)} inside), regions {len(regs)}", flush=True)
    # monthly visitors (국립공원공단, raw/park_visitors.json) for the parks it covers, matched by name without "국립공원"
    vp = os.path.join(RAW, "park_visitors.json")
    vis = json.load(open(vp, encoding="utf-8")) if os.path.exists(vp) else {"parks": {}}
    for p in out:
        v = vis["parks"].get(re.sub(r"국립공원$", "", p["name"]))
        if v:
            p["vis"] = [[int(m), n] for m, n in sorted(v.items())]
    print(f"  park visitors: {sorted(p['name'] for p in out if p.get('vis'))} ({vis.get('table', '-')})", flush=True)
    with open(os.path.join(OUT, "park_lodging.json"), "w", encoding="utf-8") as f:
        json.dump({"bands": PARK_BANDS, "parks": out, "vis_table": vis.get("table", "")}, f, ensure_ascii=False, separators=(",", ":"))


RADII = (0.5, 1, 3, 5)  # km, station catchment rings


def bus_stop_grid():
    """Bus stops of raw/transit_stops.json as {(int(lat * 100), int(lon * 100)): [(lat, lon, routes or -1), …]}, {} without the file."""
    grid = defaultdict(list)
    tpath = os.path.join(RAW, "transit_stops.json")
    for lon, lat, rte, _osm in (json.load(open(tpath, encoding="utf-8"))["stops"] if os.path.exists(tpath) else []):
        grid[(int(lat * 100), int(lon * 100))].append((lat, lon, rte))
    return grid


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

    # sources: OSM subway / light-rail stations; OSM railway stations named like a station in the 코레일 광역철도 or
    # 간선열차 tables; 전국도시철도역사정보표준데이터 (fills stations OSM lacks). Same name within 500 m = one station.
    nodes = [dict(s, src="metro") for s in json.load(open(path, encoding="utf-8"))]
    load = lambda name: json.load(open(os.path.join(RAW, name), encoding="utf-8")) if os.path.exists(os.path.join(RAW, name)) else []
    rail = load("rail_stations.json")
    wide = {korail_norm(r["name"]) for r in load("korail_wide.json")}
    mp = os.path.join(RAW, "korail_main.jsonl")
    main = {korail_norm(json.loads(l)["name"]) for l in open(mp, encoding="utf-8")} if os.path.exists(mp) else set()
    # by name with the parentheses kept (김천(구미) → 김천구미), and also without their text (총신대입구(이수) → 총신대입구)
    # unless another station has that exact name (김천)
    by_name = defaultdict(list)
    full = lambda r: korail_norm(r["name"].replace("(", "").replace(")", ""))
    for r in rail:
        by_name[full(r)].append(r)
    for r in rail:
        if korail_norm(r["name"]) != full(r) and korail_norm(r["name"]) not in by_name:
            by_name[korail_norm(r["name"])].append(r)
    nodes += [dict(r, src="korail") for n in wide for r in by_name.get(n, [])]
    # a 간선 station name that several distant railway stations share (양평 on 경의중앙선 and on 5호선) goes to the one
    # Korail operates; if that is still not one place, the name is skipped
    far = lambda rs: any(dist2(x["lat"], x["lon"], y["lat"], y["lon"]) > 25 for x in rs for y in rs)
    korail_op = lambda rs: [r for r in rs if re.search(r"한국철도|코레일|Korail|KORAIL", r.get("op", ""))]
    pick = {n: (korail_op(by_name[n]) if far(by_name[n]) else by_name[n]) for n in main if by_name.get(n)}
    amb = sorted(n for n, rs in pick.items() if not rs or far(rs))
    nodes += [dict(r, src="main") for n, rs in pick.items() if n not in amb for r in rs]
    print(f"stations: 간선 {len(main)} names, {sum(1 for n in main if by_name.get(n))} found among railway stations; "
          f"same name far apart (skipped): {' '.join(amb)}; not found: {' '.join(sorted(n for n in main if not by_name.get(n)))}", flush=True)
    std = load("metro_std.json")
    if std:
        # exact names first: the JSON also has 영문역사명 / 환승노선명, which contain the shorter names
        col = lambda *keys: next((k for k in keys if k in std[0]), None) or next((c for c in std[0] if any(k in c for k in keys)), None)
        cn, cl, cy, cx = col("역사명", "역명"), col("노선명"), col("역위도", "위도"), col("역경도", "경도")
        for r in std:
            try:
                nodes.append({"name": r[cn].strip(), "lat": round(float(r[cy]), 5), "lon": round(float(r[cx]), 5), "src": "std", "line": (r.get(cl) or "").strip()})
            except (TypeError, ValueError, KeyError):
                pass
    st = []
    for s in nodes:
        key = korail_norm(s["name"])
        for m in st:
            if m["key"] == key and dist2(m["lat"], m["lon"], s["lat"], s["lon"]) <= 0.25:
                m["pts"].append((s["lat"], s["lon"]))
                break
        else:
            m = {"key": key, "name": s["name"].strip(), "lat": s["lat"], "lon": s["lon"], "pts": [(s["lat"], s["lon"])], "src": set(), "std_lines": set()}
            st.append(m)
        m["src"].add(s["src"])
        if s.get("line"):
            m["std_lines"].add(s["line"])
    print(f"stations: {sum(1 for m in st if m['src'] == {'std'})} stations only in 표준데이터 (missing from OpenStreetMap): "
          + " ".join(sorted(f"{m['name']}({'/'.join(sorted(m['std_lines']))})" for m in st if m["src"] == {"std"})), flush=True)
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
    out, srcs = [], []
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
                        c = cnt[tidx[(r["cat"], r["type"])]]
                        for k, rad in enumerate(RADII):
                            if d2 <= rad * rad:
                                c[k] += 1
        reg = near1.most_common(1)[0][0] if near1 else nearest[1]
        if not reg or not re.search("[가-힣]", m["name"]):  # no lodging within 10 km: outside Korea (the query box reaches Kyushu)
            continue
        if m["src"] == {"korail"} and reg[0] not in KORAIL_SIDO:  # a same-named station elsewhere
            continue
        si = sidos.index(reg[0])
        gi = sgg_of[reg[0]].index(reg[1])

        def line(label, colour):
            if label not in lidx:
                lidx[label] = len(lines)
                lines.append([label, colour])
            return lidx[label]
        ln = lines_near(lat, lon)
        if not ln:  # Korail lines are route=train in OSM, so not in subway.json; use the 표준데이터 line names
            ln = [line(n, "#7f8c8d") for n in sorted(m["std_lines"])] or ([line("코레일 광역철도 (노선 미확인)", "#0052A4")] if "korail" in m["src"] else [])
        if "main" in m["src"]:
            ln = ln + [line("간선열차 정차역 (KTX·ITX·무궁화 등)", "#1f3a93")]
        out.append([lat, lon, m["name"], si, gi, ln, [[t, *c] for t, c in sorted(cnt.items())]])
        srcs.append(m["src"])
    print(f"stations: {len(out)} after merging, {sum(1 for o in out if o[5])} on a known line, {len(lines)} lines", flush=True)
    # operating lodgings (exact positions) within 0.5 / 1 km of any station, per 시군구, for the summary tab
    sgrid = defaultdict(list)
    for o in out:
        sgrid[(int(o[0] * 100), int(o[1] * 100))].append((o[0], o[1]))
    # [lodgings, within 0.5 km, within 1 km, Hansen accessibility sum]: Hansen (1959) A = Σ exp(−β·d) over stations within
    # 3 km, β = 2 per km (assumed walking decay: a station 0.5 km away counts 0.37, 1 km away 0.14)
    near = defaultdict(lambda: [0, 0, 0, 0.0, 0, 0, 0, 0])
    gi_of = {s: {g: i for i, g in enumerate(sgg_of[s])} for s in sidos}
    # bus stops from the transit-gap dashboard: lodgings within 0.5 km of any stop, of a stop with a known route count,
    # and of a stop with 3+ routes (indices 4–6); index 7 = within 1 km of a station or 0.5 km of any stop (UN SDG 11.2.1's
    # distances for high-capacity rail and other stops, here straight-line)
    bgrid = bus_stop_grid()
    for r in rows:
        if r["status"] != 0 or not r["ll"] or r.get("approx"):
            continue
        lat, lon = r["ll"]
        ds = [dist2(lat, lon, *p) for i in range(-3, 4) for j in range(-4, 5)  # a 0.01° cell is ~1.1 km tall, ~0.9 km wide
              for p in sgrid.get((int(lat * 100) + i, int(lon * 100) + j), ())]
        d2 = min(ds, default=99)
        c = near[f"{sidos.index(r['sido'])}:{gi_of[r['sido']][r['sgg']]}"]
        c[0] += 1
        c[1] += d2 <= 0.25
        c[2] += d2 <= 1
        c[3] += sum(math.exp(-2 * math.sqrt(x)) for x in ds if x <= 9)
        bus = [(dist2(lat, lon, p[0], p[1]), p[2]) for i in (-1, 0, 1) for j in (-1, 0, 1) for p in bgrid.get((int(lat * 100) + i, int(lon * 100) + j), ())]
        bus = [rte for d, rte in bus if d <= 0.25]
        c[4] += bool(bus)
        c[5] += any(rte >= 0 for rte in bus)
        c[6] += any(rte >= 3 for rte in bus)
        c[7] += d2 <= 1 or bool(bus)
    near = {k: [a, b, c, round(h, 2), nb, nk, ng, sdg] for k, (a, b, c, h, nb, nk, ng, sdg) in near.items()}
    print(f"bus stops near lodgings: {sum(len(v) for v in bgrid.values())} stops; "
          f"{sum(v[4] for v in near.values())} of {sum(v[0] for v in near.values())} lodgings within 0.5 km", flush=True)
    kym = add_korail(out, lines, sidos)
    mym = add_main(out, srcs)
    with open(os.path.join(OUT, "stations.json"), "w", encoding="utf-8") as f:
        json.dump({"r": RADII, "lines": lines, "st": out, "kym": kym, "mym": mym, "near": near}, f, ensure_ascii=False, separators=(",", ":"))


def write_festivals(rows, sidos, sgg_of, tidx, merged):
    """TourAPI festivals with every edition seen so far and the operating lodgings (exact positions) within RADII of
    the festival, per type, as for stations. Editions the service no longer lists and that have not ended are dropped
    (cancelled or moved)."""
    path = os.path.join(RAW, "festivals.jsonl")
    if not os.path.exists(path):
        return
    today = datetime.now(KST).strftime("%Y%m%d")
    by_id = defaultdict(list)
    for line in open(path, encoding="utf-8"):
        rec = json.loads(line)
        if rec["eventstartdate"] and (rec["cur"] or rec["eventenddate"] < today):
            by_id[rec["contentid"]].append(rec)
    grid = defaultdict(list)
    for r in rows:
        if r["status"] == 0 and r["ll"] and not r.get("approx"):
            grid[(int(r["ll"][0] * 100), int(r["ll"][1] * 100))].append(r)
    out, skipped = [], 0
    for recs in by_id.values():
        recs.sort(key=lambda r: r["eventstartdate"])
        rec = recs[-1]
        try:
            lon, lat = float(rec["mapx"]), float(rec["mapy"])
        except ValueError:
            lon = lat = 0
        sido, sgg = region(rec["addr1"], merged)
        if not (32.8 < lat < 38.9 and 124.2 < lon < 132.2) or sido not in sidos:
            skipped += 1
            continue
        kx = 111.32 * math.cos(math.radians(lat))
        cnt = defaultdict(lambda: [0] * len(RADII))
        ci, cj = int(lat * 100), int(lon * 100)
        for i in range(ci - 5, ci + 6):
            for j in range(cj - 6, cj + 7):
                for r in grid.get((i, j), ()):
                    d2 = ((r["ll"][0] - lat) * 110.95) ** 2 + ((r["ll"][1] - lon) * kx) ** 2
                    for k, rad in enumerate(RADII):
                        if d2 <= rad * rad:
                            cnt[tidx[(r["cat"], r["type"])]][k] += 1
        out.append([round(lat, 5), round(lon, 5), clean(rec["title"]), sidos.index(sido), sgg_of[sido].index(sgg) if sgg in sgg_of[sido] else -1,
                    [[int(r["eventstartdate"]), int(r["eventenddate"] or r["eventstartdate"])] for r in recs],
                    re.sub(r"^\S+\s", "", clean(rec["addr1"])), clean(rec["firstimage2"] or rec["firstimage"]).replace("http://", "https://"),
                    clean(rec["tel"]), [[t, *c] for t, c in sorted(cnt.items())]])
    print(f"festivals: {len(out)} festivals, {sum(len(f[5]) for f in out)} editions; skipped (no position or region) {skipped}", flush=True)
    with open(os.path.join(OUT, "festivals.json"), "w", encoding="utf-8") as f:
        json.dump({"r": RADII, "f": out}, f, ensure_ascii=False, separators=(",", ":"))


TRRSRT_RADII = (1, 3, 5)  # km, rings around 관광지·관광단지


def write_trrsrt(rows, sidos, sgg_of, tidx, merged):
    """trrsrt.json: 관광지·관광단지 (전국관광지정보표준데이터) with the operating lodgings (exact positions) per type and their
    객실 수 (room_rule) within TRRSRT_RADII: {"r": radii, "t": [[lat, lon, name, 1 = 관광단지, si, gi, 수용인원 or None,
    지정일, 숙박시설 정보, [[업종, n per radius], …], [객실 per radius]], …]}. 시도/시군구 from the address (-1 if not found)."""
    path = os.path.join(RAW, "trrsrt.json")
    if not os.path.exists(path):
        return
    med, cap, _ = room_rule(rows, tidx)
    grid = defaultdict(list)
    for r in rows:
        if r["status"] == 0 and r["ll"] and not r.get("approx"):
            grid[(int(r["ll"][0] * 100), int(r["ll"][1] * 100))].append(r)
    out, skipped, noreg = [], 0, []
    for rec in json.load(open(path, encoding="utf-8")):
        try:
            lat, lon = float(rec["latitude"]), float(rec["longitude"])
        except (TypeError, ValueError):
            lat = lon = 0
        if not (32.8 < lat < 38.9 and 124.2 < lon < 132.2):
            skipped += 1
            continue
        sido, sgg = region(clean(rec.get("rdnmadr") or rec.get("lnmadr")), merged)
        si = sidos.index(sido) if sido in sidos else -1
        gi = sgg_of[sido].index(sgg) if si >= 0 and sgg in sgg_of[sido] else -1
        if gi < 0:
            noreg.append(clean(rec.get("trrsrtNm")))
        kx = 111.32 * math.cos(math.radians(lat))
        cnt, rooms = defaultdict(lambda: [0] * len(TRRSRT_RADII)), [0] * len(TRRSRT_RADII)
        ci, cj, span = int(lat * 100), int(lon * 100), int(TRRSRT_RADII[-1] / 1.1) + 1
        for i in range(ci - span, ci + span + 1):
            for j in range(cj - span - 2, cj + span + 3):
                for r in grid.get((i, j), ()):
                    d2 = ((r["ll"][0] - lat) * 110.95) ** 2 + ((r["ll"][1] - lon) * kx) ** 2
                    t = tidx[(r["cat"], r["type"])]
                    for k, rad in enumerate(TRRSRT_RADII):
                        if d2 <= rad * rad:
                            cnt[t][k] += 1
                            rooms[k] += min(r["rooms"], cap.get(t, r["rooms"])) if r["rooms"] else med.get(t, 0)
        try:
            acpt = int(float(rec.get("aceptncCo"))) or None
        except (TypeError, ValueError):
            acpt = None
        out.append([round(lat, 5), round(lon, 5), clean(rec.get("trrsrtNm")), int(rec.get("trrsrtSe") == "관광단지"), si, gi, acpt,
                    clean(rec.get("appnDate")), clean(rec.get("stayngInfo")), [[t, *c] for t, c in sorted(cnt.items())], [round(x) for x in rooms]])
    print(f"trrsrt: {len(out)} 관광지·관광단지 ({sum(o[3] for o in out)} 관광단지); no position {skipped}; "
          f"시군구 not found ({len(noreg)}): {' '.join(noreg[:30])}", flush=True)
    with open(os.path.join(OUT, "trrsrt.json"), "w", encoding="utf-8") as f:
        json.dump({"r": TRRSRT_RADII, "t": out}, f, ensure_ascii=False, separators=(",", ":"))


def write_food(sidos, sido_meta, merged):
    """모범음식점 (still designated and open) and 백년가게 placed at the coordinates of their 일반음식점 인허가 record
    (fetch.py food_coords, found by name or by address; same EPSG:5174 coordinates as the lodging records). Those not
    matched are left out, among them 백년가게 that are not restaurants (no 일반음식점 record).
    Also meta.sido[]["food"] = per 시군구 [모범음식점, 백년가게] counted from the address (placed or not), for the 미식 tab."""
    path = os.path.join(RAW, "food_coords.json")
    pos = {k: coords({"CRD_INFO_X": v[0], "CRD_INFO_Y": v[1]}) for k, v in json.load(open(path, encoding="utf-8")).items() if v} if os.path.exists(path) else {}
    out, missing = [], Counter()
    for sm in sido_meta:
        sm["food"] = [[0, 0] for _ in sm["sgg"]]
    def count(addr, k):
        sd, g = region(addr, merged)
        if sd in sidos:
            sm = sido_meta[sidos.index(sd)]
            if g in sm["sgg"]:
                sm["food"][sm["sgg"].index(g)][k] += 1
    ex = os.path.join(RAW, "excellent_restaurant_info.jsonl")
    for line in open(ex, encoding="utf-8") if os.path.exists(ex) else []:
        r = json.loads(line)
        if r.get("DSGN_RTRCN_YMD") or r.get("SALS_STTS_NM") != "영업":
            continue
        count(clean(r.get("ROAD_NM_ADDR") or r.get("LCTN_ADDR")), 0)
        ll = pos.get(f"ex:{r['MNG_NO']}") or pos.get(f"ex2:{r['MNG_NO']}")  # ex2: found again by address
        if not ll:
            missing[0] += 1
            continue
        out.append([*ll, 0, clean(r.get("BSNSSP_NM")), clean(r.get("ROAD_NM_ADDR") or r.get("LCTN_ADDR")),
                    " · ".join(x for x in (clean(r.get("FD_OF_TYPE")), clean(r.get("PRINC_FD_KND"))) if x), clean(r.get("TELNO"))])
    cen = os.path.join(RAW, "century_shops.json")
    for r in json.load(open(cen, encoding="utf-8")) if os.path.exists(cen) else []:
        count(clean(r.get("업체주소")), 1)
        ll = pos.get(f"cen:{r.get('업체명')}|{r.get('업체주소')}") or pos.get(f"cen2:{r.get('업체명')}|{r.get('업체주소')}")
        if not ll:
            missing[1] += 1
            continue
        out.append([*ll, 1, clean(r.get("업체명")), clean(r.get("업체주소")), "", clean(r.get("연락처"))])
    print(f"food: 모범음식점 {sum(1 for x in out if x[2] == 0)}, 백년가게 {sum(1 for x in out if x[2] == 1)} placed; "
          f"not placed (yet): 모범음식점 {missing[0]}, 백년가게 {missing[1]}", flush=True)
    with open(os.path.join(OUT, "food.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))


TERM_RADII = (1, 3)  # km, rings around bus terminals


def write_bus(rows, sidos, sgg_of, tidx):
    """bus.json from raw/bus_stations.json: {"r": TERM_RADII, "b": [[lat, lon, 1 = name has 터미널, name, …]]}. Terminals
    also carry 시도/시군구 index (the most common among the counted lodgings within 3 km, else -1) and the operating
    lodgings (exact positions) within TERM_RADII per type. Same name within 300 m = one point; a trailing romanized
    name ("… Bus Terminal") is dropped. Returns {"table", "n"} from raw/bus_official.json for meta (None if absent)."""
    path = os.path.join(RAW, "bus_stations.json")
    grid = defaultdict(list)
    for r in rows:
        if r["status"] == 0 and r["ll"] and not r.get("approx"):
            grid[(int(r["ll"][0] * 100), int(r["ll"][1] * 100))].append(r)
    out = []
    for st in json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []:
        name, lat, lon = re.sub(r"\s+[^가-힣]*$", "", st["name"]).strip() or st["name"], st["lat"], st["lon"]
        kx = 111.32 * math.cos(math.radians(lat))
        if any(o[3] == name and ((o[0] - lat) * 110.95) ** 2 + ((o[1] - lon) * kx) ** 2 <= 0.09 for o in out):
            continue
        o = [lat, lon, int("터미널" in name), name]
        if o[2]:
            cnt, reg = defaultdict(lambda: [0] * len(TERM_RADII)), Counter()
            ci, cj = int(lat * 100), int(lon * 100)
            for i in range(ci - 3, ci + 4):
                for j in range(cj - 4, cj + 5):
                    for r in grid.get((i, j), ()):
                        d2 = ((r["ll"][0] - lat) * 110.95) ** 2 + ((r["ll"][1] - lon) * kx) ** 2
                        if d2 <= TERM_RADII[-1] ** 2:
                            reg[(r["sido"], r["sgg"])] += 1
                        for k, rad in enumerate(TERM_RADII):
                            if d2 <= rad * rad:
                                cnt[tidx[(r["cat"], r["type"])]][k] += 1
            sd, g = reg.most_common(1)[0][0] if reg else (None, None)
            o += [sidos.index(sd) if sd in sidos else -1, sgg_of[sd].index(g) if sd in sidos and g in sgg_of[sd] else -1,
                  [[t, *c] for t, c in sorted(cnt.items())]]
        out.append(o)
    print(f"bus: {sum(o[2] for o in out)} 터미널, {sum(1 - o[2] for o in out)} other bus stations", flush=True)
    with open(os.path.join(OUT, "bus.json"), "w", encoding="utf-8") as f:
        json.dump({"r": TERM_RADII, "b": out}, f, ensure_ascii=False, separators=(",", ":"))
    path = os.path.join(RAW, "bus_official.json")
    if not os.path.exists(path):
        return None
    d = json.load(open(path, encoding="utf-8"))
    return {"table": d["table"], "n": sum(int(r["계"]) for r in d["rows"] if r.get("구분") not in ("계", "합계", "전국"))}


def add_main(out, srcs):
    """Append [[boardings], [alightings]] of 간선열차 for the latest 12 months to stations taken from the 간선 table."""
    path = os.path.join(RAW, "korail_main.jsonl")
    for o in out:
        o.append(0)
    if not os.path.exists(path):
        return []
    data = [json.loads(l) for l in open(path, encoding="utf-8")]
    mym = sorted({r["ym"] for r in data})[-12:]
    by = defaultdict(dict)
    for r in data:
        if r["ym"] in mym:
            by[korail_norm(r["name"])][r["ym"]] = (r["ride"], r["goff"])
    hit = 0
    for o, src in zip(out, srcs):  # 김천(구미): try 김천구미 before 김천
        series = (by.get(korail_norm(o[2].replace("(", "").replace(")", ""))) or by.get(korail_norm(o[2]))) if "main" in src else None
        if series:
            o[-1] = [[series.get(m, (0, 0))[0] for m in mym], [series.get(m, (0, 0))[1] for m in mym]]
            hit += 1
    print(f"korail_main: {len(by)} stations, {hit} on the map, months {mym[:1]}~{mym[-1:]}", flush=True)
    return mym


KORAIL_SIDO = ("서울특별시", "경기도", "인천광역시", "강원특별자치도", "충청남도", "부산광역시", "울산광역시", "대구광역시", "경상북도")  # where 코레일 광역철도 runs (동해선, 대경선 included)


KORAIL_ALIAS = {"디엠시": "디지털미디어시티", "인천공항T1": "인천공항1터미널", "인천공항T2": "인천공항2터미널"}  # names the Korail tables abbreviate


def korail_norm(n):
    n = re.sub(r"역$", "", re.sub(r"\(.*?\)|\s", "", n))
    return KORAIL_ALIAS.get(n, n)
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


KTO_IX = [("21", "관광 체류 강도"), ("2101", "타권역 방문자 비중"), ("2102", "숙박 비중"), ("2103", "1박 방문자"), ("2104", "2박 방문자"),
          ("2105", "3박 방문자"), ("22", "관광 소비 강도"), ("31", "관광객 다양성"), ("32", "관광 소비 다양성"), ("33", "국제적 다양성"),
          ("11", "관광서비스 수요"), ("1107", "숙박업 소비액"), ("1110", "숙박 검색량"), ("12", "문화자연자원 수요"),
          ("1103", "미식여행 SNS 언급량"), ("1106", "식음료 소비액")]


def write_kto_index(sidos, sgg_of):
    """관광수요지수 세부 지표 (한국관광데이터랩) per 시도 / 시군구 and month: {"months", "ix", "v": {"si" or "si:gi": [[value per month] per indicator]},
    "approx": [keys]}. Old 광주광역시/전라남도 rows go to 전남광주통합특별시 when it exists (its own 시도 row wins). Cities the
    service reports only by 일반구 ("수원시 장안구") get the plain mean of their 구 (an index, so no weights exist); those keys
    are listed in "approx"."""
    paths = [p for p in (os.path.join(RAW, f) for f in ("kto_index.jsonl", "kto_res.jsonl")) if os.path.exists(p)]
    if not paths:
        return
    rows = [r for p in paths for r in (json.loads(l) for l in open(p, encoding="utf-8")) if not r.get("empty")]
    months = sorted({r["ym"] for r in rows})
    mi, xi = {m: i for i, m in enumerate(months)}, {c: i for i, (c, _) in enumerate(KTO_IX)}
    merged = MERGED_GWANGJU_JEONNAM in sidos
    by_name = defaultdict(list)
    for sd in sidos:
        for g in sgg_of[sd]:
            by_name[g].append(sd)
    out, unmatched, parts = {}, set(), defaultdict(list)
    for r in sorted(rows, key=lambda r: r["sido"] == MERGED_GWANGJU_JEONNAM):  # the merged 시도's own rows last, so they win
        old = r["sido"] in ("광주광역시", "전라남도")
        sido = MERGED_GWANGJU_JEONNAM if old and merged else SIDO_ALIASES.get(r["sido"], r["sido"])
        if sido not in sidos or r["ix"] not in xi:
            unmatched.add(r["sido"])
            continue
        si = sidos.index(sido)
        if not r["sgg"]:
            if old and merged:  # 광주 or 전남 alone is not the merged 시도
                continue
            key = str(si)
        else:
            g = r["sgg"] if r["sgg"] in sgg_of[sido] else (r["sgg"] if len(by_name.get(r["sgg"], [])) == 1 else None)
            city = re.fullmatch(r"(\S+시) \S+구", r["sgg"])
            if g is None and city and city.group(1) in sgg_of[sido]:
                parts[(f"{si}:{sgg_of[sido].index(city.group(1))}", xi[r["ix"]], mi[r["ym"]])].append(r["v"])
                continue
            if g is None:
                unmatched.add(f"{r['sido']} {r['sgg']}")
                continue
            sd = by_name[g][0] if g not in sgg_of[sido] else sido
            key = f"{sidos.index(sd)}:{sgg_of[sd].index(g)}"
        out.setdefault(key, [[None] * len(months) for _ in KTO_IX])[xi[r["ix"]]][mi[r["ym"]]] = r["v"]
    approx = set()
    for (key, j, m), vs in parts.items():
        cell = out.setdefault(key, [[None] * len(months) for _ in KTO_IX])[j]
        if cell[m] is None:  # the city's own row, when there is one, wins
            cell[m] = round(sum(vs) / len(vs), 2)
            approx.add(key)
    print(f"kto_index: {len(months)} months {months[:1]}~{months[-1:]}, {len(out)} areas ({len(approx)} from the mean of their 일반구); "
          f"unmatched: {' '.join(sorted(unmatched))}", flush=True)
    with open(os.path.join(OUT, "kto_index.json"), "w", encoding="utf-8") as f:
        json.dump({"months": months, "ix": KTO_IX, "v": out, "approx": sorted(approx)}, f, ensure_ascii=False, separators=(",", ":"))


def add_population(sidos, sgg_of, sido_meta):
    """sido_meta[i]["pop"] / ["popg"]: 주민등록인구 of the latest month (행정안전부 행정동별 주민등록 인구).
    일반구 rows such as "수원시 장안구" are summed into their 시; a 시군구 that moved between 시도 is matched by its unique name."""
    path = os.path.join(RAW, "pop_month.json")
    if not os.path.exists(path):
        return None
    d = json.load(open(path, encoding="utf-8"))
    norm = lambda n: SIDO_ALIASES.get(n.strip(), n.strip())
    by_name = defaultdict(list)
    for sd in sidos:
        for g in sgg_of[sd]:
            by_name[g].append(sd)
    exact, parts, unmatched = {}, defaultdict(int), set()
    for r in d["sgg"]:
        sd, name = norm(r["sido"]), r["sgg"].strip() or norm(r["sido"])  # 세종 reports no 시군구 name
        city = name.split(" ")[0]
        if sd in sidos and name in sgg_of[sd]:
            exact[(sd, name)] = r["pop"]
        elif sd in sidos and name.replace(" ", "") in sgg_of[sd]:  # 전주시완산구 in the permit addresses
            exact[(sd, name.replace(" ", ""))] = r["pop"]
        elif sd in sidos and city in sgg_of[sd]:
            parts[(sd, city)] += r["pop"]
        elif len(by_name.get(name, [])) == 1:
            exact[(by_name[name][0], name)] = r["pop"]
        else:
            unmatched.add(f"{r['sido']} {name}")
    pops = {**parts, **exact}  # a 시 reported itself wins over the sum of its 구
    sido_pop = {norm(r["sido"]): r["pop"] for r in d["sido"]}
    for sd, sm in zip(sidos, sido_meta):
        if sd in sido_pop:
            sm["pop"] = sido_pop[sd]
        sm["popg"] = [pops.get((sd, g)) for g in sgg_of[sd]]
    missing = [f"{sd} {g}" for sd in sidos for g in sgg_of[sd] if (sd, g) not in pops]
    print(f"population: {d['ym']}, {sum(1 for sd in sidos if sd in sido_pop)} of {len(sidos)} 시도, {len(pops)} 시군구; "
          f"no population: {' '.join(missing)}; unmatched rows: {' '.join(sorted(unmatched))}", flush=True)
    return d["ym"]


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


DOWNLOAD_COLS = ["관리번호", "업소명", "업종대분류", "업종", "시도", "시군구", "읍면동", "리", "영업상태", "인허가일", "폐업일",
                 "도로명주소", "지번주소", "위도", "경도", "위치근사", "용도지역", "건물용도", "인구감소지역", "객실수",
                 "공시지가", "공시지가기준연도", "용도지역(VWorld)", "버스정류장거리(m)", "버스정류장노선수"]
BUS_NEAR_KM = 1.5  # nearest-stop search for the download; ±2 grid cells (0.01°, ≥0.87 km wide up to 38.6°N) always cover it


def write_download(rows, sidos, sido_meta, land):
    """Every facility (after duplicate removal and region matching) as data/download/lodging.csv.gz for researchers;
    the columns are described in site/codebook.html. UTF-8 with BOM so spreadsheet programs read Korean."""
    os.makedirs(os.path.join(OUT, "download"), exist_ok=True)
    gi_of = {s: {g: i for i, g in enumerate(sm["sgg"])} for s, sm in zip(sidos, sido_meta)}
    decl = lambda r: ["", "인구감소지역", "인구감소관심지역"][sido_meta[sidos.index(r["sido"])].get("decl", [0] * 999)[gi_of[r["sido"]][r["sgg"]]]]
    bgrid = bus_stop_grid()

    def nearest_stop(r):
        """(distance in m, routes or "") of the bus stop nearest an exact position, ("", "") beyond BUS_NEAR_KM or without stops."""
        if not r["ll"] or r.get("approx"):
            return "", ""
        lat, lon = r["ll"]
        kx = 111.32 * math.cos(math.radians(lat))
        for span, cover in ((1, 0.85), (2, BUS_NEAR_KM)):  # ±1 cell is enough in towns; widen only when nothing is that close
            d2, rte = min(((((la - lat) * 110.95) ** 2 + ((lo - lon) * kx) ** 2, rt) for i in range(-span, span + 1) for j in range(-span, span + 1)
                           for la, lo, rt in bgrid.get((int(lat * 100) + i, int(lon * 100) + j), ())), default=(99, -1))
            if d2 <= cover ** 2:
                break
        return (round(math.sqrt(d2) * 1000), rte if rte >= 0 else "") if d2 <= BUS_NEAR_KM ** 2 else ("", "")
    path = os.path.join(OUT, "download", "lodging.csv.gz")
    with gzip.open(path, "wt", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(DOWNLOAD_COLS)
        for r in sorted(rows, key=lambda r: (r["sido"], r["sgg"], r["emd"] or "", r["name"])):
            lat, lon = r["ll"] if r["ll"] else ("", "")
            jiga, gosi, zone = land.get(r["id"], (None, "", ""))
            w.writerow([r["id"], r["name"], r["cat"], r["type"], r["sido"], r["sgg"], r["emd"] or "", r["ri"] or "", STATUS[r["status"]],
                        r["date"], r["closed"], r["road"], r["lot"], lat, lon, r.get("approx", 0) if r["ll"] else "",
                        ZONES[r["zone"]] if r["zone"] >= 0 else "", BLDGS[r["bldg"]] if r["bldg"] >= 0 else "", decl(r), r["rooms"] or "",
                        jiga or "", gosi if jiga else "", zone, *nearest_stop(r)])
    print(f"download: {len(rows)} facilities, {os.path.getsize(path) / 1e6:.1f} MB", flush=True)


TYPO_VARS = [  # [key, label, word when high, word when low]
    ("tfi", "주민 1천 명당 숙소(로그)", "숙박 밀집", "숙박 희소"),
    ("tpi", "주민 1천 명당 하루 외지인(로그)", "방문 집중", "방문 적음"),
    ("fshare", "외국인 방문자 비중", "외국인", None),
    ("gini", "계절 편중(지니)", "계절 편중", "연중 방문"),
    ("urban", "도시지역 거주 인구 비율", "도시", "농산어촌"),
    ("rural", "농어촌민박 비중", "농어촌민박", None),
    ("intl", "관광숙박·도시민박 비중", "관광숙박", None),
    ("leisure", "펜션·야영장·한옥 비중", "레저숙박", None),
    ("old30", "30년 이상 여관·여인숙 비율", "노후 여관", "노후 여관 적음"),
]
TYPO_K = 7  # 6 leaves one large catch-all group; 8 splits 서울 도심 into two near-identical types


def add_typology(sido_meta, cube_rows, types, visits):
    """시군구 유형: k-means (k = TYPO_K, k-means++ from a fixed seed, best of 50 starts) on the z-scores of TYPO_VARS for
    every 시군구, all 업종, operating facilities. Missing values count as the mean. Each type is named after its one or two
    most distinctive variables (|z| ≥ 0.6 at the type's median, so one outlier such as 제주 does not name a group of islands);
    a type without any is '혼합형', and types that would share a name get the trait that sets them apart. sido_meta[i]["typz"]
    = each 시군구's own z-scores, so the page can show what stands out in a region whatever its type. sido_meta[i]["typ"] = type per 시군구; returns the meta block
    {"k", "vars": labels, "types": [{"name", "traits", "n", "z", "mean"}]}."""
    import random
    cat = {t: c for t, (c, _) in enumerate(types)}
    n = defaultdict(lambda: defaultdict(int))
    for si, gi, t, st, _y, c in cube_rows:
        if st == 0:
            n[(si, gi)][cat[t]] += c
    full = [i for i in range(len(visits["m"])) if visits["mfull"][i]][-12:] if visits else []

    def gini(xs):
        m = sum(xs) / len(xs)
        return sum(abs(a - b) for a in xs for b in xs) / (2 * len(xs) ** 2 * m) if m else None
    keys, X = [], []
    for si, sm in enumerate(sido_meta):
        for gi, _g in enumerate(sm["sgg"]):
            c = n[(si, gi)]
            tot = sum(c.values())
            pop = (sm.get("popg") or [None] * 999)[gi]
            vis = (sm.get("visg") or [None] * 999)[gi]
            u = (sm.get("urban") or [None] * 999)[gi]
            old = (sm.get("old") or [[0, 0, 0]] * 999)[gi]
            ms = visits["msgg"][si][gi] if visits and visits.get("msgg") else None
            mon = [ms[i] for i in full] if ms and len(full) == 12 and all(ms[i] is not None for i in full) else None
            share = lambda cs: sum(c[x] for x in cs) / tot if tot else None
            X.append([
                math.log(tot / (pop / 1e3) + 0.01) if pop and tot else None,
                math.log1p(vis[0] / 365 / (pop / 1e3)) if pop and vis else None,
                vis[1] / (vis[0] + vis[1]) if vis and vis[0] + vis[1] else None,
                gini(mon) if mon else None,
                u[3] / u[2] if u and u[2] else None,
                share(["농어촌민박업"]), share(["관광숙박업", "외국인관광 도시민박업"]), share(["관광펜션업", "야영장업", "한옥체험업"]),
                old[2] / old[0] if old[0] >= 10 else None])
            keys.append((si, gi))
    V = len(TYPO_VARS)
    mean = [statistics.mean(x[j] for x in X if x[j] is not None) for j in range(V)]
    sd = [statistics.pstdev([x[j] for x in X if x[j] is not None]) or 1 for j in range(V)]
    Z = [[(x[j] - mean[j]) / sd[j] if x[j] is not None else 0.0 for j in range(V)] for x in X]
    d2 = lambda a, b: sum((p - q) ** 2 for p, q in zip(a, b))
    rnd, best = random.Random(42), None
    for _ in range(50):
        cs = [Z[rnd.randrange(len(Z))]]
        while len(cs) < TYPO_K:  # k-means++ seeding
            w = [min(d2(z, c) for c in cs) for z in Z]
            r, acc = rnd.random() * sum(w), 0
            for z, wi in zip(Z, w):
                acc += wi
                if acc >= r:
                    cs.append(z)
                    break
        for _it in range(100):
            lab = [min(range(TYPO_K), key=lambda k: d2(z, cs[k])) for z in Z]
            new = [[statistics.mean(z[j] for z, l in zip(Z, lab) if l == k) for j in range(V)] if k in lab else cs[k] for k in range(TYPO_K)]
            if new == cs:
                break
            cs = new
        inertia = sum(d2(z, cs[l]) for z, l in zip(Z, lab))
        if best is None or inertia < best[0]:
            best = (inertia, lab, cs)
    _, lab, cs = best
    # order types by size so the numbering is stable across days when the clusters are
    order = sorted(range(TYPO_K), key=lambda k: -lab.count(k))
    rank = {k: i for i, k in enumerate(order)}
    out, names = [], Counter()
    for k in order:
        z = [statistics.median(Z[i][j] for i in range(len(Z)) if lab[i] == k) for j in range(V)]
        traits = sorted(((abs(z[j]), j, TYPO_VARS[j][2] if z[j] > 0 else TYPO_VARS[j][3]) for j in range(V)), reverse=True)
        traits = [(j, w) for a, j, w in traits if a >= 0.6 and w]
        out.append({"traits": [w for _, w in traits], "n": lab.count(k), "z": [round(v, 2) for v in z],
                    "mean": [round(statistics.mean(X[i][j] for i in range(len(X)) if lab[i] == k and X[i][j] is not None), 4)
                             if any(lab[i] == k and X[i][j] is not None for i in range(len(X))) else None for j in range(V)]})
    for t in out:  # name: two most distinctive traits
        t["name"] = "·".join(t["traits"][:2]) + "형" if t["traits"] else "혼합형"
        names[t["name"]] += 1
    for nm in [nm for nm, c in names.items() if c > 1]:  # same name: add the trait where each differs most from the others
        group = [t for t in out if t["name"] == nm]
        for t in group:
            others = [o for o in group if o is not t]
            diff = sorted(((abs(t["z"][j] - statistics.mean(o["z"][j] for o in others)), j) for j in range(V)), reverse=True)
            for _, j in diff:
                w = TYPO_VARS[j][2] if t["z"][j] > 0 else TYPO_VARS[j][3]
                if w and w not in t["name"]:
                    t["name"] = nm[:-1] + "·" + w + "형"
                    break
    for si, sm in enumerate(sido_meta):
        sm["typ"] = [rank[lab[keys.index((si, gi))]] for gi in range(len(sm["sgg"]))]
        sm["typz"] = [[round(v, 2) for v in Z[keys.index((si, gi))]] for gi in range(len(sm["sgg"]))]
    print("typology: " + "; ".join(f"{t['name']} {t['n']}" for t in out), flush=True)
    return {"k": TYPO_K, "vars": [v[1] for v in TYPO_VARS], "words": [[v[2], v[3]] for v in TYPO_VARS], "types": out}


def add_validation(rows, sidos, merged):
    """meta "valid": 문화체육관광부 전국 관광숙박시설 현황 (raw/mcst_lodging.json, 시도별 관광숙박업 업체·객실) next to the
    permit records' 관광숙박업 operating or paused on the table's date (closed records without a date left out; 객실 =
    reported values, empty as 0): {"table", "date", "rows": [[시도, 공식 업체, 인허가, 공식 객실 or None, 인허가 객실], …, 합계]}.
    The column layout is not fixed in advance, so the table is used only when it reads as exactly one total row per 시도
    (a 계/합계 column or row is taken when there are several); otherwise its columns are printed and None is returned."""
    path = os.path.join(RAW, "mcst_lodging.json")
    if not os.path.exists(path):
        return None
    d = json.load(open(path, encoding="utf-8"))
    recs, title = d["rows"], d["table"]
    keys = list(recs[0].keys()) if recs else []
    print(f"mcst_lodging: {title}: columns {keys}; first rows {json.dumps(recs[:3], ensure_ascii=False)}", flush=True)

    def norm(v):
        v = str(v or "").strip().replace(" ", "")
        if merged and v in ("광주", "광주광역시", "전남", "전라남도"):
            return MERGED_GWANGJU_JEONNAM
        v = SIDO_ALIASES.get(v, v)
        return v if v in sidos else None

    def num(v):
        try:
            return float(str(v).replace(",", ""))
        except ValueError:
            return None
    total = lambda k: any(t in ("계", "합계", "총계", "소계", "전체") for t in re.split(r"[\s_()\[\]·-]+", k)) or "합계" in k or "총계" in k
    reg = max(keys, key=lambda k: sum(1 for r in recs if norm(r.get(k))), default=None)
    mine = [r for r in recs if reg and norm(r.get(reg))]
    if len({norm(r[reg]) for r in mine}) < 10:
        print("mcst_lodging: no 시도 column found; validation skipped", flush=True)
        return None
    # long layout: another text column (e.g. 업종) with a total row per 시도
    for k in keys:
        if k != reg and any(num(r.get(k)) is None and str(r.get(k) or "").strip() for r in mine):
            tot = [r for r in mine if total(str(r.get(k) or ""))]
            if tot:
                mine = tot
    numeric = [k for k in keys if k != reg and all(num(r.get(k)) is not None for r in mine)]

    def pick(cands):
        return cands[0] if len(cands) == 1 else (lambda t: t[0] if len(t) == 1 else None)([k for k in cands if total(k)])
    room_k = pick([k for k in numeric if "객실" in k])
    cnt_k = pick([k for k in numeric if "객실" not in k and any(w in k for w in ("업체", "업소", "개소", "사업체", "수"))])
    by = defaultdict(list)
    for r in mine:
        by[norm(r[reg])].append(r)
    bad = [s for s, xs in by.items() if len(xs) > (2 if s == MERGED_GWANGJU_JEONNAM else 1)]
    if not cnt_k or bad:
        print(f"mcst_lodging: ambiguous layout (count column {cnt_k}, rooms column {room_k}, repeated 시도 {bad}); validation skipped", flush=True)
        return None
    ref = f"{title[-8:-4]}-{title[-4:-2]}-{title[-2:]}" if title[-8:].isdigit() else datetime.now(KST).strftime("%Y-%m-%d")
    ours = defaultdict(lambda: [0, 0])
    for r in rows:
        if r["cat"] == "관광숙박업" and r["date"] and r["date"] <= ref and (r["status"] < 2 or (r["closed"] and r["closed"] > ref)):
            ours[r["sido"]][0] += 1
            ours[r["sido"]][1] += r["rooms"] or 0
    out = sorted(([s, round(sum(num(x[cnt_k]) for x in xs)), ours[s][0], round(sum(num(x[room_k]) for x in xs)) if room_k else None, ours[s][1]]
                  for s, xs in by.items()), key=lambda x: -x[1])
    out.append(["합계", sum(x[1] for x in out), sum(x[2] for x in out), sum(x[3] for x in out) if room_k else None, sum(x[4] for x in out)])
    print(f"mcst_lodging: validation {ref}, official {out[-1][1]} / permit records {out[-1][2]} 관광숙박업 (count column {cnt_k}, rooms {room_k})", flush=True)
    return {"table": re.sub(r"_?\d{8}$", "", title), "date": ref, "rows": out}


PANEL_FROM = 2010


def write_panel(rows, sidos, sido_meta, tidx, visits):
    """data/download/panel_sgg.csv: one row per 시군구 and year (PANEL_FROM to last year) for research use; columns in
    site/codebook.html. Stock = operating or paused at the year end (permit year ≤ y, not closed by then); closed records
    without a date are left out throughout, as in "stk". 활동 = the stock plus those closed during the year, so
    신생률 / 소멸률 follow 통계청 기업생멸행정통계 (신생·소멸 ÷ 활동). 객실 uses room_rule. Visitors are summed over
    the year's four quarters when DataLab covers the whole year (blank otherwise, e.g. 인천's 2026 구 before they existed)."""
    last = datetime.now(KST).year - 1
    years = list(range(PANEL_FROM, last + 1))
    med, cap, _ = room_rule(rows, tidx)
    zero = lambda: {"stock": [0] * len(CATEGORIES), "rooms": 0, "new": 0, "closed": 0}
    acc = defaultdict(zero)
    for r in rows:
        if not r["date"][:4].isdigit() or (r["status"] == 2 and not r["closed"][:4].isdigit()):
            continue
        py, cy = int(r["date"][:4]), int(r["closed"][:4]) if r["status"] == 2 else None
        t, ci = tidx[(r["cat"], r["type"])], CATEGORIES.index(r["cat"])
        rooms = min(r["rooms"], cap.get(t, r["rooms"])) if r["rooms"] else med.get(t, 0)
        for y in range(max(py, PANEL_FROM), last + 1):
            a = acc[(r["sido"], r["sgg"], y)]
            a["new"] += py == y
            if cy == y:
                a["closed"] += 1
            if cy is None or cy > y:
                a["stock"][ci] += 1
                a["rooms"] += rooms
    q = visits["q"] if visits else []

    def year_vis(series, y):
        idx = [q.index(f"{y}Q{k}") if f"{y}Q{k}" in q else None for k in (1, 2, 3, 4)]
        if not series or None in idx or sum(visits["qdays"][i] for i in idx) < calendar.isleap(y) + 365:
            return ["", ""]
        return [sum(series[j][i] for i in idx) if all(series[j][i] is not None for i in idx) else "" for j in (0, 1)]
    path = os.path.join(OUT, "download", "panel_sgg.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["시도", "시군구", "연도", "인구감소지역", "연말운영시설", *(f"연말운영_{c}" for c in CATEGORIES), "연말객실(보정)",
                    "신규인허가", "폐업", "활동시설", "신생률(%)", "소멸률(%)", "외지인누적방문자", "외국인누적방문자"])
        for si, (s, sm) in enumerate(zip(sidos, sido_meta)):
            for gi, g in enumerate(sm["sgg"]):
                decl = ["", "인구감소지역", "인구감소관심지역"][(sm.get("decl") or [0] * len(sm["sgg"]))[gi]]
                ser = visits["sgg"][si][gi] if visits else None
                for y in years:
                    a = acc.get((s, g, y)) or zero()
                    n, act = sum(a["stock"]), sum(a["stock"]) + a["closed"]
                    w.writerow([s, g, y, decl, n, *a["stock"], round(a["rooms"]), a["new"], a["closed"], act,
                                round(a["new"] / act * 100, 2) if act else "", round(a["closed"] / act * 100, 2) if act else "",
                                *year_vis(ser, y)])
    print(f"panel: {sum(len(sm['sgg']) for sm in sido_meta)} 시군구 × {len(years)} years ({years[0]}–{years[-1]})", flush=True)


OLD_TYPES = {("숙박업", "여관업"), ("숙박업", "여인숙업")}  # 노후 숙박: the old roadside-inn stock
COMMERCIAL = {"중심상업지역", "일반상업지역", "근린상업지역", "유통상업지역"}


def load_vworld_land():
    """관리번호 -> (개별공시지가 원/㎡ or None, 기준연도, 용도지역) of open 여관·여인숙 from scripts/static/vworld_land.csv(.gz),
    written by scripts/vworld_land.py on a PC in Korea (VWorld refuses GitHub Actions). {} without the file."""
    for path in (os.path.join(ROOT, "scripts", "static", f) for f in ("vworld_land.csv.gz", "vworld_land.csv")):
        if os.path.exists(path):
            with (gzip.open(path, "rt", encoding="utf-8-sig") if path.endswith(".gz") else open(path, encoding="utf-8-sig")) as f:
                out = {r["관리번호"]: (int(r["cbnd.jiga"]) if r.get("cbnd.jiga") else None, r.get("cbnd.gosi_year") or "", r.get("zone.uname") or "")
                       for r in csv.DictReader(f)}
            print(f"vworld_land: {len(out)} facilities, {sum(1 for v in out.values() if v[0])} with 공시지가, "
                  f"{sum(1 for v in out.values() if v[2])} with 용도지역", flush=True)
            return out
    return {}


def land_stats(xs):
    """[median 공시지가 (원/㎡), facilities with one, facilities with a known 용도지역, of them in a 상업지역] or None when
    fewer than 5 have a 공시지가. The 용도지역 is often blank (a quarter of Seoul's), so its share counts only known ones."""
    v = [j for j, _, z in xs if j]
    return [round(statistics.median(v)), len(v), sum(1 for *_, z in xs if z), sum(1 for *_, z in xs if z in COMMERCIAL)] if len(v) >= 5 else None


def room_rule(rows, tidx):
    """객실 수 rule shared by the charts: per 업종 index the median and 99.9th percentile of the operating facilities'
    reported 객실 수 (an empty one takes the median, one above the percentile is cut to it), and per 업종 the share of
    operating facilities that report one."""
    by_t = defaultdict(list)
    for r in rows:
        if r["status"] == 0:
            by_t[tidx[(r["cat"], r["type"])]].append(r["rooms"])
    med, cap = {}, {}
    for t, xs in by_t.items():
        v = sorted(x for x in xs if x)
        if v:
            med[t], cap[t] = statistics.median(v), v[int(len(v) * 0.999)]
    cov = [round(sum(1 for x in by_t.get(t, []) if x) / len(by_t[t]), 3) if by_t.get(t) else 0 for t in range(max(tidx.values()) + 1)]
    return med, cap, cov


def add_change_old(rows, sidos, sido_meta, tidx, land):
    """Per 시군구 in meta.sido[]: "r12" = [[업종, new permits, closings, operating or paused now], …] over the last
    365 days (only 업종 with any), for the map's net-change colouring; "old" = [operating 여관·여인숙, of them licensed
    20+ years ago, 30+ years ago]; "oldland" (and "oldland_sido" for the whole 시도) = land_stats of the 30+ year ones
    from `land` (VWorld 공시지가·용도지역); "stk" = [[업종, stock at the end of each of STOCK_YEARS], …] (operating or paused that day, from the
    permit and closing dates; closed records without a date are left out), followed by the summed 객실 수 at the same
    year ends (an empty one takes the median of the 업종, one above the 업종's 99.9th percentile is cut to it; 0 for 업종
    without a 객실 column), for the supply vs demand growth chart. Returns (STOCK_YEARS, per 업종 the share of operating
    facilities with a 객실 수)."""
    today = datetime.now(KST).date()
    since, y20, y30 = (today - timedelta(days=365)).isoformat(), today.year - 20, today.year - 30
    years = list(range(today.year - 4, today.year))
    med, cap, cov = room_rule(rows, tidx)
    for si, (s, sm) in enumerate(zip(sidos, sido_meta)):
        gi_of = {g: i for i, g in enumerate(sm["sgg"])}
        r12 = [defaultdict(lambda: [0, 0, 0]) for _ in sm["sgg"]]
        stk = [defaultdict(lambda: [0] * (2 * len(years))) for _ in sm["sgg"]]
        old = [[0, 0, 0] for _ in sm["sgg"]]
        old_land = [[] for _ in sm["sgg"]]
        for r in rows:
            if r["sido"] != s:
                continue
            gi, t = gi_of[r["sgg"]], tidx[(r["cat"], r["type"])]
            c = r12[gi][t]
            c[0] += r["date"] > since
            c[1] += r["status"] == 2 and r["closed"] > since
            c[2] += r["status"] < 2
            if r["status"] == 0 and (r["cat"], r["type"]) in OLD_TYPES:
                old[gi][0] += 1
                old[gi][1] += bool(r["date"]) and int(r["date"][:4]) <= y20
                old[gi][2] += bool(r["date"]) and int(r["date"][:4]) <= y30
                if r["date"] and int(r["date"][:4]) <= y30 and r["id"] in land:
                    old_land[gi].append(land[r["id"]])
            if r["date"] and (r["status"] < 2 or r["closed"]):
                rooms = min(r["rooms"], cap.get(t, r["rooms"])) if r["rooms"] else med.get(t, 0)
                for k, y in enumerate(years):
                    if int(r["date"][:4]) <= y and (r["status"] < 2 or int(r["closed"][:4]) > y):
                        stk[gi][t][k] += 1
                        stk[gi][t][len(years) + k] += rooms
        sm["r12"] = [[[t, *v] for t, v in sorted(d.items()) if any(v)] for d in r12]
        sm["stk"] = [[[t, *v[:len(years)], *(round(x) for x in v[len(years):])] for t, v in sorted(d.items()) if any(v)] for d in stk]
        sm["old"] = old
        if land:
            sm["oldland"] = [land_stats(xs) for xs in old_land]
            sm["oldland_sido"] = land_stats([x for xs in old_land for x in xs])
    return years, cov


def add_land_price(sidos, sgg_of, sido_meta):
    """meta.sido[]["land"] = per 시군구 지가변동률 (%) of the latest year in raw/land_price.json (한국부동산원), None when
    the table has no row of that name (e.g. 구 created after that year); ["land_sido"] = the 시도 value. Rows are
    "시도>시군구" (구 of a 시 are skipped, the 시 row is used); "전남광주>광주>동구" counts toward the merged 시도.
    Returns the year, or None without the file."""
    path = os.path.join(RAW, "land_price.json")
    if not os.path.exists(path):
        return None
    rows = json.load(open(path, encoding="utf-8"))["rows"]
    year = max(r[0] for r in rows)
    val, missed = {}, []
    for y, full, v in rows:
        if y != year:
            continue
        parts = full.split(">")
        if parts[0] == "전남광주":  # "전남광주" = the merged 시도; "전남광주>광주" / ">전남" = the former 시도, skipped
            if len(parts) == 1:
                val[(MERGED_GWANGJU_JEONNAM, None)] = round(float(v), 3)
            if len(parts) <= 2:
                continue
            parts = parts[1:]
        sido = SIDO_ALIASES.get(parts[0])
        if sido in ("광주광역시", "전라남도") and MERGED_GWANGJU_JEONNAM in sidos:
            sido = MERGED_GWANGJU_JEONNAM
        if sido not in sidos or len(parts) > 2:
            continue
        val[(sido, parts[1] if len(parts) == 2 else None)] = round(float(v), 3)
    for s, sm in zip(sidos, sido_meta):
        sm["land_sido"] = val.get((s, None))
        sm["land"] = [val.get((s, g), val.get((s, None)) if g == s else None) for g in sgg_of[s]]
        missed += [f"{s} {g}" for g, v in zip(sgg_of[s], sm["land"]) if v is None]
    print(f"land_price {year}: {sum(v is not None for sm in sido_meta for v in sm['land'])} 시군구 matched; no value: {' '.join(missed)}", flush=True)
    return year


def national_brief(rows, tidx):
    """National numbers for the page's briefing, per 업종 index: new permits and closings from 1 Jan to today this year
    and over the same dates last year ("ytd"), and operating facilities with the share licensed 20+ years ago ("age")."""
    today = datetime.now(KST).date()
    y, md = today.year, today.strftime("%m-%d")
    n = max(tidx.values()) + 1
    ytd = {"y": y, "md": md, "new": [[0, 0] for _ in range(n)], "closed": [[0, 0] for _ in range(n)]}
    age = [[0, 0] for _ in range(n)]
    for r in rows:
        t = tidx[(r["cat"], r["type"])]
        for key, d in (("new", r["date"]), ("closed", r["closed"] if r["status"] == 2 else "")):
            if d and d[5:] <= md and d[:4] in (str(y), str(y - 1)):
                ytd[key][t][0 if d[:4] == str(y) else 1] += 1
        if r["status"] == 0 and r["date"]:
            age[t][0] += 1
            age[t][1] += int(r["date"][:4]) <= y - 20
    return {"ytd": ytd, "age": age}


SURV_FROM = "2010-01-01"  # cohort for the survival curves: permits since then (older closings are less complete)


def write_survival(rows, sidos, sgg_of):
    """Kaplan-Meier survival of lodgings by 업종 대분류 (and all together) for the nation, each 시도 and 시군구:
    survival.json = {"t": [1..10 years], "cats": [...], "v": {key: [[S(t) % or null] per group]}, "n": {key: [n per group]}}.
    Start = permit date (since SURV_FROM); event = closing (폐업 with a date); 영업·휴업 are censored at today;
    폐업 without a date is left out. S(t) is null when fewer than 20 remain at risk at t."""
    today = datetime.now(KST).date()
    months = lambda a, b: (b - a).days / 30.4375
    groups = defaultdict(list)  # (key, group) -> [(months, event)]
    gi_of = {s: {g: i for i, g in enumerate(sgg_of[s])} for s in sidos}
    ci = {c: i for i, c in enumerate(CATEGORIES)}
    for r in rows:
        if not r["date"] or r["date"] < SURV_FROM:
            continue
        try:
            start = datetime.strptime(r["date"], "%Y-%m-%d").date()
            if r["status"] == 2:
                if not r["closed"]:
                    continue
                end, ev = datetime.strptime(r["closed"], "%Y-%m-%d").date(), 1
            else:
                end, ev = today, 0
        except ValueError:
            continue
        if end < start or start > today:
            continue
        si = sidos.index(r["sido"])
        for key in ("nat", str(si), f"{si}:{gi_of[r['sido']][r['sgg']]}"):
            for g in (0, 1 + ci[r["cat"]]):  # 0 = 전체
                groups[(key, g)].append((months(start, end), ev))
    T = list(range(1, 11))
    out_v, out_n = defaultdict(lambda: [None] * (1 + len(CATEGORIES))), defaultdict(lambda: [0] * (1 + len(CATEGORIES)))
    for (key, g), obs in groups.items():
        obs.sort()
        at_risk, surv, k, curve = len(obs), 1.0, 0, []
        for t in T:
            while k < len(obs) and obs[k][0] <= t * 12:  # events and censorings up to t years, ties counted together
                tm, d, c = obs[k][0], 0, 0
                while k < len(obs) and obs[k][0] == tm:
                    d += obs[k][1]
                    c += 1 - obs[k][1]
                    k += 1
                if d:
                    surv *= 1 - d / at_risk
                at_risk -= d + c
            curve.append(round(surv * 100, 1) if at_risk >= 20 else None)
        out_v[key][g], out_n[key][g] = curve, len(obs)
    with open(os.path.join(OUT, "survival.json"), "w", encoding="utf-8") as f:
        json.dump({"t": T, "from": SURV_FROM[:4], "cats": CATEGORIES, "v": out_v, "n": out_n}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"survival: {len(out_v)} areas; national 3/5-year survival "
          f"{out_v['nat'][0][2] if out_v.get('nat') else '-'}% / {out_v['nat'][0][4] if out_v.get('nat') else '-'}%", flush=True)


def load_dong_pop(merged):
    """Population per 법정 읍·면·동 (국립환경과학원 생활계 인구현황, 리 summed) keyed by (시도, 시군구, 읍면동), 일반구 counted
    in their 시, plus a (시도, 읍면동) index for names whose 구 changed after the survey year (인천 2026). Returns
    (by_key, by_sido_emd, year)."""
    path = os.path.join(RAW, "dong_pop.json")
    if not os.path.exists(path):
        return {}, {}, None
    d = json.load(open(path, encoding="utf-8"))
    by_key, by_name = Counter(), defaultdict(Counter)
    for r in d["rows"]:
        sido = SIDO_ALIASES.get(r["sido"], r["sido"])
        if merged and sido in ("광주광역시", "전라남도"):
            sido = MERGED_GWANGJU_JEONNAM
        m = re.fullmatch(r"(\S+?시)\s?\S+구", r["sgg"])
        sgg = sido if sido == "세종특별자치시" or not r["sgg"] else (m.group(1) if m else r["sgg"])
        by_key[(sido, sgg, r["emd"])] += r["pop"]
        by_name[(sido, r["emd"])][sgg] += r["pop"]
    unique = {k: sum(v.values()) for k, v in by_name.items() if len(v) == 1}
    return by_key, unique, d["year"]


def add_decline(sidos, sgg_of, sido_meta, merged):
    """인구감소지역 (1) / 인구감소관심지역 (2) per 시군구 from scripts/static/decline_areas.json: sido_meta[i]["decl"],
    and the 시군구 indices of 인구활력 플러스 areas in ["declp"]. Returns the designation date."""
    d = json.load(open(os.path.join(ROOT, "scripts", "static", "decline_areas.json"), encoding="utf-8"))
    for sm in sido_meta:
        sm["decl"], sm["declp"] = [0] * len(sm["sgg"]), []
    unmatched = []
    for kind, code in (("decline", 1), ("watch", 2), ("plus", 0)):
        for sido, names in d[kind].items():
            sido = MERGED_GWANGJU_JEONNAM if merged and sido in ("광주광역시", "전라남도") else SIDO_ALIASES.get(sido, sido)
            for g in names:
                if sido not in sidos or g not in sgg_of[sido]:
                    unmatched.append(f"{sido} {g}")
                    continue
                sm, gi = sido_meta[sidos.index(sido)], sgg_of[sido].index(g)
                if code:
                    sm["decl"][gi] = code
                else:
                    sm["declp"].append(gi)
    print(f"decline: {sum(x == 1 for sm in sido_meta for x in sm['decl'])} 인구감소지역, {sum(x == 2 for sm in sido_meta for x in sm['decl'])} 관심지역; "
          f"not found: {' '.join(unmatched) or '-'}", flush=True)
    return d["designated"]


def add_urban(sidos, sgg_of, sido_meta, merged):
    """법정 도시지역 per 시군구 from scripts/static/upis.csv (국토교통부 도시계획현황, made by korea-transit-gap's
    upis_csv.py): [용도지역 합계 ㎡, 도시지역 ㎡, 전체 인구, 도시지역 인구] in sido_meta[i]["urban"] (per 시군구, None if
    not listed), ["urban_sido"] and in each group's "urban". 인천's new 구 are not in the 2025 statistics; its group of
    the old 중구·동구·서구 adds those old rows. Returns the base year."""
    path = os.path.join(ROOT, "scripts", "static", "upis.csv")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by = {}
    for r in rows:
        sido = MERGED_GWANGJU_JEONNAM if merged and r["시도"] in ("광주광역시", "전라남도") else SIDO_ALIASES.get(r["시도"], r["시도"])
        by[(sido, r["시군구"])] = [float(r["용도지역합계_m2"]), float(r["도시지역_m2"]), float(r["전체인구"] or 0), float(r["도시지역인구"] or 0)]
    add = lambda xs: [sum(x[k] for x in xs) for k in range(4)] if xs else None
    for sido, sm in zip(sidos, sido_meta):
        sm["urban"] = [by.get((sido, g)) for g in sgg_of[sido]]
        sm["urban_sido"] = add([v for (s, _), v in by.items() if s == sido])
        for g in sm.get("groups", []):
            names = [sgg_of[sido][gi] for gi in g["gis"]] + (list(INCHEON_OLD) if g.get("own") else [])
            g["urban"] = add([by[(sido, n)] for n in names if (sido, n) in by])
    print(f"urban: {sum(v is not None for sm in sido_meta for v in sm['urban'])} 시군구 with 도시지역 ({rows[0]['기준연도'] if rows else '-'}); "
          f"without: {' '.join(f'{s}/{g}' for s, sm in zip(sidos, sido_meta) for g, v in zip(sgg_of[s], sm['urban']) if v is None) or '-'}", flush=True)
    return rows[0]["기준연도"] if rows else None


def data_dates(admin_ver, pop_ym, decl_date=None, dpop_year=None):
    """[[자료, 기준 시점, 갱신]] for the page's '데이터 기준일' panel, read from the files just written."""
    def out(name):
        p = os.path.join(OUT, name)
        return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    ym = lambda s: f"{s[:4]}.{s[4:6]}" if s else "-"
    today = datetime.now(KST).strftime("%Y.%m.%d")
    vis, kto, arr, icn, kac, stn = out("visits.json"), out("kto_index.json"), out("arrivals.json"), out("icn.json"), out("kac.json"), out("stations.json")
    rows = [["숙박 인허가 8종 (행정안전부)", today, "매일"],
            ["관광지·축제 (한국관광공사 TourAPI)", today, "매일"],
            ["외지인·외국인 방문객 (한국관광데이터랩)", f"{ym(vis.get('last'))}.{vis['last'][6:]}까지" if vis.get("last") else "-", "매일(최근 3개월 다시 받음)"],
            ["관광수요지수 (한국관광공사)", ym((kto.get("months") or [""])[-1]), "월별"],
            ["주민등록 인구 (행정안전부)", f"{ym(pop_ym)} 말" if pop_ym else "-", "월별"],
            ["방한 외래관광객 (한국문화관광연구원)", ym((arr.get("months") or [""])[-1]), "월별"],
            ["인천공항 국가별 여객 (인천국제공항공사)", ym((icn.get("months") or [""])[-1]), "월별"],
            ["공항별 여객 (한국공항공사)", f"{(kac.get('years') or ['-'])[-1]}년", "연 단위"],
            ["코레일 광역철도 승하차", ym((stn.get("kym") or [""])[-1]), "월별"],
            ["코레일 간선열차 승하차", ym((stn.get("mym") or [""])[-1]), "매일(월별 합계)"],
            ["모범음식점·백년가게 (행정안전부·소상공인시장진흥공단)", today, "매일"],
            ["행정구역 경계 (통계청 SGIS·admdongkor)", f"{admin_ver[3:7]}.{admin_ver[7:9]}.{admin_ver[9:]}판" if admin_ver else "-", "새 판이 나오면"],
            ["철도·역·국립공원 경계 (OpenStreetMap)", today, "매일"],
            ["읍·면·동 인구 (국립환경과학원 생활계 인구현황)", f"{dpop_year}년" if dpop_year else "-", "연 단위"],
            ["인구감소지역 지정 (행정안전부)", f"{decl_date.replace('-', '.')} 고시" if decl_date else "-", "5년마다 재지정"]]
    return rows


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
    tidx = {t: i for i, t in enumerate(types)}  # (대분류, 업종): the same 업종 name can sit in two 대분류 (휴양콘도미니엄업)
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
    dpop_key, dpop_name, dpop_year = load_dong_pop(merged)
    dpop_hit = dpop_all = 0
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
            cube[(si, g, tidx[(r["cat"], r["type"])], r["status"], y)] += 1
            if y >= Q_FROM:
                cubeq[(si, g, tidx[(r["cat"], r["type"])], r["status"], y * 10 + quarter(r["date"]))] += 1
            if cy >= Q_FROM:
                closeq[(si, g, tidx[(r["cat"], r["type"])], cy * 10 + quarter(r["closed"]))] += 1
            if cy:
                close[(si, g, tidx[(r["cat"], r["type"])], cy, y)] += 1
            if r["zone"] >= 0:
                minbak[(si, g, r["status"], r["zone"], r["bldg"])] += 1
            lat, lon = r["ll"] if r["ll"] else (None, None)
            out.append([lat, lon, tidx[(r["cat"], r["type"])], g, d, q, r["status"], y, cy,
                        r["name"], re.sub(r"^\S+\s", "", r["road"] or r["lot"]), r["date"], r["closed"], r.get("approx", 0),
                        r["zone"], r["bldg"], r["rooms"] or 0])
            if r["ll"]:
                cen[r["sgg"]].append(r["ll"])
        # 읍·면·동 주민 수(생활계 인구현황): 같은 시군구의 같은 이름, 없으면 시도 안에서 이름이 하나뿐인 동
        dpop = [[dpop_key.get((s, g, dn)) or dpop_name.get((s, dn)) for dn in ds] for g, ds in zip(sggs, dongs)] if dpop_key else None
        if dpop:
            dpop_all += sum(len(x) for x in dpop)
            dpop_hit += sum(1 for x in dpop for v in x if v)
        with open(os.path.join(OUT, "pts", f"{si}.json"), "w", encoding="utf-8") as f:
            json.dump({"dongs": dongs, "ris": {f"{k[0]}:{k[1]}": v for k, v in ris.items()}, "rows": out, "dpop": dpop},
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
        if s == "인천광역시" and any(g in sggs for g in INCHEON_NEW):  # own = 방문객을 묶음 단위로 따로 가짐(구별 자료 없음)
            sido_meta[-1]["groups"] = [{"name": INCHEON_GROUP, "gis": [sggs.index(g) for g in INCHEON_NEW + INCHEON_OLD if g in sggs], "own": 1}]
    if dpop_key:
        print(f"dong_pop: {dpop_year}, population found for {dpop_hit} of {dpop_all} 읍·면·동", flush=True)
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
    pop_ym = add_population(sidos, sgg_of, sido_meta)
    decl_date = add_decline(sidos, sgg_of, sido_meta, merged)
    vland = load_vworld_land()
    stock_years, room_cov = add_change_old(rows, sidos, sido_meta, tidx, vland)
    land_year = add_land_price(sidos, sgg_of, sido_meta)
    urban_year = add_urban(sidos, sgg_of, sido_meta, merged)
    typology = add_typology(sido_meta, [(*k, v) for k, v in cube.items()], types, visits)
    write_download(rows, sidos, sido_meta, vland)
    write_panel(rows, sidos, sido_meta, tidx, visits)
    valid = add_validation(rows, sidos, merged)
    write_arrivals()
    write_icn()
    write_kto_index(sidos, sgg_of)
    write_kac()
    write_subway()
    parks = write_park_areas()
    write_stations(rows, sidos, sgg_of, tidx)
    write_festivals(rows, sidos, sgg_of, tidx, merged)
    write_trrsrt(rows, sidos, sgg_of, tidx, merged)
    write_park_lodging(rows, parks, sidos, sgg_of, tidx)
    write_food(sidos, sido_meta, merged)
    bus = write_bus(rows, sidos, sgg_of, tidx)
    write_survival(rows, sidos, sgg_of)
    admin_ver = write_admin(sidos, sido_meta, merged)
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
        "pop_ym": pop_ym,
        "fresh": data_dates(admin_ver, pop_ym, decl_date, dpop_year),
        "dpop_year": dpop_year,
        "brief": national_brief(rows, tidx),
        "bus": bus,
        "stock_years": stock_years,
        "room_cov": room_cov,
        "room_rule": (lambda mc: {"med": [mc[0].get(t) for t in range(len(types))], "cap": [mc[1].get(t) for t in range(len(types))]})(room_rule(rows, tidx)),
        "land_year": land_year,
        "urban_year": urban_year,
        "valid": valid,
        "typology": typology,
        "transit": (lambda t: {"route_days": t.get("route_days", [])})(json.load(open(os.path.join(RAW, "transit_stops.json"), encoding="utf-8")))
        if os.path.exists(os.path.join(RAW, "transit_stops.json")) else None,
        "vworld_year": Counter(v[1] for v in vland.values() if v[1]).most_common(1)[0][0] if vland else None,
    }
    with open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))
    print(json.dumps({k: meta[k] for k in ("counts", "dedupe", "coords", "unknown_region")}, ensure_ascii=False)[:1500])


if __name__ == "__main__":
    main()
