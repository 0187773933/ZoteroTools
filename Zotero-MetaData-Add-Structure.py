#!/usr/bin/env python3
import json, re
from pathlib import Path
from collections import defaultdict

COLUMN_GAP = 0.08
LINE_MERGE_Y = 0.012
PARA_BREAK_Y = 0.035

SECTION_WORDS = [
    "abstract","introduction","methods",
    "materials and methods","results",
    "discussion","conclusion","references"
]


# -----------------------------------------------------
# BLOCK
# -----------------------------------------------------
class B:
    def __init__(self, raw, page):
        self.raw=raw
        self.page=page
        self.type=raw["type"]
        self.text=raw.get("embedded_text","").strip()

        x1,y1,x2,y2=raw["bbox_xyn"]
        self.x1,self.y1,self.x2,self.y2=x1,y1,x2,y2
        self.xc=(x1+x2)/2
        self.yc=(y1+y2)/2


# -----------------------------------------------------
# LOAD
# -----------------------------------------------------
def load(att):
    pages=[]
    for i,p in enumerate(att["yolo"]):
        blocks=[B(b,i) for b in p if b["type"]!="abandon" and b.get("embedded_text")]
        pages.append(blocks)
    return pages


# -----------------------------------------------------
# COLUMN SPLIT (auto detect)
# -----------------------------------------------------
def split_columns(page):

    xs=sorted(b.xc for b in page)
    gaps=[xs[i+1]-xs[i] for i in range(len(xs)-1)]
    if not gaps:
        return [page]

    big=max(gaps)
    if big<COLUMN_GAP:
        return [page]

    cut=xs[gaps.index(big)]
    left=[b for b in page if b.xc<=cut]
    right=[b for b in page if b.xc>cut]

    left.sort(key=lambda b:b.yc)
    right.sort(key=lambda b:b.yc)
    return [left,right]


# -----------------------------------------------------
# LINE STITCH
# -----------------------------------------------------
def lines(column):

    column.sort(key=lambda b:b.yc)
    out=[]
    cur=[column[0]]

    for b in column[1:]:
        if abs(b.yc-cur[-1].yc)<LINE_MERGE_Y:
            cur.append(b)
        else:
            out.append(cur)
            cur=[b]
    out.append(cur)

    return [" ".join(x.text for x in l) for l in out]


# -----------------------------------------------------
# PARAGRAPH STITCH
# -----------------------------------------------------
def paragraphs(lines):

    paras=[]
    cur=lines[0]

    for l in lines[1:]:
        if cur.endswith(('.',':',';'))==False:
            cur+=" "+l
        else:
            paras.append(cur)
            cur=l

    paras.append(cur)
    return paras


# -----------------------------------------------------
# SECTION SPLIT
# -----------------------------------------------------
def sectionize(paragraphs):

    sec=defaultdict(list)
    cur="body"

    for p in paragraphs:
        head=p.lower().strip()

        for w in SECTION_WORDS:
            if head.startswith(w):
                cur=w
                p=p[len(w):].strip(" :.-")
                break

        sec[cur].append(p)

    return dict(sec)


# -----------------------------------------------------
# FIGURE PANEL SPLIT
# -----------------------------------------------------
def group_figures(pages):

    figures=[]

    for page in pages:
        caps=[b for b in page if b.type=="figure_caption"]

        for c in caps:
            panels=[]
            for b in page:
                if b.type=="figure" and abs(b.yc-c.yc)<0.07:
                    panels.append(b.raw)

            figures.append({
                "caption":c.text,
                "panels":panels
            })

    return figures


# -----------------------------------------------------
# MAIN
# -----------------------------------------------------
def process(path):

    data=json.loads(Path(path).read_text())

    for att in data["attachments"]:
        pages=load(att)

        all_paragraphs=[]
        for page in pages:
            cols=split_columns(page)

            for col in cols:
                l=lines(col)
                p=paragraphs(l)
                all_paragraphs.extend(p)

        sections=sectionize(all_paragraphs)
        figures=group_figures(pages)

        att["flattened"]={
            "sections":sections,
            "figures":figures
        }

    Path(path).write_text(json.dumps(data,indent=2))
    print("Flattened paper written.")


if __name__=="__main__":
    import sys
    process(sys.argv[1])