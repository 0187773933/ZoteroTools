#!/usr/bin/env python3
import sqlite3, json, re, time, shutil, tempfile, requests
from pathlib import Path
from tqdm import tqdm
import fitz
import torch
import os
from PIL import Image
from doclayout_yolo import YOLOv10
import cv2
import logging
import json
from PIL import Image
from PIL.PngImagePlugin import PngInfo


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

# kill ultralytics + yolo logging
logging.getLogger( "ultralytics" ).setLevel( logging.ERROR )
logging.getLogger( "doclayout_yolo" ).setLevel( logging.ERROR )

# kill tqdm bars inside ultralytics
os.environ[ "YOLO_VERBOSE" ] = "False"
os.environ[ "ULTRALYTICS_VERBOSE" ] = "False"

# https://huggingface.co/juliozhao/DocLayout-YOLO-DocStructBench/blob/main/doclayout_yolo_docstructbench_imgsz1024.pt
YOLO_MODEL_PATH = "/Users/morpheous/WORKSPACE/MODELS/doclayout_yolo_docstructbench_imgsz1024.pt"
YOLO_MODEL = YOLOv10( YOLO_MODEL_PATH )

def write_json( file_path , python_object ):
    with open( file_path , 'w', encoding='utf-8' ) as f:
        json.dump( python_object , f , ensure_ascii=False , indent=4 )

def read_json( file_path ):
    with open( file_path ) as f:
        return json.load( f )

def open_snapshot():
	tmp = Path( tempfile.mkdtemp() ) / "zotero.sqlite"
	shutil.copy2( ZOTERO_DB , tmp )
	return sqlite3.connect( tmp )

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

def extract_text_from_page_bbox(page, bbox_xyn, dpi=400):
    """
    Extract embedded text from a bbox using an already-open PyMuPDF page
    """

    page_rect = page.rect
    pdf_w, pdf_h = page_rect.width, page_rect.height

    zoom = dpi / 72.0
    img_w = pdf_w * zoom
    img_h = pdf_h * zoom

    x1n, y1n, x2n, y2n = bbox_xyn

    rect = fitz.Rect(
        (x1n * img_w) / zoom,
        (y1n * img_h) / zoom,
        (x2n * img_w) / zoom,
        (y2n * img_h) / zoom
    )

    text = page.get_text("text", clip=rect)
    return text.strip()

def get_work_from_openalex( doi ):

	# cached = load_cache(doi)
	# if cached:
	# 	return cached

	url = BASE_URL + f"https://doi.org/{doi}"
	params = {"api_key": API_KEY}
	while True:
		r = requests.get(url, params=params, headers=HEADERS)
		if r.status_code == 200:
			data = r.json()
			save_cache(doi, data)
			return data

		elif r.status_code == 429:
			retry = int(r.headers.get("Retry-After", 5))
			print(f"\nRate limited. Sleeping {retry}s")
			time.sleep(retry)
		else:
			return None




def pdf_to_images( pdf_path , dpi=200 , fmt="png" ):
	tmp = Path( tempfile.mkdtemp( prefix="pdf_pages_" ) )
	doc = fitz.open( str( pdf_path ) )
	zoom = dpi / 72.0
	mat = fitz.Matrix( zoom , zoom )
	paths = []
	for i in tqdm( range( len( doc ) ) , desc="Rasterizing PDF" , unit="page" ):
		pix = doc.load_page(i).get_pixmap( matrix=mat , alpha=False )
		p = tmp / f"page_{i+1:04d}.{fmt}"
		pix.save( p )
		paths.append( str( p ) )
	doc.close()
	return tmp , paths

def yolo_pdf( input_path ):
	pdf_path = Path( input_path )
	tmpdir , images = pdf_to_images( pdf_path )
	page_results = []
	fitz_doc = fitz.open( input_path )
	for page_index , img_path in enumerate( tqdm( images , desc="Processing pages" ) ):
		detection = YOLO_MODEL.predict(
			img_path ,
			imgsz=1024 ,
			conf=0.2 ,
			# device="cpu" ,
		)
		if len( detection ) == 0:
			continue
		detection = detection[ 0 ]
		if len( detection.boxes ) == 0:
			continue
		# https://github.com/opendatalab/DocLayout-YOLO/blob/main/doclayout_yolo/engine/results.py#L433
		names = detection.names
		boxes = detection.boxes
		xyxyn = boxes.xyxyn
		conf  = boxes.conf
		cls   = boxes.cls
		page_result = []
		for i in range( len( boxes ) ):
			class_id = int( cls[ i ] )
			class_name = names[ class_id ]
			bbox_xyn = xyxyn[ i ].tolist()
			score = float( conf[ i ] )
			result = {
				"type": class_name ,
				"bbox_xyn": bbox_xyn ,
				"confidence": score
			}
			if class_name != "figure":
				text = extract_text_from_page_bbox( fitz_doc[ page_index ] , bbox_xyn , dpi=400 )
				if text:
					result["embedded_text"] = text
			page_result.append( result )
		page_results.append( page_result )
	out_path = pdf_path.with_suffix( ".json" )
	write_json( out_path , page_results )
	fitz_doc.close()

def main():
	papers=load_papers()
	print("Found",len(papers),"papers")

	for key,data in tqdm(papers.items()):
		outfile=OUT_DIR/f"{key}.json"
		if outfile.exists(): continue
		try:
			meta,refs=get_openalex_metadata(data["doi"])

			obj={
				"zotero_key":key,
				"doi":data["doi"],
				"meta":meta,
				"references":refs ,
				"pdf": str( data["pdf"] )
			}
			write_json( str( outfile ) , obj )

		except Exception as e:
			print("FAILED",key,e)

if __name__=="__main__":
	main()
