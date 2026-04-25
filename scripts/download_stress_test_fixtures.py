"""Download F100 SEC filings for the Sunday-morning stress test.

Companies (CIK fixed; do not mutate):
    Unilever (UL, 20-F)            CIK 0000217410
    Pfizer (PFE, 10-K)             CIK 0000078003
    Microsoft (MSFT, 10-K)         CIK 0000789019
    JPMorgan Chase (JPM, 10-K)     CIK 0000019617
    Procter & Gamble (PG, 10-K)    CIK 0000080424

For each: fetches the most recent annual report (10-K or 20-F),
DEF 14A proxy, 10-Q, and earnings 8-K (filtered to Item 2.02 only).

Output: rcs-sidecar/fixtures/stress_test_f100/<company>/<form>_<date>.<ext>
The folder is gitignored — script is in the repo, fixtures are not.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "rcs-sidecar" / "fixtures" / "stress_test_f100"

USER_AGENT = "Hafeedh Balogun (schoolbalogun@gmail.com) Kaide Labs research demo"

COMPANIES = [
    ("unilever",   "0000217410", "20-F"),
    ("pfizer",     "0000078003", "10-K"),
    ("microsoft",  "0000789019", "10-K"),
    ("jpmorgan",   "0000019617", "10-K"),
    ("pg",         "0000080424", "10-K"),
]
EXTRA_FORMS = ["DEF 14A", "10-Q"]
EARNINGS_8K_ITEM = "2.02"

REQUEST_DELAY_S = 0.15
TIMEOUT_S = 30


def _get(url: str, host: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
            "Host": host,
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        data = r.read()
    if data[:2] == b"\x1f\x8b":
        import gzip
        data = gzip.decompress(data)
    return data


def _submissions(cik_padded: str) -> dict:
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    return json.loads(_get(url, "data.sec.gov").decode("utf-8"))


def _doc_url(cik_int: int, accession: str, primary_doc: str) -> str:
    acc_no_dash = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_no_dash}/{primary_doc}"


def _pick_targets(filings: dict, annual_form: str) -> list[tuple[str, str, str, str, str]]:
    """Returns (form, filing_date, accession, primary_document, items) tuples."""
    forms = filings.get("form", [])
    dates = filings.get("filingDate", [])
    accs = filings.get("accessionNumber", [])
    docs = filings.get("primaryDocument", [])
    items = filings.get("items", [""] * len(forms))

    rows = list(zip(forms, dates, accs, docs, items))
    targets = []

    def first_match(predicate):
        for r in rows:
            if predicate(r):
                return r
        return None

    annual = first_match(lambda r: r[0] == annual_form)
    if annual:
        targets.append(annual)
    for f in EXTRA_FORMS:
        m = first_match(lambda r, f=f: r[0] == f)
        if m:
            targets.append(m)
    earnings = first_match(lambda r: r[0] == "8-K" and EARNINGS_8K_ITEM in (r[4] or ""))
    if earnings:
        targets.append(earnings)
    return targets


def _safe_form(form: str) -> str:
    return form.replace(" ", "").replace("/", "-")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict] = {}

    for slug, cik_padded, annual_form in COMPANIES:
        cik_int = int(cik_padded)
        company_dir = OUT_DIR / slug
        company_dir.mkdir(exist_ok=True)
        per_company = {"files": 0, "bytes": 0, "missing": []}

        try:
            data = _submissions(cik_padded)
        except Exception as e:
            print(f"[{slug}] FAILED submissions fetch: {type(e).__name__}: {e}")
            per_company["missing"].append("submissions_json")
            summary[slug] = per_company
            time.sleep(REQUEST_DELAY_S)
            continue
        time.sleep(REQUEST_DELAY_S)

        filings = data.get("filings", {}).get("recent", {})
        targets = _pick_targets(filings, annual_form)
        wanted_forms = [annual_form, *EXTRA_FORMS, "8-K"]
        got_forms = {t[0] for t in targets}
        for w in wanted_forms:
            if w not in got_forms:
                per_company["missing"].append(w)

        for form, date, accession, primary, _items in targets:
            ext = Path(primary).suffix or ".htm"
            out = company_dir / f"{_safe_form(form)}_{date}{ext}"
            url = _doc_url(cik_int, accession, primary)
            t0 = time.monotonic()
            try:
                blob = _get(url, "www.sec.gov")
                out.write_bytes(blob)
                kb = len(blob) / 1024.0
                dt = time.monotonic() - t0
                print(f"[{slug}] OK   {form:8s} {date}  {kb:8.1f} KB  {dt:5.1f}s  {out.name}")
                per_company["files"] += 1
                per_company["bytes"] += len(blob)
            except Exception as e:
                print(f"[{slug}] FAIL {form:8s} {date}  {type(e).__name__}: {e}")
                per_company["missing"].append(form)
            time.sleep(REQUEST_DELAY_S)

        summary[slug] = per_company

    print("\n=== summary ===")
    total_files = total_bytes = 0
    for slug, info in summary.items():
        mb = info["bytes"] / 1024.0 / 1024.0
        miss = f" (missing: {', '.join(info['missing'])})" if info["missing"] else ""
        print(f"  {slug:12s} {info['files']} files, {mb:.2f} MB{miss}")
        total_files += info["files"]
        total_bytes += info["bytes"]
    print(f"  ---")
    print(f"  total: {total_files} files, {total_bytes/1024/1024:.2f} MB")

    insufficient = [s for s, info in summary.items() if info["files"] < 2]
    if insufficient:
        print(f"\nWARNING: companies with <2 files: {insufficient}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
