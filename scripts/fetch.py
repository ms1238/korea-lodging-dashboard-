"""Download every record from the 8 MOIS permit APIs into raw/<endpoint>.jsonl,
plus tourist attractions from the Korea Tourism Organization TourAPI (KorService2) into raw/tour_<type>.jsonl,
plus visitor counts from the KTO DataLabService (daily since 2018, summed per month) into raw/datalab_sido.jsonl / datalab_sgg.jsonl,
plus monthly foreign arrivals by nationality (한국문화관광연구원 출입국관광통계, since 2018) into raw/arrivals.jsonl.

Endpoint pattern: https://apis.data.go.kr/1741000/<endpoint>/info
The service key is read from the DATA_GO_KR_KEY environment variable (a GitHub Actions secret);
it must never be written into the repository.
"""
import json
import math
import os
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


def main():
    """Fetch every source. If one fails (e.g. the daily request quota is used up) and a copy from an earlier run
    is present in raw/ (restored from the Actions cache), keep that copy and go on; otherwise stop."""
    key = os.environ.get("DATA_GO_KR_KEY")
    if not key:
        sys.exit("DATA_GO_KR_KEY is not set")
    os.makedirs(RAW_DIR, exist_ok=True)
    failed = []
    for ep in sys.argv[1:] or ENDPOINTS + [f"tour_{c}" for c in TOUR_TYPES] + ["datalab", "arrivals"]:
        files = list(DATALAB) if ep == "datalab" else [ep]
        try:
            fetch_datalab(key) if ep == "datalab" else fetch_arrivals(key) if ep == "arrivals" else fetch_permits(key, ep)
        except Exception as e:  # noqa: BLE001
            if all(os.path.exists(os.path.join(RAW_DIR, f"{f}.jsonl")) for f in files):
                print(f"WARNING {ep}: {e}; keeping the copy from the last run", flush=True)
                failed.append(ep)
            else:
                sys.exit(f"{ep}: {e}; no earlier copy, aborting so the last good build stays published")
    if failed:
        print(f"Kept earlier data for: {', '.join(failed)}", flush=True)


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


if __name__ == "__main__":
    main()
