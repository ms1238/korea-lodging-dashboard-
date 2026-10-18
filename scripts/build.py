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
9. Visitors (KTO DataLab): 외지인 and 외국인 visitor counts over the latest 365 days, per 시도 and 시군구.
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
    """Annual 외지인(2) and 외국인(3) visitors per 시도 and 시군구 as [외지인, 외국인] in sido_meta[i]["vis"] / ["visg"].

    Uses the latest 365 days. Areas reported for fewer days (e.g. 인천 구 created in 2026) are scaled up to a year
    and listed under "partial". Old 광주광역시/전라남도 rows count toward 전남광주통합특별시."""
    def read(name):
        path = os.path.join(RAW, f"{name}.jsonl")
        return [json.loads(l) for l in open(path, encoding="utf-8")] if os.path.exists(path) else []
    sido_rows, sgg_rows = read("datalab_sido"), read("datalab_sgg")
    if not sido_rows:
        return None
    last = max(r["ymd"] for r in sido_rows)
    first = (datetime.strptime(last, "%Y%m%d") - timedelta(days=364)).strftime("%Y%m%d")

    def norm(name):
        if name in ("광주광역시", "전라남도") and MERGED_GWANGJU_JEONNAM in sidos:
            return MERGED_GWANGJU_JEONNAM
        return SIDO_ALIASES.get(name, name)
    code_sido = {r["code"]: norm(r["name"]) for r in sido_rows}
    sums, days, unmatched = defaultdict(lambda: [0.0, 0.0]), defaultdict(set), set()

    def add(key, r):
        sums[key][int(r["kind"]) - 2] += float(r["n"])
        days[key].add(r["ymd"])
    for r in sido_rows:
        if first <= r["ymd"] <= last and r["kind"] in ("2", "3"):
            sido = norm(r["name"])
            add((sido, None), r) if sido in sidos else unmatched.add(r["name"])
    for r in sgg_rows:
        # 구 of a 시 (e.g. "수원시 장안구") are also reported at 시 level; keep the 시 row only
        if not (first <= r["ymd"] <= last and r["kind"] in ("2", "3")) or " " in r["name"]:
            continue
        sido = code_sido.get(r["code"][:2])
        name = sido if r["name"] == sido else r["name"]  # 세종 reports itself as its only 시군구
        if sido in sidos and name in sgg_of[sido]:
            add((sido, name), r)
        else:
            unmatched.add(f"{sido} {r['name']}")
    full = len({r["ymd"] for r in sido_rows if first <= r["ymd"] <= last})
    partial = []

    def year(key):
        if key not in sums:
            return None
        n = len(days[key])
        if n < full * 0.95:
            partial.append(" ".join(k for k in key if k))
        return [round(v * full / n) for v in sums[key]]
    for s, sm in zip(sidos, sido_meta):
        sm["vis"] = year((s, None))
        sm["visg"] = [year((s, g)) for g in sm["sgg"]]
    return {"from": first, "to": last, "partial": partial, "unmatched": sorted(unmatched)}


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
    with open(os.path.join(OUT, "close.json"), "w", encoding="utf-8") as f:
        json.dump([[*k, v] for k, v in sorted(close.items())], f, separators=(",", ":"))
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
    visitors = add_visitors(sidos, sgg_of, sido_meta)
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
