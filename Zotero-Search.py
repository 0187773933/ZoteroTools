#!/usr/bin/env python3
import sqlite3
import shutil
import tempfile
from pathlib import Path
import re
import fitz
from tqdm import tqdm
from html import escape

# =========================
# CONFIG
# =========================

ZOTERO_DB = Path.home() / "Zotero" / "zotero.sqlite"
ZOTERO_STORAGE = Path.home() / "Zotero" / "storage"
OUT_HTML = Path("zotero_temporal_decoders.html")

# ---- semantic tiers ----

TEMPORAL_TERMS = [
    "time series",
    "temporal decoding",
    "temporal generalization",
    "sliding window",
    "autoregressive",
]

MODEL_TERMS = [
    "transformer",
    "rnn",
    "cnn",
    "lstm",
    "gru",
    "hidden state",
]

DECODER_TERMS = [
    "decode",
    "decoding",
    "decoder",
]

METHOD_HINTS = [
    "method",
    "methods",
    "model",
    "architecture",
    "training",
]

CONTEXT_CHARS = 200

# =========================
# DB SAFE OPEN
# =========================

def open_sqlite_safely(db_path: Path) -> sqlite3.Connection:
    tmp = Path(tempfile.mkstemp(suffix=".sqlite")[1])
    shutil.copy(db_path, tmp)
    return sqlite3.connect(tmp)

# =========================
# GET ITEMS + PDF PATHS + YEAR + DOI
# =========================

def get_items_with_pdfs(conn):
    cur = conn.cursor()

    cur.execute("""
    SELECT
        parent.key        AS parent_key,
        attach.key        AS attach_key,
        parent.dateAdded  AS dateAdded,
        MAX(CASE WHEN f.fieldName='date' THEN v.value END) AS date,
        MAX(CASE WHEN f.fieldName='year' THEN v.value END) AS year,
        MAX(CASE WHEN f.fieldName='DOI' THEN v.value END)  AS doi
    FROM items AS parent
    JOIN itemAttachments AS ia ON ia.parentItemID = parent.itemID
    JOIN items AS attach ON attach.itemID = ia.itemID
    LEFT JOIN itemData AS id ON id.itemID = parent.itemID
    LEFT JOIN itemDataValues AS v ON v.valueID = id.valueID
    LEFT JOIN fields AS f ON f.fieldID = id.fieldID
    WHERE ia.contentType = 'application/pdf'
    GROUP BY parent.itemID, attach.itemID
    """)

    results = []

    for parent_key, attach_key, date_added, date, year, doi in cur.fetchall():
        folder = ZOTERO_STORAGE / attach_key
        if not folder.exists():
            continue

        pdfs = list(folder.glob("*.pdf"))
        if not pdfs:
            continue

        resolved_year = 0
        if year and year.isdigit():
            resolved_year = int(year)
        elif date:
            m = re.search(r"\d{4}", date)
            if m:
                resolved_year = int(m.group())
        elif date_added:
            resolved_year = int(date_added[:4])

        results.append({
            "key": parent_key,
            "pdf": pdfs[0],
            "year": resolved_year,
            "doi": doi.strip() if doi else None,
        })

    return results

# =========================
# PDF SEARCH (SEMANTIC + DEDUPED)
# =========================

def search_pdf(pdf_path: Path):
    hits = []
    seen_pages = set()

    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return hits

    for page_num in range(len(doc)):
        text = doc[page_num].get_text().lower()

        if page_num in seen_pages:
            continue

        if "references" in text[:800]:
            continue

        if not any(h in text[:1200] for h in METHOD_HINTS):
            continue

        temporal_hit = [t for t in TEMPORAL_TERMS if t in text]
        model_hit = [m for m in MODEL_TERMS if m in text]
        decoder_hit = [d for d in DECODER_TERMS if d in text]

        if not (temporal_hit and model_hit and decoder_hit):
            continue

        seen_pages.add(page_num)

        snippet_start = min(
            (text.find(w) for w in temporal_hit + model_hit + decoder_hit if w in text),
            default=0,
        )

        start = max(0, snippet_start - CONTEXT_CHARS)
        end = min(len(text), snippet_start + CONTEXT_CHARS)

        hits.append({
            "page": page_num + 1,
            "temporal": temporal_hit,
            "model": model_hit,
            "decoder": decoder_hit,
            "snippet": text[start:end].replace("\n", " "),
        })

    return hits

# =========================
# HTML OUTPUT
# =========================

def write_html(results):
    rows = []

    for r in results:
        blocks = ""
        for h in r["hits"]:
            blocks += f"""
            <details>
              <summary>
                Page {h['page']} |
                temporal={', '.join(h['temporal'])} |
                model={', '.join(h['model'])}
              </summary>
              <pre>{escape(h['snippet'])}</pre>
            </details>
            """

        if r["doi"]:
            doi_html = (
                f'<a href="https://doi.org/{r["doi"]}" target="_blank">(1)</a> '
                f'<a href="https://doi-org.ezproxy.libraries.wright.edu/{r["doi"]}" target="_blank">(2)</a>'
            )
        else:
            doi_html = "—"

        rows.append(f"""
        <tr>
          <td>{r['year']}</td>
          <td><a href="file://{r['pdf']}" target="_blank">{escape(r['pdf'].name)}</a></td>
          <td>{doi_html}</td>
          <td>{blocks}</td>
        </tr>
        """)

    html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Temporal fMRI Decoder Papers</title>
<style>
body {{ font-family: system-ui, sans-serif; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: 8px; vertical-align: top; }}
th {{ background: #f0f0f0; }}
pre {{ white-space: pre-wrap; }}
details {{ margin-bottom: 6px; }}
</style>
</head>
<body>

<h1>Temporal / Sequence fMRI Decoder Papers</h1>
<p>Strict semantic filter: temporal × model × decoder (same page, methods-biased)</p>

<table>
<tr>
  <th>Year</th>
  <th>PDF</th>
  <th>DOI</th>
  <th>Evidence</th>
</tr>
{''.join(rows)}
</table>

</body>
</html>
"""
    OUT_HTML.write_text(html, encoding="utf-8")

# =========================
# MAIN
# =========================

def main():
    conn = open_sqlite_safely(ZOTERO_DB)
    try:
        items = get_items_with_pdfs(conn)
    finally:
        conn.close()

    print(f"\nScanning {len(items)} PDFs\n")

    results = []

    for item in tqdm(items, desc="PDFs", unit="pdf"):
        hits = search_pdf(item["pdf"])
        if hits:
            print(item["pdf"])
            item["hits"] = hits
            results.append(item)

    results.sort(key=lambda r: r["year"], reverse=True)

    write_html(results)

    print(f"\nDONE.")
    print(f"HTML written to: {OUT_HTML.resolve()}")
    print(f"Matched papers: {len(results)}")

if __name__ == "__main__":
    main()
