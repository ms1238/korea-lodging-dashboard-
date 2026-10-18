"""Download every record from the 8 MOIS permit APIs into raw/<endpoint>.jsonl,
plus tourist attractions from the Korea Tourism Organization TourAPI (KorService2) into raw/tour_<type>.jsonl,
plus daily visitor counts from the KTO DataLabService (last 14 calendar months) into raw/datalab_sido.jsonl / datalab_sgg.jsonl.

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
    for ep in sys.argv[1:] or ENDPOINTS + [f"tour_{c}" for c in TOUR_TYPES] + ["datalab"]:
        if ep == "datalab":
            fetch_datalab(key)
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
    """One request per calendar month (about 25,000 rows for 기초), covering the last 14 calendar months."""
    today = date.today()
    months = [(today.year, today.month - i) for i in range(13, -1, -1)]
    months = [(y + (m - 1) // 12, (m - 1) % 12 + 1) for y, m in months]
    for out, (op, code_f, name_f) in DATALAB.items():
        n = total = 0
        with open(os.path.join(RAW_DIR, f"{out}.jsonl"), "w", encoding="utf-8") as f:
            for y, m in months:
                end = date(y + m // 12, m % 12 + 1, 1).toordinal() - 1
                params = {"serviceKey": key, "pageNo": 1, "numOfRows": 50000, "_type": "json",
                          "MobileOS": "ETC", "MobileApp": "korea-lodging-dashboard",
                          "startYmd": f"{y}{m:02d}01", "endYmd": date.fromordinal(end).strftime("%Y%m%d")}
                body = get_body(DATALAB_BASE.format(op), params, f"{out} {y}-{m:02d}")
                total += int(body.get("totalCount") or 0)
                for it in items_of(body):
                    f.write(json.dumps({"ymd": it["baseYmd"], "code": it[code_f], "name": it[name_f],
                                        "kind": it["touDivCd"], "n": it["touNum"]}, ensure_ascii=False) + "\n")
                    n += 1
        print(f"{out}: total {total}, fetched {n}", flush=True)
        if n < total * 0.98:
            sys.exit(f"{out}: fetched {n} of {total}; aborting so the last good build stays published")


if __name__ == "__main__":
    main()
