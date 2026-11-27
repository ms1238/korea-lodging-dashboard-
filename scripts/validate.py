"""Check the freshly built site/ before it is deployed; exit 1 stops the deploy (the last good site stays up).

Hard failures (::error::, exit 1): a file the page needs is missing or empty, a 시도 has no lodging at all,
the kept lodging count fell more than MAX_DROP against the deployed site, a 시도 lost more than MAX_DROP_SIDO
of its lodgings, a complete year of 방문자 data shrank more than MAX_DROP nationally (MAX_DROP_SIDO for one 시도),
or hotel_ops.csv no longer adds up (시도 객실 합 = 전국).
Soft problems (::warning::, deploy goes on): the deployed site cannot be read, a source is staler than expected.

The deployed site is https://<owner>.github.io/<repo>/ from GITHUB_REPOSITORY, or PAGES_URL if set.
"""
import csv
import json
import os
import sys
import urllib.request
from collections import defaultdict

SITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "site")
MAX_DROP = 0.05        # kept lodgings and 방문자 year totals
MAX_DROP_SIDO = 0.15   # one 시도's lodgings
errors, warnings = [], []


def load(name):
    with open(os.path.join(SITE, name), encoding="utf-8") as f:
        return json.load(f)


def deployed(name):
    base = os.environ.get("PAGES_URL")
    if not base and os.environ.get("GITHUB_REPOSITORY"):
        owner, repo = os.environ["GITHUB_REPOSITORY"].split("/")
        base = f"https://{owner}.github.io/{repo}/"
    if not base:
        return None
    try:
        with urllib.request.urlopen(base.rstrip("/") + "/" + name, timeout=60) as r:
            return json.load(r)
    except Exception as e:  # first deploy, Pages down, network: compare nothing
        warnings.append(f"deployed {name} not readable ({e}); skipped the comparison")
        return None


def drop(old, new):
    return (old - new) / old if old else 0


def check_meta():
    m = load("data/meta.json")
    kept = m["counts"]["kept"]
    if kept <= 0:
        errors.append("meta.json: no lodging kept")
    for s in m["sido"]:
        if s["n"] <= 0:
            errors.append(f"meta.json: {s['name']} has no lodging")
    old = deployed("data/meta.json")
    if old:
        d = drop(old["counts"]["kept"], kept)
        if d > MAX_DROP:
            errors.append(f"kept lodgings {old['counts']['kept']:,} → {kept:,} (−{d:.1%}, limit {MAX_DROP:.0%})")
        prev = {s["name"]: s["n"] for s in old["sido"]}
        for s in m["sido"]:
            if s["name"] in prev and drop(prev[s["name"]], s["n"]) > MAX_DROP_SIDO:
                errors.append(f"{s['name']} lodgings {prev[s['name']]:,} → {s['n']:,} (limit −{MAX_DROP_SIDO:.0%})")
        gone = set(prev) - {s["name"] for s in m["sido"]}
        if gone:
            errors.append(f"시도 missing from the build: {', '.join(sorted(gone))}")
    print(f"meta: {kept:,} lodgings in {len(m['sido'])} 시도")


def year_totals(v, names):
    """{(시도 name or "all", year): 외지인+외국인 total} for years with all four quarters (qdays ≥ 89).
    visits.json lists 시도 in meta.json's order, which follows lodging counts and can change from one build to the
    next (two 시도 with the same count swap), so the 시도 are keyed by the name at the same position in meta.json."""
    out = defaultdict(float)
    full = defaultdict(int)
    for i, q in enumerate(v["q"]):
        if v["qdays"][i] >= 89:
            full[q[:4]] += 1
        for si, s in enumerate(v["sido"]):
            if s:
                t = sum(s[j][i] or 0 for j in (0, 1))
                out[("all", q[:4])] += t
                out[(names[si] if si < len(names) else f"#{si}", q[:4])] += t
    return {k: t for k, t in out.items() if full[k[1]] == 4}


def check_visits():
    path = os.path.join(SITE, "data", "visits.json")
    if not os.path.exists(path):
        warnings.append("visits.json missing (DataLab not fetched); 방문자 sections will be hidden")
        return
    v = load("data/visits.json")
    new = year_totals(v, [s["name"] for s in load("data/meta.json")["sido"]])
    old, old_meta = deployed("data/visits.json"), deployed("data/meta.json")
    if old and old_meta:
        for (si, y), t in year_totals(old, [s["name"] for s in old_meta["sido"]]).items():
            lim, who = (MAX_DROP, "전국") if si == "all" else (MAX_DROP_SIDO, si)
            if (si, y) not in new:
                if si == "all":
                    errors.append(f"방문자 year {y} was complete on the deployed site and is not now")
            elif drop(t, new[(si, y)]) > lim:
                errors.append(f"방문자 {y} {who} {t:,.0f} → {new[(si, y)]:,.0f} (limit −{lim:.0%})")
    print(f"visits: last day {v['last']}, complete years {sorted({y for _, y in new})}")


def check_hotels():
    path = os.path.join(SITE, "hotel_ops.csv")
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    need = {"year", "sido", "sgg", "grade", "n", "rooms", "occ", "adr", "revpar", "fr"}
    if not rows or need - set(rows[0]):
        errors.append(f"hotel_ops.csv: empty or missing columns {sorted(need - set(rows[0] if rows else []))}")
        return
    tot = defaultdict(int)
    nat = {}
    for r in rows:
        if r["sgg"] == "" and r["grade"] == "전체":
            if r["sido"] == "전국":
                nat[r["year"]] = int(r["rooms"])
            else:
                tot[r["year"]] += int(r["rooms"])
        if r["grade"] == "전체" and r["occ"] and not 0 <= float(r["occ"]) <= 110:
            errors.append(f"hotel_ops.csv: {r['year']} {r['sido']} {r['sgg']} 이용률 {r['occ']}")
    for y, n in nat.items():
        if tot[y] != n:
            errors.append(f"hotel_ops.csv {y}: 시도 객실 합 {tot[y]:,} ≠ 전국 {n:,}")
    print(f"hotel_ops: years {sorted(nat)}")


def check_files():
    for name in ("index.html", "app.js", "indicators.json", "data/meta.json", "data/cube.json"):
        p = os.path.join(SITE, name)
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            errors.append(f"{name} missing or empty")


def main():
    check_files()
    if not errors:
        check_meta()
        check_visits()
        check_hotels()
    for w in warnings:
        print(f"::warning::{w}")
    for e in errors:
        print(f"::error::{e}")
    if errors:
        print(f"validate: {len(errors)} problem(s); not deploying, the last good site stays up")
        sys.exit(1)
    print("validate: ok")


if __name__ == "__main__":
    main()
