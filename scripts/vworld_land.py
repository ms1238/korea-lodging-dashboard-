"""Run on a PC in Korea (VWorld refuses connections from abroad, so not in GitHub Actions):
adds 개별공시지가 and 용도지역 from the VWorld 2D data API to every open 여관·여인숙 with an exact position.

    python vworld_land.py

It asks for the VWorld key (not stored anywhere), downloads the dashboard's facility list, and writes
vworld_land.csv.gz next to itself; upload that file to scripts/static/ of the repository. Stopping and
running it again continues where it left off (vworld_land.partial.jsonl). Standard library only.
"""
import csv
import getpass
import gzip
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

LIST = "https://ms1238.github.io/korea-lodging-dashboard-/data/download/lodging.csv.gz"
API = "https://api.vworld.kr/req/data"
DOMAIN = "https://ms1238.github.io/korea-lodging-dashboard-/"
LAYERS = {"cbnd": "LP_PA_CBND_BUBUN", "zone": "LT_C_UQ111"}  # 연속지적도(공시지가), 용도지역(도시지역)
TYPES = ("여관업", "여인숙업")
HERE = os.path.dirname(os.path.abspath(__file__))
PART, OUT = os.path.join(HERE, "vworld_land.partial.jsonl"), os.path.join(HERE, "vworld_land.csv.gz")


class Stop(Exception):
    pass


def ask(key, layer, lon, lat):
    """Attributes of the feature of `layer` under the point, {} if none; Stop on a key or quota error."""
    q = {"service": "data", "request": "GetFeature", "data": layer, "key": key, "format": "json", "size": 1,
         "geomFilter": f"POINT({lon} {lat})", "crs": "EPSG:4326", "geometry": "false", "domain": DOMAIN}
    for attempt in range(4):
        try:
            with urllib.request.urlopen(API + "?" + urllib.parse.urlencode(q), timeout=30) as r:
                res = json.load(r)["response"]
            break
        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                raise Stop(f"연결 실패: {e}")
            time.sleep(3 * (attempt + 1))
    if res.get("status") == "NOT_FOUND":
        return {}
    if res.get("status") != "OK":
        raise Stop(f"VWorld 오류: {json.dumps(res.get('error', res), ensure_ascii=False)[:300]}")
    feats = res["result"]["featureCollection"]["features"]
    return feats[0]["properties"] if feats else {}


def main():
    print("시설 목록을 받는 중…", flush=True)
    with urllib.request.urlopen(LIST, timeout=120) as r:
        rows = list(csv.DictReader(io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(r.read())), encoding="utf-8-sig")))
    todo = [r for r in rows if r["업종"] in TYPES and r["영업상태"] in ("영업", "휴업") and r["위도"] and r["위치근사"] == "0"]
    done = {}
    if os.path.exists(PART):
        for line in open(PART, encoding="utf-8"):
            x = json.loads(line)
            done[x["id"]] = x
    todo = [r for r in todo if r["관리번호"] not in done]
    print(f"대상 {len(todo) + len(done):,}곳, 받은 곳 {len(done):,}곳, 남은 곳 {len(todo):,}곳", flush=True)
    if not todo:
        return write(done)
    key = os.environ.get("VWORLD_KEY") or getpass.getpass("VWorld 인증키를 붙여넣고 Enter (화면에 안 보입니다): ").strip()
    first = todo[0]
    try:  # one call first, so a wrong key or blocked access stops right away with the reason
        sample = ask(key, LAYERS["cbnd"], first["경도"], first["위도"])
    except Stop as e:
        sys.exit(str(e))
    print("확인용 첫 응답(지적도):", json.dumps(sample, ensure_ascii=False)[:400], flush=True)
    stop, n = [], 0

    def one(r):
        if stop:
            return None
        try:
            return {"id": r["관리번호"], **{k: ask(key, layer, r["경도"], r["위도"]) for k, layer in LAYERS.items()}}
        except Stop as e:
            stop.append(str(e))
            return None
    with open(PART, "a", encoding="utf-8") as f, ThreadPoolExecutor(4) as pool:
        for x in pool.map(one, todo):
            if x:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
                done[x["id"]] = x
                n += 1
                if n % 500 == 0:
                    f.flush()
                    print(f"  {n:,} / {len(todo):,}", flush=True)
    if stop:
        print(f"멈춤: {stop[0]}\n받은 곳까지 저장했습니다. 내일(또는 문제를 고친 뒤) 다시 실행하면 이어서 받습니다.", flush=True)
    write(done)


def write(done):
    cols = sorted({f"{k}.{a}" for x in done.values() for k in LAYERS for a in x.get(k, {})})
    with gzip.open(OUT, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["관리번호"] + cols)
        for i, x in done.items():
            w.writerow([i] + [x.get(c.split(".", 1)[0], {}).get(c.split(".", 1)[1], "") for c in cols])
    print(f"저장: {OUT} ({len(done):,}곳). 이 파일을 저장소 scripts/static/ 에 올려 주세요.", flush=True)


if __name__ == "__main__":
    main()
