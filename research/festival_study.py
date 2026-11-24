"""바이럴 먹거리 축제는 왜 숙박으로 이어지지 않나 — 3층(방문·체류·공급) 사건연구.

배포된 대시보드 자료(site/data)를 읽어 처리군 6곳과 짝지은 비교군을 비교하고
research/festival_study_results.md, research/festival_study_panel.csv 를 씁니다.

    python research/festival_study.py [자료 폴더]

자료 폴더에 파일이 없으면 배포 사이트(PAGES_URL, 기본 아래 SITE)에서 받아 그 폴더에 둡니다.
설계와 해석은 research/festival_study.md.
"""
import csv
import json
import math
import os
import statistics as st
import sys
import urllib.request
from collections import defaultdict

SITE = os.environ.get("PAGES_URL", "https://ms1238.github.io/korea-lodging-dashboard-/").rstrip("/") + "/data/"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, ".cache")

# 처리군: 언론이 '예상을 넘은 인파'로 보도한 신생·급성장 먹거리 축제. onset = 처음 흥행한 회차의 분기,
# editions = 개최 시군구와 날짜가 기사로 확인된 회차(방문·체류 층은 이 회차의 달만 봄). 출처는 festival_study.md.
TREATED = [
    {"name": "김천 김밥축제", "sido": "경상북도", "sgg": "김천시", "onset": "2024Q4",
     "editions": ["2024-10", "2025-10"]},
    {"name": "구미 라면축제", "sido": "경상북도", "sgg": "구미시", "onset": "2024Q4",
     "editions": ["2024-11", "2025-11"]},
    {"name": "원주 만두축제", "sido": "강원특별자치도", "sgg": "원주시", "onset": "2023Q4",
     "editions": ["2024-10", "2025-10"]},
    {"name": "순창 떡볶이 페스타", "sido": "전북특별자치도", "sgg": "순창군", "onset": "2024Q4",
     "editions": ["2024-11", "2025-11"]},
    {"name": "대전 빵축제", "sido": "대전광역시", "sgg": "동구", "onset": "2024Q3",
     "editions": []},  # 2024.9 동구 소제동. 2025년 회차는 날짜·장소 미확인, 2026년은 유성구로 옮김
    {"name": "천안 빵빵데이", "sido": "충청남도", "sgg": "천안시", "onset": "2024Q4",
     "editions": ["2024-10", "2025-10"]},
]
N_CONTROLS = 5
PRE_Q = 12                      # 사건 전 12분기
LAST_Q = "2026Q3"               # 마지막 완결 분기
STAY = [("2102", "숙박 비중"), ("2103", "1박 방문자"), ("2104", "2박 방문자")]
RAIL = "간선열차 정차역"


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
    """같은 종류·같은 간선철도 접근성의 시군구 중 인구(로그)가 가장 가까운 N곳."""
    pool = [c for c in pop if c not in treated_keys and kind(c) == kind(k) and (c in rail) == (k in rail)]
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
    rows = kto["v"].get(f"{k[0]}:{k[1]}")
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
        if verdict != "–":
            types.setdefault(t["name"], []).append(verdict)
        w(f"| {t['name']} | {ym} | " + " | ".join(f"{f(v)} ({f(z)})" for v, z in zip(vals, zs)) + f" | {verdict} |")

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
w("| 축제 | ② 판정 | ③ 신규 인허가 백분위 | ③ 객실 백분위 |\n|---|---|---|---|")
for t, (_, p0), (_, p1) in zip(TREATED, agg["신규 인허가"], agg["인허가 객실"]):
    w(f"| {t['name']} | {', '.join(types.get(t['name'], ['판정 불가']))} | {p0:.0f} | {p1:.0f} |")

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
