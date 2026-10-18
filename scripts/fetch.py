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


def main():
    key = os.environ.get("DATA_GO_KR_KEY")
    if not key:
        sys.exit("DATA_GO_KR_KEY is not set")
    os.makedirs(RAW_DIR, exist_ok=True)
    for ep in sys.argv[1:] or ENDPOINTS + [f"tour_{c}" for c in TOUR_TYPES] + ["datalab", "arrivals"]:
        if ep == "datalab":
            fetch_datalab(key)
            continue
        if ep == "arrivals":
            fetch_arrivals(key)
            continue
        first = get_page(key, ep, 1)
        total = int(first.get("totalCount") or 0)
        size = max(1, len(items_of(first)) or int(first.get("numOfRows") or PAGE_SIZE))
        pages = max(1, math.ceil(total / size))
        with ThreadPoolExecutor(WORKERS) as pool:
            rest = list(pool.map(lambda p: get_page(key, ep, p), range(2, pages + 1)))
        n = 0
        with open(os.path.join(RAW_DIR, f"{ep}.jsonl"), "w", encoding="utf-8") as f:
            for body in [first] + rest:
                for item in items_of(body):
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
                    n += 1
        print(f"{ep}: total {total}, fetched {n}", flush=True)
        if n < total * 0.98:
            sys.exit(f"{ep}: fetched {n} of {total}; aborting so the last good build stays published")


def fetch_datalab(key):
    """One request per calendar month since 2018-01 (about 25,000 daily rows for 기초), summed per month
    into {ym, code, name, kind, n, days, last} so the raw file stays small."""
    today = date.today()
    months = [(y, m) for y in range(DATALAB_FROM, today.year + 1) for m in range(1, 13) if (y, m) <= (today.year, today.month)]
    for out, (op, code_f, name_f) in DATALAB.items():
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
        with open(os.path.join(RAW_DIR, f"{out}.jsonl"), "w", encoding="utf-8") as f:
            for (y, m), body in bodies:
                total += int(body.get("totalCount") or 0)
                agg = {}
                for it in items_of(body):
                    k = (it[code_f], it[name_f], it["touDivCd"])
                    cur = agg.setdefault(k, [0.0, set()])
                    cur[0] += float(it["touNum"])
                    cur[1].add(it["baseYmd"])
                    n += 1
                for (code, name, kind), (v, days) in agg.items():
                    f.write(json.dumps({"ym": f"{y}{m:02d}", "code": code, "name": name, "kind": kind,
                                        "n": round(v), "days": len(days), "last": max(days)}, ensure_ascii=False) + "\n")
        print(f"{out}: total {total}, fetched {n}", flush=True)
        if n < total * 0.98:
            sys.exit(f"{out}: fetched {n} of {total}; aborting so the last good build stays published")


def fetch_arrivals(key):
    """방한외래관광객(ED_CD=E) per nationality, one request per month; empty months (not yet published) are skipped."""
    today = date.today()
    months = [(y, m) for y in range(DATALAB_FROM, today.year + 1) for m in range(1, 13) if (y, m) <= (today.year, today.month)]

    def month(ym):
        params = {"serviceKey": key, "_type": "json", "numOfRows": 1000, "pageNo": 1, "YM": f"{ym[0]}{ym[1]:02d}", "ED_CD": "E"}
        return ym, get_body(ARRIVALS, params, f"arrivals {ym[0]}-{ym[1]:02d}")
    with ThreadPoolExecutor(WORKERS) as pool:
        bodies = list(pool.map(month, months))
    n = total = 0
    with open(os.path.join(RAW_DIR, "arrivals.jsonl"), "w", encoding="utf-8") as f:
        for _, body in bodies:
            total += int(body.get("totalCount") or 0)
            for it in items_of(body):
                f.write(json.dumps({"ym": str(it["ym"]), "nat": it["natCd"], "name": " ".join(str(it["natKorNm"]).split()),
                                    "n": it["num"]}, ensure_ascii=False) + "\n")
                n += 1
    print(f"arrivals: total {total}, fetched {n}", flush=True)
    if n < total * 0.98:
        sys.exit(f"arrivals: fetched {n} of {total}; aborting so the last good build stays published")


if __name__ == "__main__":
    main()
