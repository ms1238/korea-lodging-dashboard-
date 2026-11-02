"""Archive the monthly snapshot on Zenodo so it gets a citable DOI (one version per month under one concept DOI).

Run by the workflow's monthly snapshot step when the ZENODO_TOKEN secret is set (a zenodo.org personal token with
deposit:write and deposit:actions). The repository variable ZENODO_DEPOSITION holds the id of any published version;
without it, the first run creates a new record and prints its id to save as that variable.

    python scripts/zenodo.py <tag> <file> [<file> …]
"""
import json
import os
import sys
from datetime import date

import requests

API = os.environ.get("ZENODO_API") or "https://zenodo.org/api"  # variable ZENODO_API=https://sandbox.zenodo.org/api to try it first


def main():
    tag, files = sys.argv[1], sys.argv[2:]
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {os.environ['ZENODO_TOKEN']}"

    def call(method, url, **kw):
        r = s.request(method, url if url.startswith("http") else API + url, timeout=300, **kw)
        if r.status_code >= 400:
            sys.exit(f"Zenodo {method} {url}: {r.status_code} {r.text[:500]}")
        return r.json() if r.content else {}
    meta = {
        "title": "전국 숙박시설 현황 (Korea Lodging Dashboard) 월별 스냅샷",
        "upload_type": "dataset",
        "description": "행정안전부 숙박 인허가 8종을 중복 제거·지역 매칭한 전국 숙박시설 데이터(lodging_*.csv.gz), "
                       "시군구 연도별 패널(panel_sgg.csv)과 코드북. https://ms1238.github.io/korea-lodging-dashboard-/",
        "creators": [{"name": os.environ.get("ZENODO_CREATOR") or "ms1238"}],
        "keywords": ["숙박시설", "관광 수용태세", "tourism accommodation", "South Korea"],
        "related_identifiers": [{"identifier": "https://github.com/ms1238/korea-lodging-dashboard-", "relation": "isSupplementTo", "scheme": "url"}],
        "version": tag,
        "publication_date": date.today().isoformat(),
    }
    if os.environ.get("ZENODO_LICENSE"):
        meta["license"] = os.environ["ZENODO_LICENSE"]
    dep_id = os.environ.get("ZENODO_DEPOSITION")
    if dep_id:
        # a new version is made from the latest published one
        latest = call("GET", f"/deposit/depositions/{dep_id}")["links"]["latest"].rstrip("/").split("/")[-1]
        draft = call("GET", call("POST", f"/deposit/depositions/{latest}/actions/newversion")["links"]["latest_draft"])
        for f in draft.get("files", []):  # a new version starts with the previous files
            call("DELETE", f"/deposit/depositions/{draft['id']}/files/{f['id']}")
    else:
        draft = call("POST", "/deposit/depositions", json={})
    for path in files:
        with open(path, "rb") as fh:
            call("PUT", f"{draft['links']['bucket']}/{os.path.basename(path)}", data=fh)
    call("PUT", f"/deposit/depositions/{draft['id']}", data=json.dumps({"metadata": meta}), headers={"Content-Type": "application/json"})
    done = call("POST", f"/deposit/depositions/{draft['id']}/actions/publish")
    print(f"Zenodo: published {tag} as record {done['id']}, DOI {done.get('doi')}, concept DOI {done.get('conceptdoi')}", flush=True)
    if not dep_id:
        print(f"::notice::Save {done['id']} as the repository variable ZENODO_DEPOSITION so later months become new versions "
              f"of the same record (concept DOI {done.get('conceptdoi')}).", flush=True)


if __name__ == "__main__":
    main()
