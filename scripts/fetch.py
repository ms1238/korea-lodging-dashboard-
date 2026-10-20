"""Download every record from the 8 MOIS permit APIs into raw/<endpoint>.jsonl,
plus tourist attractions from the Korea Tourism Organization TourAPI (KorService2) into raw/tour_<type>.jsonl,
plus visitor counts from the KTO DataLabService (daily since 2018, summed per month) into raw/datalab_sido.jsonl / datalab_sgg.jsonl,
plus monthly foreign arrivals by nationality (한국문화관광연구원 출입국관광통계, since 2018) into raw/arrivals.jsonl,
plus subway / light-rail routes with their line colours from OpenStreetMap (Overpass API, no key) into raw/subway.json,
plus national-park boundaries from OpenStreetMap into raw/parks_osm.json.

`--only-missing` fetches only sources that have no file in raw/ yet (used on code pushes, which reuse cached data).

Endpoint pattern: https://apis.data.go.kr/1741000/<endpoint>/info
The service key is read from the DATA_GO_KR_KEY environment variable (a GitHub Actions secret);
it must never be written into the repository.
"""
import csv
import io
import json
import math
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import requests

ENDPOINTS = [
    "lodgings",                  # 숙박업
    "tourist_accommodations",    # 관광숙박업
    "foreigner_city_homestays",  # 외국인관광 도시민박업
    "rural_homestays",           # 농어촌민박업
    "tourist_pensions",          # 관광펜션업
    "hanok_experience",          # 한옥체험업
    "general_campgrounds",       # 일반야영장업
    "auto_campgrounds",          # 자동차야영장업
]
BASE = "https://apis.data.go.kr/1741000/{}/info"
TOUR_BASE = "https://apis.data.go.kr/B551011/KorService2/areaBasedList2"
TOUR_TYPES = {"12": "관광지", "14": "문화시설", "28": "레포츠"}  # TourAPI contentTypeId
FESTIVALS = "https://apis.data.go.kr/B551011/KorService2/searchFestival2"  # TourAPI 행사·축제
CENTURY_SPEC = "https://infuser.odcloud.kr/oas/docs?namespace=15132695/v1"  # 소상공인시장진흥공단 백년가게 (odcloud, one table per publication)
DONG_POP = "https://apis.data.go.kr/1480523/LvlhPpnSttusService/getLvlhPpnSttusInfo"  # 국립환경과학원 생활계 인구현황 (법정동·리, yearly)
FOOD_MATCH_BUDGET = 6000  # 일반음식점 lookups per run (one per restaurant); the rest waits for the next run
FOOD_MATCH_MINUTES = 20  # stop after this long so the job (90 min limit) still saves what it found
FESTIVALS_FROM = "20180101"  # an entry carries only its latest edition's dates, so an early start date returns the whole list
DATALAB_BASE = "https://apis.data.go.kr/B551011/DataLabService/{}"
# output file -> (operation, region code field, region name field); 광역 and 기초 visitor counts per day
DATALAB_FROM = 2018  # first year the service has data for
ARRIVALS = "https://apis.data.go.kr/B551940/EdrcntTourismStatsService/getEdrcntTourismStatsList"
ICN = "https://apis.data.go.kr/B551177/AviationStatsByCountry/getTotalNumberOfPassenger"  # 인천공항 국가별 여객
KORAIL_WIDE = "https://apis.data.go.kr/B551457/issueStatistics/wideRailloadStationPer"  # 코레일 광역철도 역별 승하차
KAC_SPEC = "https://infuser.odcloud.kr/oas/docs?namespace=15002610/v1"  # 한국공항공사 공항별 여객실적 (odcloud)
# 관광수요지수 구성 지표 (한국관광데이터랩): (operation, indicator parameter, indicator codes). Values are indices, not counts.
KTO_INDEX = [
    ("AreaTarDemDsService/areaTarSjrnDsList", "tarSjrnDsIxCd", ("21", "2101", "2102", "2103", "2104", "2105")),
    ("AreaTarDemDsService/areaTarExpDsList", "tarExpDsIxCd", ("22",)),
    ("AreaTarDivService/areaTouDivList", "touDivIxCd", ("31",)),
    ("AreaTarDivService/areaExpDivList", "expDivIxCd", ("32",)),
    ("AreaTarDivService/areaIntlDivList", "intlDivIxCd", ("33",)),
]
# 관광 자원 수요 (same family, own raw file so a code push fetches it when missing): 관광서비스 수요, 숙박업 소비액,
# 내비게이션 숙박유형 검색량, 문화자연자원 수요
KTO_RES = [
    ("AreaTarResDemService/areaTarSvcDemList", "tarSvcDemIxCd", ("11", "1107", "1110")),
    ("AreaTarResDemService/areaCulResDemList", "culResDemIxCd", ("12",)),
]
KTO_INDEX_AREAS = ("11", "26", "27", "28", "29", "30", "31", "36", "41", "43", "44", "46", "47", "48", "50", "51", "52", "12")  # DataLab 시도 codes
KTO_INDEX_BUDGET = 800  # requests per service and run (the development quota is 1,000 a day); the rest waits for the next run
POPULATION = "https://apis.data.go.kr/1741000/admmPpltnHhStus/selectAdmmPpltnHhStus"  # 행정동별 주민등록 인구 및 세대현황 (monthly)
KORAIL_MAIN = "https://apis.data.go.kr/B551457/issueStatistics/mainLineStationPer"  # 코레일 간선열차 역별 승하차 (daily, about a year)
METRO_STD = "https://www.data.go.kr/data/15013205/standard.do"  # 전국도시철도역사정보표준데이터 (국가철도공단, yearly file)
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
# a bounding box of South Korea instead of an area lookup: some mirrors have no area index and answer 500
SUBWAY_QUERY = """[out:json][timeout:240];
relation["route"~"^(subway|light_rail)$"](33.0,124.5,38.7,131.0);
out geom;"""
# 광역·도시철도 tagged route=train (서해선, 경의·중앙선, 수인·분당선, 경춘선, 공항철도, GTX-A, 신분당선, 대경선, 동해선 …) and KTX
RAIL_ROUTES_QUERY = """[out:json][timeout:300];
(relation["route"="train"]["colour"](33.0,124.5,38.7,131.0);
 relation["route"="train"]["name"~"KTX"](33.0,124.5,38.7,131.0);
 relation["route"="train"]["network"~"^(KTX|고속철도)$"](33.0,124.5,38.7,131.0););
out geom;"""
PARKS_QUERY = """[out:json][timeout:240];
(relation["boundary"="national_park"](33.0,124.5,38.7,131.0);
 relation["boundary"="protected_area"]["protect_class"="2"](33.0,124.5,38.7,131.0);
 way["boundary"="national_park"](33.0,124.5,38.7,131.0););
out geom;"""
# 행정동 boundaries (vuski/admdongkor, from 통계청 boundaries; follows reorganizations such as Incheon's new 구 in 2026)
ADMDONG_REPO = "https://api.github.com/repos/vuski/admdongkor/contents"
# subway / light-rail stations; 수도권 전철 stations run by Korail are often railway=station + subway=yes
STATIONS_QUERY = """[out:json][timeout:180];
(nwr["railway"="station"]["station"~"^(subway|light_rail|monorail)$"](33.0,124.5,38.7,131.0);
 nwr["railway"="station"]["subway"="yes"](33.0,124.5,38.7,131.0);
 nwr["railway"="station"]["light_rail"="yes"](33.0,124.5,38.7,131.0););
out center tags;"""
# every railway station: 광역철도 lines run by Korail (경의중앙, 경춘, 수인분당, 서해, 동해선, 대경선 ...) are tagged as
# ordinary railway stations, so the build adds those whose name appears in the 코레일 광역철도 table
RAIL_STATIONS_QUERY = """[out:json][timeout:180];
nwr["railway"~"^(station|halt)$"](33.0,124.5,38.7,131.0);
out center tags;"""
OPTIONAL = {"subway", "rail_routes", "parks_osm", "stations", "rail_stations", "icn", "korail_wide", "korail_main", "metro_std", "kac_years", "kto_index", "kto_res", "pop_month", "festivals", "excellent_restaurant_info", "century_shops", "food_coords", "admin_dong", "dong_pop"}  # the page works without these, so a failed first fetch does not stop the deploy
JSON_FILES = {"rail_routes", "dong_pop", "admin_dong", "food_coords", "century_shops", "subway", "parks_osm", "stations", "rail_stations", "korail_wide", "metro_std", "kac_years", "pop_month"}  # raw/<name>.json; the others are .jsonl
DATALAB = {"datalab_sido": ("metcoRegnVisitrDDList", "areaCode", "areaNm"),
           "datalab_sgg": ("locgoRegnVisitrDDList", "signguCode", "signguNm")}
PAGE_SIZE = 100  # the API caps numOfRows at 100 regardless of what is requested
WORKERS = 6
RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "raw")


def get_page(key, endpoint, page):
    if endpoint.startswith("tour_"):
        url = TOUR_BASE
        params = {"serviceKey": key, "pageNo": page, "numOfRows": 1000, "_type": "json",
                  "MobileOS": "ETC", "MobileApp": "korea-lodging-dashboard", "contentTypeId": endpoint[5:]}
    else:
        url = BASE.format(endpoint)
        params = {"serviceKey": key, "pageNo": page, "numOfRows": PAGE_SIZE, "returnType": "json"}
    return get_body(url, params, f"{endpoint} page {page}")


def get_body(url, params, what):
    last = None
    for attempt in range(8):
        try:
            r = requests.get(url, params=params, timeout=90)
            data = r.json()
            if "response" not in data:
                # e.g. {"OpenAPI_ServiceResponse": {"cmmMsgHeader": {"errMsg": ...}}}
                raise RuntimeError(f"API error: {json.dumps(data, ensure_ascii=False)[:300]}")
            return data["response"]["body"]
        except Exception as e:  # network resets are common; back off and retry
            last = e
            time.sleep(3 + attempt * 3)
    raise RuntimeError(f"{what} failed: {last}")


def items_of(body):
    items = body.get("items") or {}
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    return items or []


def write_rows(name, rows):
    """Write raw/<name>.jsonl atomically, so a failed fetch never leaves a half-written file behind."""
    path = os.path.join(RAW_DIR, f"{name}.jsonl")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(path + ".tmp", path)


def check(name, n, total):
    print(f"{name}: total {total}, fetched {n}", flush=True)
    if n < total * 0.98:
        raise RuntimeError(f"{name}: fetched {n} of {total}")


def fetch_permits(key, ep):
    first = get_page(key, ep, 1)
    total = int(first.get("totalCount") or 0)
    size = max(1, len(items_of(first)) or int(first.get("numOfRows") or PAGE_SIZE))
    pages = max(1, math.ceil(total / size))
    with ThreadPoolExecutor(WORKERS) as pool:
        rest = list(pool.map(lambda p: get_page(key, ep, p), range(2, pages + 1)))
    rows = [item for body in [first] + rest for item in items_of(body)]
    check(ep, len(rows), total)
    write_rows(ep, rows)


def overpass(query):
    """Run an Overpass query on the first mirror that answers; returns the elements."""
    rels = None
    for url in OVERPASS:
        for attempt in range(2):
            try:
                r = requests.post(url, data={"data": query}, timeout=300,
                                  headers={"User-Agent": "korea-lodging-dashboard (github.com/ms1238/korea-lodging-dashboard-)"})
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]!r}")
                rels = r.json()["elements"]
                break
            except Exception as e:  # noqa: BLE001
                print(f"  overpass {url} try {attempt + 1}: {e}", flush=True)
                time.sleep(10)
        if rels:
            break
    if not rels:
        raise RuntimeError("all Overpass mirrors failed")
    return rels


def save_json(name, data):
    path = os.path.join(RAW_DIR, name)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(path + ".tmp", path)


def osm_ways(el):
    """[[role, [[lon, lat], …]], …] of a relation's member ways, or of a closed way."""
    if el["type"] == "way" and el.get("geometry"):
        return [["outer", [[round(p["lon"], 5), round(p["lat"], 5)] for p in el["geometry"]]]]
    return [[m.get("role") or "outer", [[round(p["lon"], 5), round(p["lat"], 5)] for p in m["geometry"]]]
            for m in el.get("members", []) if m.get("type") == "way" and m.get("geometry")]


def fetch_admin_dong(_key):
    """The latest 행정동 GeoJSON of vuski/admdongkor (one folder per release, verYYYYMMDD), kept as
    [{sido, sgg, rings: [[[lon, lat], …], …]}] with coordinates rounded to 5 decimals (~1 m)."""
    h = {"User-Agent": "korea-lodging-dashboard (github.com/ms1238/korea-lodging-dashboard-)"}
    ver = max(x["name"] for x in requests.get(ADMDONG_REPO, headers=h, timeout=60).json() if x["type"] == "dir" and x["name"].startswith("ver"))
    files = [x for x in requests.get(f"{ADMDONG_REPO}/{ver}", headers=h, timeout=60).json() if x["name"].endswith(".geojson")]
    feats = requests.get(files[0]["download_url"], headers=h, timeout=300).json()["features"]
    out = []
    for f in feats:
        g, p = f["geometry"], f["properties"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        out.append({"sido": p.get("sidonm", ""), "sgg": p.get("sggnm", ""),
                    "rings": [[[round(x, 5), round(y, 5)] for x, y in ring] for poly in polys for ring in poly]})
    print(f"admin_dong: {ver}, {len(out)} 행정동", flush=True)
    save_json("admin_dong.json", {"ver": ver, "dongs": out})


def fetch_parks_osm(_key):
    """National-park boundaries: relations (outer/inner member ways) and closed ways, with name tags."""
    out = []
    for el in overpass(PARKS_QUERY):
        tags = el.get("tags", {})
        name = tags.get("name:ko") or tags.get("name") or ""
        out.append({"id": f"{el['type']}/{el['id']}", "name": name, "ways": osm_ways(el)})
    print(f"parks_osm: {len(out)} boundaries ({sum('국립공원' in p['name'] for p in out)} named …국립공원)", flush=True)
    if not out:
        raise RuntimeError("no boundaries returned")
    save_json("parks_osm.json", out)


def fetch_stations(_key, query=STATIONS_QUERY, name="stations"):
    """Station points (node, or the centre of a way/relation) with their Korean name."""
    out = []
    for el in overpass(query):
        tags, c = el.get("tags", {}), el.get("center") or el
        label = tags.get("name:ko") or tags.get("name") or ""
        if label and "lat" in c:
            out.append({"id": f"{el['type']}/{el['id']}", "name": label, "lat": round(c["lat"], 5), "lon": round(c["lon"], 5),
                        "op": tags.get("operator", "")})
    print(f"{name}: {len(out)} stations", flush=True)
    if not out:
        raise RuntimeError("no stations returned")
    save_json(f"{name}.json", out)


def fetch_subway(_key, query=SUBWAY_QUERY, name="subway"):
    """Route relations with member way geometry; kept small: name/ref/colour/network/service and rounded coordinates.
    Only relations with a Korean name (the bounding box also reaches Japan and North Korea, whose names are not Hangul
    or whose operator is the DPRK railway)."""
    rels = [r for r in overpass(query) if re.search("[가-힣]", r.get("tags", {}).get("name", ""))
            and "조선" not in r.get("tags", {}).get("operator", "")]
    out = [{"id": rel["id"], **{k: rel.get("tags", {}).get(k, "") for k in ("route", "name", "ref", "colour", "network", "service")},
            "ways": [[m["ref"], [[round(p["lon"], 5), round(p["lat"], 5)] for p in m["geometry"]]]
                     for m in rel.get("members", []) if m.get("type") == "way" and m.get("geometry")]}
           for rel in rels]
    print(f"{name}: {len(out)} routes, {sum(len(r['ways']) for r in out)} ways", flush=True)
    if not out:
        raise RuntimeError("no routes returned")
    save_json(f"{name}.json", out)


def main():
    """Fetch every source. If one fails (e.g. the daily request quota is used up) and a copy from an earlier run
    is present in raw/ (restored from the Actions cache), keep that copy and go on; otherwise stop."""
    key = os.environ.get("DATA_GO_KR_KEY")
    if not key:
        sys.exit("DATA_GO_KR_KEY is not set")
    os.makedirs(RAW_DIR, exist_ok=True)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    only_missing = "--only-missing" in sys.argv
    failed, fetched = [], []
    for ep in args or ENDPOINTS + [f"tour_{c}" for c in TOUR_TYPES] + ["datalab", "arrivals", "subway", "rail_routes", "parks_osm", "stations", "rail_stations", "icn", "korail_wide", "korail_main", "metro_std", "kac_years", "kto_index", "kto_res", "pop_month", "festivals", "excellent_restaurant_info", "century_shops", "food_coords", "admin_dong", "dong_pop"]:
        files = [f"{f}.jsonl" for f in DATALAB] if ep == "datalab" else [f"{ep}.json"] if ep in JSON_FILES else [f"{ep}.jsonl"]
        have = all(os.path.exists(os.path.join(RAW_DIR, f)) for f in files)
        if only_missing and have and ep != "food_coords":  # food_coords fills over several runs, so it also runs on pushes
            continue
        try:
            {"datalab": fetch_datalab, "arrivals": fetch_arrivals, "subway": fetch_subway,
             "rail_routes": lambda k: fetch_subway(k, RAIL_ROUTES_QUERY, "rail_routes"),
             "parks_osm": fetch_parks_osm, "stations": fetch_stations,
             "rail_stations": lambda k: fetch_stations(k, RAIL_STATIONS_QUERY, "rail_stations"), "icn": fetch_icn, "korail_wide": fetch_korail_wide, "korail_main": fetch_korail_main, "metro_std": fetch_metro_std, "kto_index": fetch_kto_index, "kto_res": lambda k: fetch_kto_index(k, KTO_RES, "kto_res"), "pop_month": fetch_population,
             "kac_years": fetch_kac, "festivals": fetch_festivals, "century_shops": fetch_century, "food_coords": fetch_food_coords, "dong_pop": fetch_dong_pop, "admin_dong": fetch_admin_dong}.get(ep, lambda k: fetch_permits(k, ep))(key)
            fetched.append(ep)
        except Exception as e:  # noqa: BLE001
            if have or ep in OPTIONAL:
                print(f"WARNING {ep}: {e}; {'keeping the copy from the last run' if have else 'skipped (optional)'}", flush=True)
                failed.append(ep)
            else:
                sys.exit(f"{ep}: {e}; no earlier copy, aborting so the last good build stays published")
    if failed:
        print(f"Kept earlier data or skipped: {', '.join(failed)}", flush=True)
    if fetched:  # tells the workflow to save a new cache
        open(os.path.join(RAW_DIR, "..", "fetched.flag"), "w").write(",".join(fetched))


REFRESH_MONTHS = 3  # monthly sources: past months do not change, so only the latest few are fetched again


def months_to_fetch(name):
    """All months since DATALAB_FROM, minus those already in raw/<name>.jsonl except the latest REFRESH_MONTHS.
    Returns (months, kept rows)."""
    today = date.today()
    months = [(y, m) for y in range(DATALAB_FROM, today.year + 1) for m in range(1, 13) if (y, m) <= (today.year, today.month)]
    path = os.path.join(RAW_DIR, f"{name}.jsonl")
    if not os.path.exists(path):
        return months, []
    cut = months[-REFRESH_MONTHS] if len(months) >= REFRESH_MONTHS else months[0]
    cut = f"{cut[0]}{cut[1]:02d}"
    kept = [r for r in (json.loads(l) for l in open(path, encoding="utf-8")) if r["ym"] < cut]
    have = {r["ym"] for r in kept}
    return [ym for ym in months if f"{ym[0]}{ym[1]:02d}" not in have], kept


def fetch_datalab(key):
    """One request per calendar month since 2018-01 (about 25,000 daily rows for 기초), summed per month
    into {ym, code, name, kind, n, days, last} so the raw file stays small. Months already fetched are reused."""
    for out, (op, code_f, name_f) in DATALAB.items():
        months, kept = months_to_fetch(out)
        def month(ym):
            y, m = ym
            end = date(y + m // 12, m % 12 + 1, 1).toordinal() - 1
            params = {"serviceKey": key, "pageNo": 1, "numOfRows": 50000, "_type": "json",
                      "MobileOS": "ETC", "MobileApp": "korea-lodging-dashboard",
                      "startYmd": f"{y}{m:02d}01", "endYmd": date.fromordinal(end).strftime("%Y%m%d")}
            return ym, get_body(DATALAB_BASE.format(op), params, f"{out} {y}-{m:02d}")
        with ThreadPoolExecutor(WORKERS) as pool:
            bodies = list(pool.map(month, months))
        n = total = 0
        rows = list(kept)
        for (y, m), body in bodies:
            total += int(body.get("totalCount") or 0)
            agg = {}
            for it in items_of(body):
                k = (it[code_f], it[name_f], it["touDivCd"])
                cur = agg.setdefault(k, [0.0, set()])
                cur[0] += float(it["touNum"])
                cur[1].add(it["baseYmd"])
                n += 1
            rows += [{"ym": f"{y}{m:02d}", "code": code, "name": name, "kind": kind, "n": round(v), "days": len(days), "last": max(days)}
                     for (code, name, kind), (v, days) in agg.items()]
        check(f"{out} ({len(months)} months)", n, total)
        write_rows(out, sorted(rows, key=lambda r: r["ym"]))


def fetch_arrivals(key):
    """방한외래관광객(ED_CD=E) per nationality, one request per month; empty months (not yet published) are skipped.
    Months already fetched are reused."""
    months, kept = months_to_fetch("arrivals")

    def month(ym):
        params = {"serviceKey": key, "_type": "json", "numOfRows": 1000, "pageNo": 1, "YM": f"{ym[0]}{ym[1]:02d}", "ED_CD": "E"}
        return ym, get_body(ARRIVALS, params, f"arrivals {ym[0]}-{ym[1]:02d}")
    with ThreadPoolExecutor(WORKERS) as pool:
        bodies = list(pool.map(month, months))
    total, new = 0, []
    for _, body in bodies:
        total += int(body.get("totalCount") or 0)
        new += [{"ym": str(it["ym"]), "nat": it["natCd"], "name": " ".join(str(it["natKorNm"]).split()), "n": it["num"]} for it in items_of(body)]
    check(f"arrivals ({len(months)} months)", len(new), total)
    write_rows("arrivals", sorted(kept + new, key=lambda r: r["ym"]))


def num(v):
    return int(str(v or 0).replace(",", "") or 0)


def fetch_festivals(key):
    """TourAPI festivals. The service keeps only each festival's latest edition, so earlier editions are carried over
    from the previous raw/festivals.jsonl: one row per festival and year. "cur" marks rows the service still lists."""
    path = os.path.join(RAW_DIR, "festivals.jsonl")
    old = [dict(json.loads(l), cur=False) for l in open(path, encoding="utf-8")] if os.path.exists(path) else []
    params = {"serviceKey": key, "numOfRows": 1000, "_type": "json", "MobileOS": "ETC", "MobileApp": "korea-lodging-dashboard",
              "eventStartDate": FESTIVALS_FROM}
    items, total = [], 1
    while len(items) < total:
        body = get_body(FESTIVALS, dict(params, pageNo=len(items) // 1000 + 1), "festivals")
        total, got = int(body.get("totalCount") or 0), items_of(body)
        if not got:
            break
        items += got
    check("festivals", len(items), total)
    keep = ("contentid", "title", "addr1", "eventstartdate", "eventenddate", "mapx", "mapy", "firstimage", "firstimage2", "tel")
    new = [dict({k: it.get(k) or "" for k in keep}, cur=True) for it in items]
    year = {r["contentid"]: r["eventstartdate"][:4] for r in new}
    # an earlier year of a listed festival stays; the same year again is a correction of its dates
    rows = [r for r in old if r["eventstartdate"][:4] < year.get(r["contentid"], "9999")] + new
    write_rows("festivals", sorted(rows, key=lambda r: (r["eventstartdate"], r["contentid"])))


def fetch_century(key):
    """백년가게: the latest table of the odcloud dataset (업체명, 업체주소, 연락처)."""
    spec = requests.get(CENTURY_SPEC, timeout=60).json()
    path = max(spec["paths"], key=lambda p: spec["paths"][p]["get"].get("summary", "")[-8:])  # titles end with the publication date
    rows, page = [], 1
    while True:
        d = requests.get("https://api.odcloud.kr/api" + path, params={"serviceKey": key, "page": page, "perPage": 1000, "returnType": "JSON"}, timeout=90).json()
        if "data" not in d:
            raise RuntimeError(str(d)[:200])
        rows += d["data"]
        if not d["data"] or len(rows) >= int(d.get("totalCount") or 0):
            break
        page += 1
    print(f"century_shops: {spec['paths'][path]['get'].get('summary')}: {len(rows)} rows", flush=True)
    save_json("century_shops.json", rows)


def fetch_dong_pop(key):
    """Population per 법정동·리 for the latest survey year (국립환경과학원 생활계 인구현황: 주민등록 내국인 + 외국인).
    The service has no year filter and lists every year since 2012 in order, so the last pages are read backwards
    until an older year appears."""
    def page(p, n=1000):
        last = None
        for attempt in range(4):
            try:
                root = ET.fromstring(requests.get(DONG_POP, params={"serviceKey": key, "pageNo": p, "numOfRows": n}, timeout=120).content)
                if root.findtext(".//resultCode") not in ("00", None):
                    raise RuntimeError(root.findtext(".//resultMsg"))
                return int(root.findtext(".//totalCount") or 0), [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(5 + attempt * 5)
        raise RuntimeError(f"dong_pop page {p}: {last}")
    total, _ = page(1, 1)
    rows, latest = [], None
    for p in range(math.ceil(total / 1000), 0, -1):
        _, items = page(p)
        years = {it["year"] for it in items}
        latest = latest or max(years)
        rows += [it for it in items if it["year"] == latest]
        if min(years) < latest:
            break
    out = [{"sido": r.get("citynm", ""), "sgg": r.get("citicoungunm", ""), "emd": r.get("adividoungnm", ""), "ri": r.get("adivininm", ""),
            "pop": int(r.get("popusumcnt") or 0)} for r in rows]
    print(f"dong_pop: {latest}, {len(out)} 법정동·리, population {sum(r['pop'] for r in out):,}", flush=True)
    save_json("dong_pop.json", {"year": latest, "rows": out})


def fetch_food_coords(key):
    """Positions of 모범음식점 (designated, open) and 백년가게 from the 일반음식점 인허가 API, whose records carry
    coordinates: 모범음식점 by searching the same 지자체 for the name and taking the record with the same 관리번호;
    백년가게 (no 관리번호) by name, keeping a record whose road address has the shop's street and number.
    Cached in raw/food_coords.json ({key: [CRD_INFO_X, CRD_INFO_Y] or null}); a few thousand lookups per run."""
    path = os.path.join(RAW_DIR, "food_coords.json")
    cache = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    todo = []  # 백년가게 first: fewer, and shown from the national view
    cen = os.path.join(RAW_DIR, "century_shops.json")
    for r in json.load(open(cen, encoding="utf-8")) if os.path.exists(cen) else []:
        k, addr = f"cen:{r.get('업체명')}|{r.get('업체주소')}", r.get("업체주소") or ""
        street = re.search(r"(\S+(?:로|길)\S*\s+\d+(?:-\d+)?)", addr)  # e.g. 덕진연못3길 6
        if k not in cache and street:
            todo.append((k, {"cond[BPLC_NM::LIKE]": r.get("업체명")}, None, street.group(1).replace(" ", "")))
    ex = os.path.join(RAW_DIR, "excellent_restaurant_info.jsonl")
    for line in open(ex, encoding="utf-8") if os.path.exists(ex) else []:
        r = json.loads(line)
        if not r.get("DSGN_RTRCN_YMD") and r.get("SALS_STTS_NM") == "영업" and f"ex:{r['MNG_NO']}" not in cache:
            todo.append((f"ex:{r['MNG_NO']}", {"cond[OPN_ATMY_GRP_CD::EQ]": r["OPN_ATMY_GRP_CD"], "cond[BPLC_NM::LIKE]": r["BSNSSP_NM"]}, r["MNG_NO"], None))
    todo = todo[:FOOD_MATCH_BUDGET]
    deadline, spent = time.time() + FOOD_MATCH_MINUTES * 60, []

    def one(t):
        k, cond, mng, street = t
        if spent or time.time() > deadline:
            return k, "retry"
        params = {"serviceKey": key, "pageNo": 1, "numOfRows": 100, "returnType": "json", **cond}
        for attempt in range(4):
            try:
                d = requests.get(BASE.format("general_restaurants"), params=params, timeout=60).json()
                if "SERVICETIMEOUT" in str(d)[:300]:  # a passing gateway timeout: try again
                    raise ValueError("service timeout")
                break
            except (requests.RequestException, ValueError):
                time.sleep(3 + attempt * 3)
        else:
            return k, "retry"
        if "response" not in d:  # e.g. the daily limit or a key the service has not approved yet: stop this run
            spent.append(json.dumps(d, ensure_ascii=False)[:200])
            return k, "retry"
        for it in items_of(d["response"]["body"]):
            same = it.get("MNG_NO") == mng if mng else street in (it.get("ROAD_NM_ADDR") or "").replace(" ", "")
            if same and it.get("CRD_INFO_X") and it.get("CRD_INFO_Y"):
                return k, [it["CRD_INFO_X"], it["CRD_INFO_Y"]]
        return k, None
    got = []
    try:
        with ThreadPoolExecutor(6) as pool:
            got = list(pool.map(one, todo))
    finally:
        cache.update({k: v for k, v in got if v != "retry"})
        print(f"food_coords: {len(todo)} looked up, {sum(1 for _, v in got if v and v != 'retry')} placed, "
              f"{sum(1 for _, v in got if v is None)} not found, {sum(1 for _, v in got if v == 'retry')} left for the next run; "
              f"{len(cache)} cached{'; stopped: ' + spent[0] if spent else ''}", flush=True)
        save_json("food_coords.json", cache)
    if todo and not any(v != "retry" for _, v in got):
        raise RuntimeError(f"no lookup succeeded: {spent[0] if spent else 'network'}")


def fetch_icn(key):
    """인천공항 passengers per country of the route, one request per month (from_month = to_month).
    Months not published yet come back empty or as an error and are skipped. Months already fetched are reused."""
    months, kept = months_to_fetch("icn")

    def month(ym):
        y, m = ym
        params = {"serviceKey": key, "from_month": f"{y}{m:02d}", "to_month": f"{y}{m:02d}", "type": "json"}
        for attempt in range(4):  # retry network errors only; an answer without data means the month is not out yet
            try:
                d = requests.get(ICN, params=params, timeout=90).json()
                return ym, items_of(d["response"]["body"]) if d.get("response", {}).get("header", {}).get("resultCode") == "00" else None
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(3 + attempt * 3)
        print(f"  icn {y}-{m:02d}: {last}", flush=True)
        return ym, None
    with ThreadPoolExecutor(WORKERS) as pool:
        got = list(pool.map(month, months))
    if months and all(items is None for _, items in got):
        raise RuntimeError("every month failed")
    new = [{"ym": f"{y}{m:02d}", "region": it["region"], "country": it["country"], "arr": num(it.get("arrPassenger")), "dep": num(it.get("depPassenger"))}
           for (y, m), items in got for it in items or [] if num(it.get("arrPassenger")) or num(it.get("depPassenger"))]
    print(f"icn: {len(months)} months requested, {len({r['ym'] for r in new})} with data, {len(new)} rows", flush=True)
    write_rows("icn", sorted(kept + new, key=lambda r: r["ym"]))


def fetch_korail_wide(key):
    """코레일 광역철도 boardings / alightings per station and month (the whole table, a few thousand rows;
    the service asks for at most 50 rows per page)."""
    def page(p):
        return get_body(KORAIL_WIDE, {"serviceKey": key, "pageNo": p, "numOfRows": 50, "returnType": "json"}, f"korail_wide page {p}")
    first = page(1)
    total, size = int(first.get("totalCount") or 0), max(1, len(items_of(first)))
    with ThreadPoolExecutor(WORKERS) as pool:
        rest = list(pool.map(page, range(2, math.ceil(total / size) + 1)))
    rows = [{"ym": it["run_ym"], "cd": it["stn_cd"], "name": it["stn_nm"], "ride": num(it["ride_nope"]), "goff": num(it["goff_nope"])}
            for body in [first] + rest for it in items_of(body)]
    check("korail_wide", len(rows), total)
    if not rows:
        raise RuntimeError("no rows returned")
    save_json("korail_wide.json", rows)


def fetch_korail_main(key):
    """코레일 간선열차 boardings / alightings per station and day (KTX, ITX, 무궁화 ...), summed per month.
    The service keeps about a year; months since 2025 are asked for, the latest REFRESH_MONTHS again each run."""
    today = date.today()
    months = [(y, m) for y in range(2025, today.year + 1) for m in range(1, 13) if (y, m) <= (today.year, today.month)]
    path, cut = os.path.join(RAW_DIR, "korail_main.jsonl"), "%d%02d" % months[-REFRESH_MONTHS]
    kept = [r for r in (json.loads(l) for l in open(path, encoding="utf-8"))] if os.path.exists(path) else []
    kept = [r for r in kept if r["ym"] < cut]
    have = {r["ym"] for r in kept}

    def month(ym):
        y, m = ym
        last = date(y + m // 12, m % 12 + 1, 1).toordinal() - 1
        cond = {"cond[opr_ymd::GTE]": f"{y}{m:02d}01", "cond[opr_ymd::LTE]": date.fromordinal(last).strftime("%Y%m%d")}
        page = lambda p: get_body(KORAIL_MAIN, {"serviceKey": key, "pageNo": p, "numOfRows": 1000, "returnType": "json", **cond}, f"korail_main {y}-{m:02d} page {p}")
        first = page(1)
        total, size = int(first.get("totalCount") or 0), max(1, len(items_of(first)))
        items = items_of(first) + [it for p in range(2, math.ceil(total / size) + 1) for it in items_of(page(p))]
        agg = {}
        for it in items:
            a = agg.setdefault((it["stn_cd"], it["stn_nm"]), [0, 0, set()])
            a[0] += num(it["ride_nope"]); a[1] += num(it["goff_nope"]); a[2].add(it["opr_ymd"])
        return [{"ym": f"{y}{m:02d}", "cd": cd, "name": nm, "ride": a[0], "goff": a[1], "days": len(a[2])} for (cd, nm), a in agg.items()], total, len(items)
    todo = [ym for ym in months if "%d%02d" % ym not in have]
    with ThreadPoolExecutor(3) as pool:
        got = list(pool.map(month, todo))
    rows = kept + [r for g in got for r in g[0]]
    check(f"korail_main ({len(todo)} months)", sum(g[2] for g in got), sum(g[1] for g in got))
    if not rows:
        raise RuntimeError("no rows returned")
    write_rows("korail_main", sorted(rows, key=lambda r: r["ym"]))


def fetch_metro_std(_key):
    """전국도시철도역사정보표준데이터: the file behind the dataset page (hidden form fields name it), CSV in UTF-8 or CP949."""
    ua = {"User-Agent": "Mozilla/5.0"}
    t = requests.get(METRO_STD, headers=ua, timeout=60).text
    def hidden(name):
        m = re.search(r'id="%s"[^>]*value="([^"]*)"' % name, t) or re.search(r'value="([^"]*)"[^>]*id="%s"' % name, t)
        return m.group(1) if m else None
    atch, sn = hidden("limitAtchFileId"), hidden("limitFileDetailSn")
    if not atch:
        raise RuntimeError("file id not found: " + " | ".join(re.findall(r".{0,80}limitAtchFileId.{0,120}", t)[:3]))
    r = requests.get("https://www.data.go.kr/cmm/cmm/fileDownload.do", params={"atchFileId": atch, "fileDetailSn": sn or "1"}, headers=ua, timeout=120)
    raw = r.content
    if raw[:2] == b"PK" or b"<html" in raw[:500].lower():
        raise RuntimeError(f"not a CSV file (HTTP {r.status_code}, {r.headers.get('content-type')}, {raw[:80]!r})")
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    rows = list(csv.DictReader(io.StringIO(text)))
    print(f"metro_std: {len(rows)} rows; columns {list(rows[0]) if rows else []}; first {rows[:1]}", flush=True)
    if not rows:
        raise RuntimeError("empty file")
    save_json("metro_std.json", rows)


def fetch_kto_index(key, spec=KTO_INDEX, name="kto_index"):
    """관광 수요 강도 / 관광 다양성 (or, with KTO_RES, 관광 자원 수요) indicators per 시도 (with its 시군구) and month, latest 13 months, newest first.
    One request per (month, indicator, 시도). Months already fetched are reused except the latest REFRESH_MONTHS;
    an empty answer is remembered too, so it is not asked again until it falls in the refresh window."""
    today = date.today()
    months = ["%d%02d" % (today.year - (today.month - k <= 0), (today.month - k - 1) % 12 + 1) for k in range(13)]
    path, cut = os.path.join(RAW_DIR, f"{name}.jsonl"), months[REFRESH_MONTHS - 1]
    kept = [json.loads(l) for l in open(path, encoding="utf-8")] if os.path.exists(path) else []
    kept = [r for r in kept if months[-1] <= r["ym"] < cut]
    have = {(r["ym"], r["ix"], r["area"]) for r in kept}
    todo, used = [], defaultdict(int)
    for ym in months:
        for op, param, codes in spec:
            svc = op.split("/")[0]
            for ix in codes:
                for area in KTO_INDEX_AREAS:
                    if (ym, ix, area) not in have and used[svc] < KTO_INDEX_BUDGET:
                        used[svc] += 1
                        todo.append((ym, op, param, ix, area))
    fields = ("tarSjrnDsIx", "tarExpDsIx", "touDivIx", "expDivIx", "intlDivIx", "tarSvcDemIx", "culResDemIx")
    spent = set()  # services that answered "daily request limit exceeded": the rest of their requests wait for tomorrow

    def one(t):
        ym, op, param, ix, area = t
        if op.split("/")[0] in spent:
            return None
        params = {"serviceKey": key, "pageNo": 1, "numOfRows": 100, "MobileOS": "ETC", "MobileApp": "korea-lodging-dashboard",
                  "_type": "json", "baseYm": ym, "areaCd": area, param: ix}
        last = None
        for attempt in range(3):
            try:
                d = requests.get("https://apis.data.go.kr/B551011/" + op, params=params, timeout=60).json()
                if "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in str(d):
                    spent.add(op.split("/")[0])
                    print(f"  {name}: {op.split('/')[0]} daily limit reached, stopping it for this run", flush=True)
                    return None
                if d.get("response", {}).get("header", {}).get("resultCode") != "0000":
                    raise RuntimeError(str(d)[:200])
                items = items_of(d["response"]["body"])
                f = next((f for f in fields if items and f + "Val" in items[0]), None)
                return [{"ym": ym, "ix": ix, "area": area, "sido": it["areaNm"], "sgg": "" if str(it["signguCd"]) == "0" else it["signguNm"],
                         "name": it.get(f + "Nm", ""), "v": float(it[f + "Val"])} for it in items] or [{"ym": ym, "ix": ix, "area": area, "empty": 1}]
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(3 + attempt * 3)
        print(f"  {name} {ym} {ix} {area}: {last}", flush=True)
        return None
    with ThreadPoolExecutor(4) as pool:
        got = list(pool.map(one, todo))
    failed = sum(g is None for g in got)
    rows = kept + [r for g in got if g for r in g]
    total = len(months) * sum(len(c) for _, _, c in spec) * len(KTO_INDEX_AREAS)
    print(f"{name}: {len(todo)} requests {dict(used)}, {failed} failed, {sum(1 for r in rows if not r.get('empty'))} values; "
          f"{total - len({(r['ym'], r['ix'], r['area']) for r in rows})} of {total} (month, indicator, 시도) still to fetch", flush=True)
    if todo and failed == len(todo):
        raise RuntimeError("every request failed")
    write_rows(name, sorted(rows, key=lambda r: (r["ym"], r["ix"], r["area"])))


def fetch_population(key):
    """주민등록인구 of the latest published month: 시도 (lv 1) and the 시군구 of each 시도 (lv 2, admmCd = the 시도 code)."""
    def call(admm, ym, lv, page=1):
        params = {"serviceKey": key, "admmCd": admm, "srchFrYm": ym, "srchToYm": ym, "lv": lv, "regSeCd": 1,
                  "type": "JSON", "numOfRows": 100, "pageNo": page}
        d = requests.get(POPULATION, params=params, timeout=60).json()["Response"]
        if d["head"]["resultCode"] != "0":
            raise RuntimeError(f"{admm} {ym} lv{lv}: {d['head']}")
        items = (d.get("items") or {}).get("item") or []
        return ([items] if isinstance(items, dict) else items), int(d["head"]["totalCount"])
    today = date.today()
    for k in range(1, 4):  # published after the month ends
        ym = "%d%02d" % (today.year - (today.month - k <= 0), (today.month - k - 1) % 12 + 1)
        sido, _ = call("1100000000", ym, 1)
        if sido:
            break
    else:
        raise RuntimeError("no month in the last three has data")
    sgg = []
    for r in sido:
        page = 1
        while True:
            items, total = call(r["admmCd"], ym, 2, page)
            sgg += items
            if len(items) < 100 or page * 100 >= total:
                break
            page += 1
    keep = lambda r: {"code": r["admmCd"], "sido": r["ctpvNm"], "sgg": r["sggNm"], "pop": int(r["totNmprCnt"])}
    print(f"population: {ym}, {len(sido)} 시도, {len(sgg)} 시군구 rows", flush=True)
    save_json("pop_month.json", {"ym": ym, "sido": [keep(r) for r in sido], "sgg": [keep(r) for r in sgg]})


def fetch_kac(key):
    """한국공항공사 공항별 여객실적: the odcloud dataset holds one table per publication (one year each).
    Tables with the current columns (공항, 노선, 연도, 여객성인도착 ...) are kept; older layouts are skipped."""
    spec = requests.get(KAC_SPEC, timeout=60).json()
    tables = []
    for path, v in spec["paths"].items():
        title, rows, p = v["get"].get("summary", ""), [], 1
        while True:
            r = requests.get("https://api.odcloud.kr/api" + path, params={"serviceKey": key, "page": p, "perPage": 1000, "returnType": "JSON"}, timeout=90)
            d = r.json()
            if "data" not in d:
                raise RuntimeError(f"{title}: HTTP {r.status_code}: {str(d)[:200]}")
            rows += d["data"]
            if not d["data"] or len(rows) >= int(d.get("totalCount") or 0):
                break
            p += 1
        ok = bool(rows) and {"공항", "노선", "연도", "여객성인도착", "여객성인출발"} <= set(rows[0])
        print(f"kac: {title}: {len(rows)} rows, {'kept' if ok else 'skipped, columns ' + str(list(rows[0]) if rows else [])}", flush=True)
        if ok:
            tables.append({"title": title, "rows": rows})
    if not tables:
        raise RuntimeError("no table with the expected columns")
    save_json("kac_years.json", tables)


if __name__ == "__main__":
    main()
