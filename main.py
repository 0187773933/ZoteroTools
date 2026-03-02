#!/usr/bin/env python3
import sqlite3, json, re, time, shutil, tempfile, requests
from pathlib import Path
from tqdm import tqdm
import fitz
import torch
from PIL import Image
from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

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
HEADERS = {"User-Agent": "zotero-local-corpus/1.0"}

# ============================================================
# LOAD QWEN
# ============================================================

MODEL_ID = "Qwen/Qwen2.5-VL-7B-Instruct"
print("Loading Qwen model (first run downloads weights)...")

model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
    MODEL_ID,
    torch_dtype=torch.float16,
    device_map="auto"
)

processor = AutoProcessor.from_pretrained(MODEL_ID)

PROMPT = """
Read this scientific paper page and return STRICT JSON:

{
 "title": string or null,
 "authors": [strings],
 "section_headers": [strings],
 "figures": {
    "Figure X": "full caption text"
 }
}

Rules:
Only JSON.
Merge multiline captions.
Ignore references.
"""

# ============================================================
# ZOTERO ACCESS
# ============================================================

def open_snapshot():
    tmp = Path(tempfile.mkdtemp()) / "zotero.sqlite"
    shutil.copy2(ZOTERO_DB, tmp)
    return sqlite3.connect(tmp)

def load_papers():
    conn=open_snapshot()
    c=conn.cursor()
    papers={}

    rows=c.execute("""
        SELECT parentItems.itemID,parentItems.key,childItems.key,
               itemAttachments.path,itemAttachments.contentType
        FROM itemAttachments
        JOIN items childItems ON childItems.itemID=itemAttachments.itemID
        LEFT JOIN items parentItems ON parentItems.itemID=itemAttachments.parentItemID
    """).fetchall()

    for parent_id,parent_key,attach_key,path,ctype in rows:

        if ctype!="application/pdf": continue
        if not path or not path.startswith("storage:"): continue

        pdf=ZOTERO_STORAGE/attach_key/path.replace("storage:","")
        if not pdf.exists(): continue

        doi_row=c.execute("""
            SELECT itemDataValues.value
            FROM itemDataValues
            JOIN itemData ON itemData.valueID=itemDataValues.valueID
            JOIN fields ON fields.fieldID=itemData.fieldID
            WHERE itemData.itemID=? AND fields.fieldName='DOI'
        """,(parent_id,)).fetchone()

        doi=None
        if doi_row and doi_row[0]:
            doi=doi_row[0].replace("https://doi.org/","").replace("http://doi.org/","")

        papers[parent_key]={"doi":doi,"pdf":pdf}

    conn.close()
    return papers

# ============================================================
# OPENALEX CACHE
# ============================================================

def cache_file(name):
    return CACHE_DIR/(name.replace("/","_")+".json")

def oa_get(url):
    cf=cache_file(url)
    if cf.exists(): return json.loads(cf.read_text())

    r=requests.get(url,headers=HEADERS)
    if r.status_code!=200: return None

    data=r.json()
    cf.write_text(json.dumps(data))
    return data

def get_openalex_metadata(doi):
    if not doi: return None,[]
    work=oa_get(OPENALEX+f"https://doi.org/{doi}")
    if not work: return None,[]

    authors=[a["author"]["display_name"] for a in work.get("authorships",[]) if "author" in a]

    meta={
        "title":work.get("display_name"),
        "year":work.get("publication_year"),
        "citations_global":work.get("cited_by_count"),
        "authors":authors
    }

    refs=[]
    for wid in work.get("referenced_works",[]):
        d=oa_get(wid)
        if d:
            refs.append({"title":d.get("display_name"),"year":d.get("publication_year")})

    return meta,refs

# ============================================================
# QWEN EXTRACTION
# ============================================================

def pdf_pages(pdf):
    doc=fitz.open(pdf)
    for page in doc:
        pix=page.get_pixmap(dpi=300)
        yield Image.frombytes("RGB",[pix.width,pix.height],pix.samples)

def run_qwen(img):
    inputs=processor(text=PROMPT,images=img,return_tensors="pt").to(model.device)
    out=model.generate(**inputs,max_new_tokens=1200,do_sample=False)
    txt=processor.batch_decode(out,skip_special_tokens=True)[0]

    start=txt.find("{")
    end=txt.rfind("}")+1
    if start==-1: return {}
    try: return json.loads(txt[start:end])
    except: return {}

def extract_structure(pdf):

    paper={"title":None,"authors":set(),"sections":set(),"figures":{}}

    for img in pdf_pages(pdf):
        data=run_qwen(img)
        if not data: continue

        if data.get("title") and not paper["title"]:
            paper["title"]=data["title"]

        for a in data.get("authors",[]): paper["authors"].add(a)
        for s in data.get("section_headers",[]): paper["sections"].add(s)

        for k,v in data.get("figures",{}).items():
            if k not in paper["figures"]:
                paper["figures"][k]=v

    paper["authors"]=sorted(paper["authors"])
    paper["sections"]=sorted(paper["sections"])
    return paper

# ============================================================
# MAIN
# ============================================================

def main():
    papers=load_papers()
    print("Found",len(papers),"papers")

    for key,data in tqdm(papers.items()):
        outfile=OUT_DIR/f"{key}.json"
        if outfile.exists(): continue

        try:
            structure=extract_structure(data["pdf"])
            meta,refs=get_openalex_metadata(data["doi"])

            obj={
                "zotero_key":key,
                "doi":data["doi"],
                "meta":meta,
                "structure":structure,
                "references":refs
            }

            outfile.write_text(json.dumps(obj,indent=2))

        except Exception as e:
            print("FAILED",key,e)

if __name__=="__main__":
    main()
