"""바이럴 먹거리 축제는 왜 숙박으로 이어지지 않나 — 3층(방문·체류·공급) 사건연구.

배포된 대시보드 자료(site/data)를 읽어 처리군 6곳과 짝지은 비교군을 비교하고
research/festival_study_results.md, research/festival_study_panel.csv 를 씁니다.

    python research/festival_study.py [자료 폴더]

자료 폴더에 파일이 없으면 배포 사이트(PAGES_URL, 기본 아래 SITE)에서 받아 그 폴더에 둡니다.
설계와 해석은 research/festival_study.md.
"""
import csv
import gzip
import json
import math
import os
import statistics as st
import sys
import urllib.request
from collections import defaultdict
from datetime import date, timedelta

SITE = os.environ.get("PAGES_URL", "https://ms1238.github.io/korea-lodging-dashboard-/").rstrip("/") + "/data/"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, ".cache")

# 처리군: 언론이 '예상을 넘은 인파'로 보도한 신생·급성장 먹거리 축제. onset = 처음 흥행한 회차의 분기,
# days = 개최 시군구와 날짜가 기사로 확인된 회차(첫날, 끝날), said = 주최 측 발표 방문객(만 명). 출처는 festival_study.md.
TREATED = [
    {"name": "김천 김밥축제", "sido": "경상북도", "sgg": "김천시", "onset": "2024Q4",
     "days": [("2024-10-26", "2024-10-27"), ("2025-10-25", "2025-10-26")], "said": [10, 15]},
    {"name": "구미 라면축제", "sido": "경상북도", "sgg": "구미시", "onset": "2024Q4",
     "days": [("2024-11-01", "2024-11-03"), ("2025-11-07", "2025-11-09")], "said": [17, 35]},
    {"name": "원주 만두축제", "sido": "강원특별자치도", "sgg": "원주시", "onset": "2023Q4",
     "days": [("2024-10-25", "2024-10-27"), ("2025-10-24", "2025-10-26")], "said": [50, 41]},
    {"name": "순창 떡볶이 페스타", "sido": "전북특별자치도", "sgg": "순창군", "onset": "2024Q4",
     "days": [("2024-11-16", "2024-11-17"), ("2025-11-15", "2025-11-16")], "said": [None, None]},
    {"name": "대전 빵축제", "sido": "대전광역시", "sgg": "동구", "onset": "2024Q3",
     "days": [("2024-09-28", "2024-09-29")], "said": [14]},  # 2025년 회차는 날짜·장소 미확인, 2026년은 유성구로 옮김
    {"name": "천안 빵빵데이", "sido": "충청남도", "sgg": "천안시", "onset": "2024Q4",
     "days": [("2024-10-12", "2024-10-13"), ("2025-10-18", "2025-10-19")], "said": [23, None]},
]
for t in TREATED:
    t["editions"] = [a[:7] for a, _ in t["days"]]
N_CONTROLS = 5
PRE_Q = 12                      # 사건 전 12분기
LAST_Q = "2026Q3"               # 마지막 완결 분기
STAY = [("2102", "숙박 비중"), ("2103", "1박 방문자"), ("2104", "2박 방문자")]
RAIL = "간선열차 정차역"
HUB_KM = 60          # 인근 대도시 반경: 숙소 분포 중심 간 직선거리(대략 1시간 이동권; 50km면 김천-대구 52km가 빠짐)
HUB_POP = 500_000    # 광역시가 아닌 시는 인구 50만 이상만 대도시로 봄


def load(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        urllib.request.urlretrieve(SITE + name, path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def qidx(q):  # "2024Q4" -> 연속 분기 번호
    return int(q[:4]) * 4 + int(q[5]) - 1


def qname(i):
    return f"{i // 4}Q{i % 4 + 1}"


meta, visits, kto, stations = load("meta.json"), load("visits.json"), load("kto_index.json"), load("stations.json")
sidos = meta["sido"]
key_of = {(s["name"], g): (si, gi) for si, s in enumerate(sidos) for gi, g in enumerate(s["sgg"])}
pop = {(si, gi): p for si, s in enumerate(sidos) for gi, p in enumerate(s.get("popg") or []) if p}
rail_line = [i for i, l in enumerate(stations["lines"]) if l[0].startswith(RAIL)]
rail = {(x[3], x[4]) for x in stations["st"] if set(x[5]) & set(rail_line)}


def kind(k):  # 비교군은 같은 종류끼리: 군 / 시 / 광역시 구
    g = sidos[k[0]]["sgg"][k[1]]
    return "군" if g.endswith("군") else "구" if g.endswith("구") else "시"


def label(k):
    return f"{sidos[k[0]]['name']} {sidos[k[0]]['sgg'][k[1]]}"


for t in TREATED:
    t["k"] = key_of[(t["sido"], t["sgg"])]
treated_keys = {t["k"] for t in TREATED}


def controls(k):
    """같은 종류·같은 간선철도 접근성의 시군구 중 인구(로그)가 가장 가까운 N곳. 광역시 단위 대도시는 다른 광역시들."""
    if k[0] == "hub":
        return [("hub", n) for n in HUBS if n != k[1]]
    pool = [c for c in pop if c not in treated_keys and c != k and kind(c) == kind(k) and (c in rail) == (k in rail)]
    return sorted(pool, key=lambda c: abs(math.log(pop[c]) - math.log(pop[k])))[:N_CONTROLS]


# ---------- ① 방문: 축제 달 외지인의 전국 대비 비중이 평소보다 얼마나 높았나 ----------
# 기준을 시도가 아닌 전국으로 둔 것은 시도 안의 다른 대형 행사(예: 2025.10~11 경주 APEC)가 기준을 흔들지 않게 하려는 것.
M, MFULL = visits["m"], visits["mfull"]
NATION = [sum(s[i] or 0 for s in visits["msido"] if s) for i in range(len(M))]


def visit_ar(k, ym):
    """(축제 달 전국 대비 비중 / 다른 달 비중 중앙값) - 1. 전국 공통 계절성을 뺀 이상 증가율."""
    s = visits["msgg"][k[0]][k[1]] if visits["msgg"][k[0]] else None
    if not s or ym not in M:
        return None
    sh = [s[i] / NATION[i] if s[i] and NATION[i] and MFULL[i] else None for i in range(len(M))]
    i = M.index(ym)
    rest = [x for j, x in enumerate(sh) if x and M[j][4:] != ym[4:]]
    return sh[i] / st.median(rest) - 1 if sh[i] and rest else None


def visit_z(k, ym):
    """축제 달 이상 증가율이 같은 시군구의 다른 달(축제 달과 다른 달)들 사이에서 몇 표준편차인가."""
    a = visit_ar(k, ym)
    other = [visit_ar(k, m) for m in M if m[4:] != ym[4:]]
    other = [x for x in other if x is not None]
    return a / st.pstdev(other) if a is not None and len(other) > 3 and st.pstdev(other) else None


# ---------- ② 체류: 관광수요지수 숙박 지표가 축제 달에 평소보다 올랐나 (비교군 변화 차감) ----------
KM = [m for m in kto["months"] if m <= "202609"]
KIX = [i[0] for i in kto["ix"]]


def stay_dev(k, ym, code):
    """축제 달 값 - 같은 시군구 다른 달 중앙값 (지수 포인트)."""
    rows = kto_rows(k)
    if not rows or ym not in KM:
        return None
    x = rows[KIX.index(code)]
    i = kto["months"].index(ym)
    rest = [x[j] for j, m in enumerate(kto["months"]) if m in KM and m[4:] != ym[4:] and x[j] is not None]
    return x[i] - st.median(rest) if x[i] is not None and rest else None


def stay_net(k, cs, ym, code):
    """처리군 변화 - 비교군 변화 중앙값: 같은 달의 전국 공통 계절성을 비교군으로 뺌."""
    a = stay_dev(k, ym, code)
    b = [x for x in (stay_dev(c, ym, code) for c in cs) if x is not None]
    return a - st.median(b) if a is not None and b else None


def stay_sd(k, cs, code):
    """다른 달들의 (처리-비교) 값의 표준편차: 축제 효과가 '보통 흔들림'보다 큰지 보는 잣대."""
    xs = [x for x in (stay_net(k, cs, m, code) for m in KM) if x is not None]
    return st.pstdev(xs) if len(xs) > 3 else None


# ---------- ①′ 방문(일별): 축제 기간 외지인이 같은 요일 평소보다 얼마나 많았나 ----------
# research/daily_visitors.csv.gz (research/fetch_daily.py). 기대값 = 앞뒤 2~4주 같은 요일의 전국 대비 비중 평균 × 그날 전국 외지인.
DAILY = os.path.join(HERE, "daily_visitors.csv.gz")
MERGED = "전남광주통합특별시"
SIDO_ALIAS = {"강원도": "강원특별자치도", "전라북도": "전북특별자치도", "광주광역시": MERGED, "전라남도": MERGED}
daily_nat, daily = defaultdict(int), defaultdict(lambda: defaultdict(int))
if os.path.exists(DAILY):
    with gzip.open(DAILY, "rt", encoding="utf-8") as fi:
        drows = list(csv.DictReader(fi))
    sido_code = {r["code"]: SIDO_ALIAS.get(r["name"], r["name"]) for r in drows if r["level"] == "sido"}
    uniq = defaultdict(list)
    for k0 in key_of.values():
        uniq[sidos[k0[0]]["sgg"][k0[1]]].append(k0)
    for r in drows:
        if r["level"] == "sido":
            daily_nat[r["date"]] += int(r["n"])
        elif " " not in r["name"]:  # "수원시 장안구" 같은 일반구는 시 단위 행과 겹침
            sd = sido_code.get(r["code"][:2])
            sd = sd if sd in {x["name"] for x in sidos} else None
            k0 = key_of.get((sd, r["name"])) or (uniq[r["name"]][0] if len(uniq[r["name"]]) == 1 else None)
            if k0:
                daily[k0][r["date"]] += int(r["n"])


def ds(d):
    return d.strftime("%Y%m%d")


def dshare(k, d):
    n, t = daily_of(k).get(ds(d)), daily_nat.get(ds(d))
    return n / t if n and t else None


def dexp(k, d):
    """그날의 기대 외지인 수: 앞뒤 2~4주 같은 요일 비중 평균 × 그날 전국 외지인."""
    xs = [x for x in (dshare(k, d + timedelta(7 * wk)) for wk in (-4, -3, -2, 2, 3, 4)) if x]
    return st.mean(xs) * daily_nat[ds(d)] if len(xs) >= 3 and daily_nat.get(ds(d)) else None


def dabn(k, d0, d1):
    """d0~d1 기간의 (실제/기대 - 1, 실제 - 기대)."""
    days = [d0 + timedelta(i) for i in range((d1 - d0).days + 1)]
    act = [daily_of(k).get(ds(d)) for d in days]
    exp = [dexp(k, d) for d in days]
    if not all(act) or not all(exp):
        return None, None
    return sum(act) / sum(exp) - 1, sum(act) - sum(exp)


def dz(k, d0, d1):
    """축제 기간 하루 평균 이상 증가율 / 앞뒤 28일(축제 기간 제외) 하루 이상 증가율의 표준편차."""
    a, _ = dabn(k, d0, d1)
    other = [dabn(k, d, d)[0] for d in (d0 + timedelta(i) for i in range(-28, (d1 - d0).days + 29)) if d < d0 or d > d1]
    other = [x for x in other if x is not None]
    return a / st.pstdev(other) if a is not None and len(other) > 10 and st.pstdev(other) else None


def dlocal(k, d0, d1):
    """축제 기간이 바로 앞뒤 7일보다 얼마나 더 높았나: 단풍철처럼 그 무렵 전체가 붐비는 효과를 뺀 축제 고유 효과."""
    a = dabn(k, d0, d1)[0]
    near = [dabn(k, d0 - timedelta(7), d0 - timedelta(1))[0], dabn(k, d1 + timedelta(1), d1 + timedelta(7))[0]]
    if a is None or None in near:
        return None
    return (1 + a) / (1 + st.mean(near)) - 1


def edition_days(e):
    return date.fromisoformat(e[0]), date.fromisoformat(e[1])


# ---------- ②′ 인근 유출: 축제 달 인접 시군구·반경 안 대도시의 숙박 지표가 올랐나 ----------
def neighbours(k):
    return [tuple(x) for x in sidos[k[0]]["adj"][k[1]] if tuple(x) in pop]


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def mean_rows(keys):
    """여러 구의 지수를 단순 평균(지수라 가중치가 없음; build.py가 일반구를 묶는 방식과 같음)."""
    rs = [kto["v"][x] for x in keys if x in kto["v"]]
    if not rs:
        return None
    return [[(st.mean(v) if (v := [r[j][i] for r in rs if r[j][i] is not None]) else None) for i in range(len(kto["months"]))]
            for j in range(len(KIX))]


# 광역시 단위 대도시: 광역시·서울은 시 전체, 통합특별시 안의 옛 광주는 구 묶음. 키 ("hub", 이름).
HUBS = {}
for si, sm in enumerate(sidos):
    if sm["name"].endswith("광역시") or sm["name"] == "서울특별시":
        gis = list(range(len(sm["sgg"])))
        HUBS[sm["name"]] = {"si": si, "gis": gis, "c": sm["c"], "rows": kto["v"].get(str(si))}
    for g in sm.get("groups", []):
        if g["name"] == "광주시":
            cs_ = [sm["sggc"][i] for i in g["gis"] if sm["sggc"][i]]
            HUBS["광주광역시(옛)"] = {"si": si, "gis": g["gis"], "c": [st.median(x[0] for x in cs_), st.median(x[1] for x in cs_)],
                                  "rows": mean_rows([f"{si}:{i}" for i in g["gis"]])}
for h in HUBS.values():
    h["pop"] = sum(pop.get((h["si"], i), 0) for i in h["gis"])
_hub_daily = {}


def kto_rows(k):
    return HUBS[k[1]]["rows"] if k[0] == "hub" else kto["v"].get(f"{k[0]}:{k[1]}")


def daily_of(k):
    if k[0] != "hub":
        return daily[k]
    if k[1] not in _hub_daily:
        acc = defaultdict(int)
        for i in HUBS[k[1]]["gis"]:
            for d, n in daily[(HUBS[k[1]]["si"], i)].items():
                acc[d] += n
        _hub_daily[k[1]] = acc
    return _hub_daily[k[1]]


def unit_name(u):
    return u[1] if u[0] == "hub" else sidos[u[0]]["sgg"][u[1]]


def unit_pop(u):
    return HUBS[u[1]]["pop"] if u[0] == "hub" else pop[u]


def hubs_near(k):
    """반경 HUB_KM 안의 대도시(광역시 단위, 또는 인구 HUB_POP 이상 시) 중 인접 시군구와 개최지 자신이 속한 광역시를 뺀 곳, 가까운 순."""
    c, adj = sidos[k[0]]["sggc"][k[1]], set(neighbours(k))
    out = [(km(c, h["c"]), ("hub", n)) for n, h in HUBS.items() if not (h["si"] == k[0] and k[1] in h["gis"])]
    out += [(km(c, sidos[u[0]]["sggc"][u[1]]), u) for u in pop
            if kind(u) == "시" and pop[u] >= HUB_POP and sidos[u[0]]["sggc"][u[1]] and u != k and u not in adj]
    return [(d, u) for d, u in sorted(out) if d <= HUB_KM]


def nb_signal(nb, ym):
    """인접 시군구의 (숙박 비중 z, 1박 방문자 z), 그 시군구 자신의 비교군 차감."""
    cs = controls(nb)
    out = []
    for code in ("2102", "2103"):
        v, sd = stay_net(nb, cs, ym, code), stay_sd(nb, cs, code)
        out.append(v / sd if v is not None and sd else None)
    return out


def nb_flag(zs):
    return any(z is not None and z >= 2 for z in zs)


# ---------- ③ 공급: 분기별 신규 인허가·인허가 객실·폐업 (주민 10만 명당) ----------
Q0, Q1 = qidx("2020Q1"), qidx(LAST_Q)
panel = defaultdict(lambda: [[0, 0, 0] for _ in range(Q1 - Q0 + 1)])   # k -> [신규, 객실, 폐업] per quarter


def q_of(d):
    if len(d) < 7 or not d[:4].isdigit() or not d[5:7].isdigit():
        return None
    i = int(d[:4]) * 4 + (int(d[5:7]) - 1) // 3
    return i - Q0 if Q0 <= i <= Q1 else None


for si in range(len(sidos)):
    for r in load(f"pts/{si}.json")["rows"]:
        k = (si, r[3])
        q = q_of(r[11] or "")
        if q is not None:
            panel[k][q][0] += 1
            panel[k][q][1] += r[16] or 0
        q = q_of(r[12] or "") if r[6] == 2 else None
        if q is not None:
            panel[k][q][2] += 1


def rate(k, j, lo, hi):
    """lo..hi 분기(연속 번호) 평균, 주민 10만 명당 분기 값."""
    xs = [panel[k][i - Q0][j] for i in range(lo, hi + 1)]
    return sum(xs) / len(xs) / pop[k] * 1e5


def did(k, j, onset):
    lo, e = onset - PRE_Q, onset
    return rate(k, j, e, Q1) - rate(k, j, lo, e - 1)


def pctile(k, j, onset):
    """같은 종류 전체 시군구에서 (사건 후 - 사건 전) 변화가 처리군보다 작은 곳의 비율."""
    me = did(k, j, onset)
    pool = [c for c in pop if kind(c) == kind(k) and c != k]
    return 100 * sum(did(c, j, onset) < me for c in pool) / len(pool)


# ---------- 결과 쓰기 ----------
def f(x, d=1, pct=False, sign=True):
    if x is None:
        return "–"
    return (f"{x * 100:+.{d}f}%" if pct else f"{x:+.{d}f}") if sign else f"{x:.{d}f}"


out = []
w = out.append
w("# 바이럴 먹거리 축제 3층 분석 결과\n")
w(f"`research/festival_study.py`가 자동으로 쓴 파일입니다. 자료: 배포 사이트 `{meta['updated']}` 갱신본. "
  "설계·해석은 `festival_study.md`.\n")

w("## 처리군과 비교군\n")
w("| 축제 | 시군구 | 인구 | 간선철도 | 흥행 시작 | 비교군 (인구 가까운 순) |\n|---|---|---|---|---|---|")
for t in TREATED:
    t["c"] = controls(t["k"])
    w(f"| {t['name']} | {label(t['k'])} | {pop[t['k']]:,} | {'있음' if t['k'] in rail else '없음'} | {t['onset']} | "
      + ", ".join(sidos[c[0]]["sgg"][c[1]] + f"({pop[c]//1000}천)" for c in t["c"]) + " |")

w("\n## ① 방문 — 축제 달 외지인의 전국 대비 비중, 평소 대비\n")
w("전국이 함께 붐비는 계절 효과를 뺀 값입니다. z는 같은 시군구의 다른 달 흔들림 대비 크기(|z|≥2면 평소 변동을 넘는 급증).\n")
w("| 축제 | 회차 | 처리군 | z | 비교군 중앙값 | 처리 − 비교 |\n|---|---|---|---|---|---|")
for t in TREATED:
    for ym in t["editions"]:
        a = visit_ar(t["k"], ym.replace("-", ""))
        if a is None:
            w(f"| {t['name']} | {ym} | 자료 없음 (월별 방문자는 {M[0][:4]}-{M[0][4:]}부터) | | | |")
            continue
        cs = [x for x in (visit_ar(c, ym.replace("-", "")) for c in t["c"]) if x is not None]
        cm = st.median(cs) if cs else None
        w(f"| {t['name']} | {ym} | {f(a, pct=True)} | {f(visit_z(t['k'], ym.replace('-', '')), 1)} | {f(cm, pct=True)} | "
          f"{f(a - cm if cm is not None else None, pct=True)} |")
    if not t["editions"]:
        w(f"| {t['name']} | – | 개최지·날짜가 확인된 회차가 자료 기간에 없음 | | | |")

w("\n## ①′ 방문(일별) — 축제 기간 외지인, 같은 요일 평소 대비\n")
if not daily_nat:
    w("`research/daily_visitors.csv.gz`가 없어 건너뜀 (`research/fetch_daily.py`로 받음).\n")
else:
    w("기대값은 앞뒤 2~4주 같은 요일의 전국 대비 비중으로 계산(전국 공통 변동 제거). 초과 외지인 = 실제 − 기대(연인원, 하루 단위로 셈). "
      "z는 앞뒤 28일 하루 변동 대비 배수. 앞·뒤 7일은 축제 직전·직후 주의 같은 계산(0 근처면 축제 효과가 축제 기간에만 있음). "
      "**주변 주 대비**는 축제 기간이 앞뒤 7일 평균보다 더 높은 정도로, 단풍철처럼 그 무렵 전체가 붐비는 효과를 뺀 축제 고유 효과(핵심 지표). "
      "발표 방문객은 주최 측 집계(주민 포함, 기준 제각각)라 직접 비교하지 말고 규모만 참고.\n")
    w("| 축제 | 기간 | 처리군 | 초과 외지인 | z | 앞 7일 | 뒤 7일 | **주변 주 대비** | 비교군 중앙값 | 발표 방문객 |\n"
      "|---|---|---|---|---|---|---|---|---|---|")
    for t in TREATED:
        t["dz"], t["dl"] = [], []
        for e, said in zip(t["days"], t["said"]):
            d0, d1 = edition_days(e)
            a, x = dabn(t["k"], d0, d1)
            z = dz(t["k"], d0, d1)
            t["dz"].append(z)
            t["dl"].append(dlocal(t["k"], d0, d1))
            pre, post = dabn(t["k"], d0 - timedelta(7), d0 - timedelta(1))[0], dabn(t["k"], d1 + timedelta(1), d1 + timedelta(7))[0]
            cs = [y for y in (dabn(c, d0, d1)[0] for c in t["c"]) if y is not None]
            w(f"| {t['name']} | {e[0]}~{e[1][5:]} | {f(a, pct=True)} | {f'{x:+,.0f}명' if x is not None else '–'} | {f(z)} | "
              f"{f(pre, pct=True)} | {f(post, pct=True)} | **{f(t['dl'][-1], pct=True)}** | {f(st.median(cs) if cs else None, pct=True)} | "
              f"{f'{said}만 명' if said else '–'} |")

w("\n## ② 체류 — 축제 달 숙박 지표(관광수요지수)의 평소 대비 변화, 비교군 변화 차감\n")
w("단위는 지수 포인트(처리군 변화 − 비교군 변화 중앙값), 괄호는 z(다른 달들의 같은 값 흔들림 대비 배수). "
  "판정: 숙박 비중 z≥2면 **체류형**, 숙박 비중은 그대로인데 1박·2박 방문자 중 하나가 z≥2면 **부분 체류**, 아니면 **당일형**.\n")
w("| 축제 | 회차 | " + " | ".join(n for _, n in STAY) + " | 판정 |\n|---|---|" + "---|" * (len(STAY) + 1))
types = {}
for t in TREATED:
    for ym in t["editions"]:
        vals = [stay_net(t["k"], t["c"], ym.replace("-", ""), c) for c, _ in STAY]
        sds = [stay_sd(t["k"], t["c"], c) for c, _ in STAY]
        zs = [v / s if v is not None and s else None for v, s in zip(vals, sds)]
        verdict = ("–" if zs[0] is None else "체류형" if zs[0] >= 2
                   else "부분 체류" if any(z is not None and z >= 2 for z in zs[1:]) else "당일형")
        types.setdefault(t["name"], []).append(verdict if verdict != "–" else "판정 불가")
        w(f"| {t['name']} | {ym} | " + " | ".join(f"{f(v)} ({f(z)})" for v, z in zip(vals, zs)) + f" | {verdict} |")

w("\n## ②′ 인근 유출 — 축제 달 인접 시군구와 반경 안 대도시의 숙박 지표\n")
w(f"대상: 경계를 맞댄 시군구 + 반경 {HUB_KM}km 안 대도시(광역시는 시 전체, 옛 광주는 구 묶음, 그 밖은 인구 {HUB_POP // 10000}만 이상 시; "
  "거리는 숙소 분포 중심 간 직선거리). "
  "각 지역마다 그 지역 자신의 비교군(시군구는 같은 방식, 광역시 단위는 다른 광역시들)을 빼고, 다른 달 흔들림 대비 z를 냅니다. "
  "**신호(●)** = 그 달 숙박 비중이나 1박 방문자가 z≥2 **이고** 축제 기간 외지인이 앞뒤 주보다 5% 이상 많음(일별 자료가 있을 때). "
  "월 지표만으로는 단풍철 같은 같은 달의 다른 수요와 구분이 안 되므로 일별 조건을 함께 둡니다(○ = 월 지표만 해당). "
  "인접 시군구가 여럿이라 우연한 신호도 잦아, 같은 인접 시군구들이 **축제가 없는 달**에 월 지표 신호를 낸 비율(평시 오경보율, "
  "일별 조건이 빠져 있어 실제 오경보율보다 높게 잡힌 값)과 함께 봅니다.\n")
w("| 축제 | 회차 | 지역 (인구) | 구분 | 축제 기간 외지인 (평소 대비) | 같은 (주변 주 대비) | 숙박 비중 z | 1박 방문자 z | 신호 |\n"
  "|---|---|---|---|---|---|---|---|---|")
spill = {}
for t in TREATED:
    nbs = [(nb, "인접") for nb in neighbours(t["k"])] + [(u, f"대도시 {d:.0f}km") for d, u in hubs_near(t["k"])]
    t["nunits"] = len(nbs)
    fest_m = {e[5:] for e in t["editions"]}
    base = [any(nb_flag(nb_signal(nb, m)) for nb, _ in nbs) for m in KM if m[4:] not in fest_m]
    t["base"], t["nbase"] = (sum(base) / len(base) if base else None), len(base)
    for e, ym in zip(t["days"], t["editions"]):
        d0, d1 = edition_days(e)
        hits = []
        for nb, role in nbs:
            zs = nb_signal(nb, ym.replace("-", ""))
            a = dabn(nb, d0, d1)[0] if daily_nat else None
            loc = dlocal(nb, d0, d1) if daily_nat else None
            month_flag = nb_flag(zs)
            flag = month_flag and (not daily_nat or (loc is not None and loc >= 0.05))
            if flag:
                hits.append(unit_name(nb))
            w(f"| {t['name']} | {ym} | {unit_name(nb)} ({unit_pop(nb) // 1000:,}천) | {role} | {f(a, pct=True)} | {f(loc, pct=True)} | "
              f"{f(zs[0])} | {f(zs[1])} | {'●' if flag else '○' if month_flag else ''} |")
        spill[(t["name"], ym)] = hits
w("\n| 축제 | 살핀 지역 (인접 + 대도시) | 신호(●) 낸 곳 | 평시 오경보율 (월 지표만, 축제 없는 달에 하나라도) |\n|---|---|---|---|")
for t in TREATED:
    got = "; ".join(f"{ym}: {', '.join(spill[(t['name'], ym)]) or '없음'}" for ym in t["editions"])
    base = f"{t['base'] * 100:.0f}% ({round(t['base'] * t['nbase'])}/{t['nbase']}달)" if t["base"] is not None else "–"
    w(f"| {t['name']} | {len(neighbours(t['k']))} + {t['nunits'] - len(neighbours(t['k']))} | {got} | {base} |")

w("\n## ③ 공급 — 흥행 전 12분기 대비 흥행 후 분기당 변화 (주민 10만 명당)\n")
w(f"사건 후는 흥행 시작 분기부터 {LAST_Q}까지. 이중차분 = (처리 후−전) − (비교군 중앙값 후−전). "
  "백분위는 같은 종류(시/군/구) 전국 시군구 중 처리군보다 변화가 작은 곳의 비율(50 근처면 평범, 90 이상이면 두드러진 증가).\n")
names = [("신규 인허가", 0), ("인허가 객실", 1), ("폐업", 2)]
w("| 축제 | 사건 후 분기 수 | " + " | ".join(f"{n} 처리 변화 | {n} 이중차분 | {n} 백분위" for n, _ in names) + " |\n|---|---|"
  + "---|" * (3 * len(names)))
agg = defaultdict(list)
for t in TREATED:
    on = qidx(t["onset"])
    cells = []
    for n, j in names:
        dt = did(t["k"], j, on)
        dc = st.median(did(c, j, on) for c in t["c"])
        p = pctile(t["k"], j, on)
        agg[n].append((dt - dc, p))
        cells += [f(dt, 2), f(dt - dc, 2), f"{p:.0f}"]
    w(f"| {t['name']} | {Q1 - on + 1} | " + " | ".join(cells) + " |")
w("| **중앙값** | | " + " | ".join(f" | {f(st.median(x for x, _ in agg[n]), 2)} | {st.median(p for _, p in agg[n]):.0f}"
                                       for n, _ in names) + " |")

w("\n## 유형 요약\n")
w("숙박 행방: 개최지에 숙박 신호가 있으면 '개최지 체류', 없고 인접 시군구나 반경 안 대도시에 신호가 있으면 '인근 유출 의심'"
  "(평시 오경보율이 높으면 약한 근거), 둘 다 없으면 '당일 귀가'.\n")
w("| 축제 | 회차 | ①′ 축제 고유 방문 증가 (주변 주 대비) | ② 개최지 판정 | ②′ 인접·대도시 신호 | 숙박 행방 | ③ 신규 인허가 백분위 | ③ 객실 백분위 |\n"
  "|---|---|---|---|---|---|---|---|")
for t, (_, p0), (_, p1) in zip(TREATED, agg["신규 인허가"], agg["인허가 객실"]):
    for i, ym in enumerate(t["editions"]):
        host = types.get(t["name"], [])
        host = host[i] if i < len(host) else "판정 불가"
        hits = spill.get((t["name"], ym), [])
        where = ("개최지 체류" if host in ("체류형", "부분 체류") else "인근 유출 의심" if hits
                 else "당일 귀가" if host == "당일형" else "판정 불가")
        dl = t["dl"][i] if t.get("dl") else None
        w(f"| {t['name']} | {ym} | {f(dl, pct=True)} | {host} | {', '.join(hits) or '없음'} | {where} | {p0:.0f} | {p1:.0f} |")

with open(os.path.join(HERE, "festival_study_results.md"), "w", encoding="utf-8") as fo:
    fo.write("\n".join(out) + "\n")

# 분기 패널: 처리군과 비교군, 사건 기준 상대 분기 포함 (통계 패키지로 다시 돌릴 때)
with open(os.path.join(HERE, "festival_study_panel.csv"), "w", encoding="utf-8-sig", newline="") as fo:
    cw = csv.writer(fo)
    cw.writerow(["축제", "역할", "시도", "시군구", "인구", "분기", "상대분기", "신규인허가", "인허가객실", "폐업"])
    for t in TREATED:
        on = qidx(t["onset"])
        for role, ks in (("처리", [t["k"]]), ("비교", t["c"])):
            for k in ks:
                for i in range(Q0, Q1 + 1):
                    cw.writerow([t["name"], role, sidos[k[0]]["name"], sidos[k[0]]["sgg"][k[1]], pop[k], qname(i), i - on,
                                 *panel[k][i - Q0]])
print("wrote research/festival_study_results.md, research/festival_study_panel.csv")
