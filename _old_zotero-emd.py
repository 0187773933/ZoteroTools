#!/usr/bin/env python3
import sqlite3
import json
import re
import time
import shutil
import tempfile
import requests
from pathlib import Path
from tqdm import tqdm
import fitz  # PyMuPDF

# ============================================================
# CONFIG
# ============================================================

HOME = Path.home()

ZOTERO_DB = HOME / "Zotero" / "zotero.sqlite"
ZOTERO_STORAGE = HOME / "Zotero" / "storage"

OUT_DIR = HOME / ".zotero-cg" / "papers"
CACHE_DIR = HOME / ".zotero-cg" / "openalex_cache"

OUT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

OPENALEX = "https://api.openalex.org/works/"

API_KEY = "asdf"
HEADERS = {"User-Agent": "zotero-local-corpus/1.0"}

MAX_RPS = 50
SLEEP = 1 / MAX_RPS
MAX_RETRY = 6

# ============================================================
# DB ACCESS
# ============================================================

def open_snapshot():
    tmp = Path(tempfile.mkdtemp()) / "zotero.sqlite"
    shutil.copy2(ZOTERO_DB, tmp)
    return sqlite3.connect(tmp)

def load_papers():

    conn = open_snapshot()
    c = conn.cursor()

    papers = {}

    rows = c.execute("""
        SELECT
            parentItems.itemID,
            parentItems.key,
            childItems.key,
            itemAttachments.path,
            itemAttachments.contentType
        FROM itemAttachments
        JOIN items childItems ON childItems.itemID = itemAttachments.itemID
        LEFT JOIN items parentItems ON parentItems.itemID = itemAttachments.parentItemID
    """).fetchall()

    for parent_id, parent_key, attach_key, path, ctype in rows:

        if ctype != "application/pdf":
            continue

        if not path or not path.startswith("storage:"):
            continue

        filename = path.replace("storage:", "")
        pdf = ZOTERO_STORAGE / attach_key / filename

        if not pdf.exists():
            continue

        # fetch DOI from parent item
        doi_row = c.execute("""
            SELECT itemDataValues.value
            FROM itemDataValues
            JOIN itemData ON itemData.valueID=itemDataValues.valueID
            JOIN fields ON fields.fieldID=itemData.fieldID
            WHERE itemData.itemID=? AND fields.fieldName='DOI'
        """, (parent_id,)).fetchone()

        doi = None
        if doi_row and doi_row[0]:
            doi = doi_row[0].strip().replace("https://doi.org/","").replace("http://doi.org/","")

        papers[parent_key] = {
            "doi": doi,
            "pdf": pdf
        }

    conn.close()
    return papers
# ============================================================
# OPENALEX (cached + throttled)
# ============================================================

def cache_file(name):
    safe = name.replace("/", "_")
    return CACHE_DIR / f"{safe}.json"

def oa_get(url):

    cf = cache_file(url)
    if cf.exists():
        return json.loads(cf.read_text())

    for attempt in range(MAX_RETRY):

        r = requests.get(url, params={"api_key": API_KEY}, headers=HEADERS)

        if r.status_code == 200:
            data = r.json()
            cf.write_text(json.dumps(data))
            time.sleep(SLEEP)
            return data

        if r.status_code == 429:
            retry = int(r.headers.get("Retry-After", 2))
            wait = retry * (attempt + 1)
            print("rate limited, sleeping", wait)
            time.sleep(wait)
            continue

        return None

    return None

def get_openalex_metadata(doi):

    if not doi:
        return None, []

    work = oa_get(OPENALEX + f"https://doi.org/{doi}")
    if not work:
        return None, []

    meta = {
        "title": work.get("display_name"),
        "year": work.get("publication_year"),
        "citations_global": work.get("cited_by_count"),
        "openalex_id": work.get("id")
    }

    refs = []
    for wid in work.get("referenced_works", []):
        data = oa_get(wid)
        if not data:
            continue
        refs.append({
            "title": data.get("display_name"),
            "year": data.get("publication_year"),
            "citations_global": data.get("cited_by_count"),
            "openalex_id": wid
        })

    return meta, refs

# ============================================================
# PDF PARSING
# ============================================================

SECTION_PATTERNS = {
    "abstract": r"\babstract\b",
    "methods": r"\b(methods?|materials and methods?|experimental procedures?)\b",
    "results": r"\bresults?\b",
    "discussion": r"\bdiscussion\b"
}

FIG_CAP = re.compile(r"(figure|fig\.?)\s*\d+[a-z]?:?.{0,400}", re.I)
FIG_MENTION = re.compile(r"(figure|fig\.?)\s*\d+[a-z]?", re.I)

def extract_text(pdf):
    doc = fitz.open(pdf)
    blocks=[]
    for page in doc:
        b=page.get_text("blocks")
        b.sort(key=lambda x:(x[1],x[0]))
        blocks += [x[4] for x in b]
    return "\n".join(blocks)

def split_sections(text):
    low=text.lower()
    idx={}
    for name,pat in SECTION_PATTERNS.items():
        m=re.search(pat,low)
        if m: idx[name]=m.start()

    out={k:"" for k in SECTION_PATTERNS}
    order=sorted(idx.items(),key=lambda x:x[1])

    for i,(name,start) in enumerate(order):
        end=len(text)
        if i+1<len(order): end=order[i+1][1]
        out[name]=text[start:end].strip()

    return out

def figures(text):
    caps=list(set(m.group(0) for m in FIG_CAP.finditer(text)))
    mentions=list(set(m.group(0) for m in FIG_MENTION.finditer(text)))
    return caps,mentions

def guess_title(text):
    lines=[l.strip() for l in text.split("\n")[:30] if len(l.strip())>20]
    return max(lines,key=len) if lines else ""

# ============================================================
# MAIN
# ============================================================

def main():

    papers=load_papers()
    print("Found",len(papers),"papers")

    for key,data in tqdm(papers.items()):

        outfile=OUT_DIR/f"{key}.json"
        if outfile.exists():
            continue

        try:
            text=extract_text(data["pdf"])
            sections=split_sections(text)
            caps,mentions=figures(text)
            meta,refs=get_openalex_metadata(data["doi"])

            obj={
                "zotero_key":key,
                "doi":data["doi"],
                "meta":meta,
                "sections":sections,
                "figure_captions":caps,
                "figure_mentions":mentions,
                "references":refs,
                "fulltext":text
            }

            outfile.write_text(json.dumps(obj,indent=2))

        except Exception as e:
            print("FAILED",key,e)

if __name__=="__main__":
    main()