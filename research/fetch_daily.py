"""축제 전후 일별 외지인 방문자(한국관광공사 데이터랩)를 research/daily_visitors.csv.gz 로 받습니다.

scripts/fetch.py 는 같은 API를 일별로 받지만 월별로 합쳐 저장하므로, 축제 날짜 분석용으로 필요한 달만 다시 받습니다.
키는 환경변수 DATA_GO_KR_KEY (GitHub Actions: .github/workflows/research-daily.yml 이 secret 으로 넣음).
요청 수 = 달 수 × 2 (시도·시군구). 열: date, level(sido/sgg), code, name, n (외지인, touDivCd 2).
"""
import csv
import gzip
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from fetch import DATALAB_BASE, get_body, items_of  # noqa: E402  같은 재시도·오류 처리를 씀

# 축제 회차(research/festival_study.py EDITIONS)마다 앞뒤 4주 기준선이 들어가도록 고른 달
MONTHS = ["202408", "202409", "202410", "202411", "202412", "202509", "202510", "202511", "202512"]
OPS = {"sido": ("metcoRegnVisitrDDList", "areaCode", "areaNm"), "sgg": ("locgoRegnVisitrDDList", "signguCode", "signguNm")}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daily_visitors.csv.gz")


def month(key, op, ym):
    y, m = int(ym[:4]), int(ym[4:])
    end = date.fromordinal(date(y + m // 12, m % 12 + 1, 1).toordinal() - 1)
    params = {"serviceKey": key, "pageNo": 1, "numOfRows": 50000, "_type": "json", "MobileOS": "ETC",
              "MobileApp": "korea-lodging-dashboard", "startYmd": f"{ym}01", "endYmd": end.strftime("%Y%m%d")}
    body = get_body(DATALAB_BASE.format(op), params, f"{op} {ym}")
    items = items_of(body)
    if len(items) < int(body.get("totalCount") or 0):
        raise SystemExit(f"{op} {ym}: got {len(items)} of {body.get('totalCount')} rows")
    return items


def main():
    key = os.environ.get("DATA_GO_KR_KEY")
    if not key:
        raise SystemExit("DATA_GO_KR_KEY is not set")
    rows = []
    for level, (op, code_f, name_f) in OPS.items():
        for ym in MONTHS:
            got = [it for it in month(key, op, ym) if str(it["touDivCd"]) == "2"]
            rows += [[it["baseYmd"], level, it[code_f], it[name_f], round(float(it["touNum"]))] for it in got]
            print(f"{level} {ym}: {len(got)} rows", flush=True)
    rows.sort()
    with gzip.open(OUT, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "level", "code", "name", "n"])
        w.writerows(rows)
    print(f"wrote {OUT}: {len(rows)} rows")


if __name__ == "__main__":
    main()
