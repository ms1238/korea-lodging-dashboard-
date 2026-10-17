"""Download every record from the 8 MOIS permit APIs into raw/<endpoint>.jsonl.

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
PAGE_SIZE = 100  # the API caps numOfRows at 100 regardless of what is requested
WORKERS = 6
RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "raw")


def get_page(key, endpoint, page):
    last = None
    for attempt in range(8):
        try:
            r = requests.get(
                BASE.format(endpoint),
                params={"serviceKey": key, "pageNo": page, "numOfRows": PAGE_SIZE, "returnType": "json"},
                timeout=90,
            )
            data = r.json()
            if "response" not in data:
                # e.g. {"OpenAPI_ServiceResponse": {"cmmMsgHeader": {"errMsg": ...}}}
                raise RuntimeError(f"API error: {json.dumps(data, ensure_ascii=False)[:300]}")
            return data["response"]["body"]
        except Exception as e:  # network resets are common; back off and retry
            last = e
            time.sleep(3 + attempt * 3)
    raise RuntimeError(f"{endpoint} page {page} failed: {last}")


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
    for ep in sys.argv[1:] or ENDPOINTS:
        first = get_page(key, ep, 1)
        total = int(first.get("totalCount") or 0)
        size = int(first.get("numOfRows") or PAGE_SIZE)
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


if __name__ == "__main__":
    main()
