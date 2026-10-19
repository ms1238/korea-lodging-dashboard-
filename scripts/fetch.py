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
import json
import math
import os
import re
import sys
import time
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
DATALAB_BASE = "https://apis.data.go.kr/B551011/DataLabService/{}"
# output file -> (operation, region code field, region name field); 광역 and 기초 visitor counts per day
DATALAB_FROM = 2018  # first year the service has data for
ARRIVALS = "https://apis.data.go.kr/B551940/EdrcntTourismStatsService/getEdrcntTourismStatsList"
ICN = "https://apis.data.go.kr/B551177/AviationStatsByCountry/getTotalNumberOfPassenger"  # 인천공항 국가별 여객
KORAIL_WIDE = "https://apis.data.go.kr/B551457/issueStatistics/wideRailloadStationPer"  # 코레일 광역철도 역별 승하차
KAC_SPEC = "https://infuser.odcloud.kr/oas/docs?namespace=15002610/v1"  # 한국공항공사 공항별 여객실적 (odcloud)
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
# a bounding box of South Korea instead of an area lookup: some mirrors have no area index and answer 500
SUBWAY_QUERY = """[out:json][timeout:240];
relation["route"~"^(subway|light_rail)$"](33.0,124.5,38.7,131.0);
out geom;"""
PARKS_QUERY = """[out:json][timeout:240];
(relation["boundary"="national_park"](33.0,124.5,38.7,131.0);
 relation["boundary"="protected_area"]["protect_class"="2"](33.0,124.5,38.7,131.0);
 way["boundary"="national_park"](33.0,124.5,38.7,131.0););
out geom;"""
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
OPTIONAL = {"subway", "parks_osm", "stations", "rail_stations", "icn", "korail_wide", "kac_years"}  # the page works without these, so a failed first fetch does not stop the deploy
JSON_FILES = {"subway", "parks_osm", "stations", "rail_stations", "korail_wide", "kac_years"}  # raw/<name>.json; the others are .jsonl
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


def fetch_parks_osm(_key):
    """National-park boundaries: relations (outer/inner member ways) and closed ways, with name tags."""
    out = []
    for el in overpass(PARKS_QUERY):
        tags = el.get("tags", {})
        name = tags.get("name:ko") or tags.get("name") or ""
        if el["type"] == "way" and el.get("geometry"):
            ways = [["outer", [[round(p["lon"], 5), round(p["lat"], 5)] for p in el["geometry"]]]]
        else:
            ways = [[m.get("role") or "outer", [[round(p["lon"], 5), round(p["lat"], 5)] for p in m["geometry"]]]
                    for m in el.get("members", []) if m.get("type") == "way" and m.get("geometry")]
        out.append({"id": f"{el['type']}/{el['id']}", "name": name, "ways": ways})
    print(f"parks_osm: {len(out)} boundaries ({sum('국립공원' in p['name'] for p in out)} named …국립공원)", flush=True)
    if not out:
        raise RuntimeError("no boundaries returned")
    save_json("parks_osm.json", out)


def fetch_stations(_key, query=STATIONS_QUERY, name="stations"):
    """Station points (node, or the centre of a way/relation) with their Korean name."""
    out = []
    for el in overpass(query):
        tags, c = el.get("tags", {}), el.get("center") or el
        name = tags.get("name:ko") or tags.get("name") or ""
        if name and "lat" in c:
            out.append({"id": f"{el['type']}/{el['id']}", "name": name, "lat": round(c["lat"], 5), "lon": round(c["lon"], 5)})
    print(f"{name}: {len(out)} stations", flush=True)
    if not out:
        raise RuntimeError("no stations returned")
    save_json(f"{name}.json", out)


def fetch_subway(_key):
    """Route relations with member way geometry; kept small: name/ref/colour/network and rounded coordinates."""
    rels = overpass(SUBWAY_QUERY)
    out = [{"id": rel["id"], **{k: rel.get("tags", {}).get(k, "") for k in ("route", "name", "ref", "colour", "network")},
            "ways": [[m["ref"], [[round(p["lon"], 5), round(p["lat"], 5)] for p in m["geometry"]]]
                     for m in rel.get("members", []) if m.get("type") == "way" and m.get("geometry")]}
           for rel in rels]
    print(f"subway: {len(out)} routes, {sum(len(r['ways']) for r in out)} ways", flush=True)
    if not out:
        raise RuntimeError("no routes returned")
    save_json("subway.json", out)


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
    for ep in args or ENDPOINTS + [f"tour_{c}" for c in TOUR_TYPES] + ["datalab", "arrivals", "subway", "parks_osm", "stations", "rail_stations", "icn", "korail_wide", "kac_years"]:
        files = [f"{f}.jsonl" for f in DATALAB] if ep == "datalab" else [f"{ep}.json"] if ep in JSON_FILES else [f"{ep}.jsonl"]
        have = all(os.path.exists(os.path.join(RAW_DIR, f)) for f in files)
        if only_missing and have:
            continue
        try:
            {"datalab": fetch_datalab, "arrivals": fetch_arrivals, "subway": fetch_subway,
             "parks_osm": fetch_parks_osm, "stations": fetch_stations,
             "rail_stations": lambda k: fetch_stations(k, RAIL_STATIONS_QUERY, "rail_stations"), "icn": fetch_icn, "korail_wide": fetch_korail_wide,
             "kac_years": fetch_kac}.get(ep, lambda k: fetch_permits(k, ep))(key)
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
