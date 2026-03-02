#!/usr/bin/env python3
import sqlite3
import json
import re
import time
import shutil
import tempfile
from pathlib import Path
from tqdm import tqdm
import os
import requests

import fitz
from doclayout_yolo import YOLOv10
import cv2
import logging
from PIL import Image
from PIL.PngImagePlugin import PngInfo


HOME = Path.home()
ZOTERO_DB = HOME / "Zotero" / "zotero.sqlite"
ZOTERO_STORAGE = HOME / "Zotero" / "storage"

MAIN_DIR = HOME / ".zotero-cg"
META_DATA_DIR = MAIN_DIR.joinpath( "meta-data" )
META_DATA_DIR.mkdir( parents=True , exist_ok=True )

# kill ultralytics + yolo logging
logging.getLogger( "ultralytics" ).setLevel( logging.ERROR )
logging.getLogger( "doclayout_yolo" ).setLevel( logging.ERROR )

# kill tqdm bars inside ultralytics
os.environ[ "YOLO_VERBOSE" ] = "False"
os.environ[ "ULTRALYTICS_VERBOSE" ] = "False"

# https://huggingface.co/juliozhao/DocLayout-YOLO-DocStructBench/blob/main/doclayout_yolo_docstructbench_imgsz1024.pt
YOLO_MODEL_PATH = "doclayout_yolo_docstructbench_imgsz1024.pt"
YOLO_MODEL = YOLOv10( YOLO_MODEL_PATH )

def write_json( file_path , python_object ):
	with open( file_path , 'w', encoding='utf-8' ) as f:
		json.dump( python_object , f , ensure_ascii=False , indent=4 )

def read_json( file_path ):
	with open( file_path ) as f:
		return json.load( f )

def get_meta_data_file_paths():
	_files = META_DATA_DIR.glob( '**/*' )
	_files = [ x for x in _files if x.is_file() ]
	_files = [ x for x in _files if x.suffix == ".json" ]
	return _files

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

def extract_text_from_page_bbox( page , bbox_xyn , dpi=400 ):

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

MAX_PAGES = 30
def yolo_pdf( input_path ):
	pdf_path = Path( input_path )
	tmpdir , images = pdf_to_images( pdf_path )
	images = images[ 0 : min( len( images ) , MAX_PAGES ) ]
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
	fitz_doc.close()
	return page_results

def main():
	zmd_fp = get_meta_data_file_paths()
	for item_index , zotero_item_fp in enumerate( tqdm( zmd_fp , desc="Adding YOLO Doc Layout Info" ) ):
		zotero_item = read_json( str( zotero_item_fp ) )
		if "doi" not in zotero_item:
			continue
		if "attachments" not in zotero_item:
			continue
		for attachment_index , attachment in enumerate( zotero_item[ "attachments" ] ):
			if attachment[ "contentType" ] != "application/pdf":
				continue
			if "yolo" in attachment:
				continue
			print( f"\nProcessing {item_index+1}/{len(zmd_fp)}: {zotero_item['key']} : Attachment {attachment_index}/{len(zotero_item[ 'attachments' ])}" )
			attachment[ "yolo" ] = yolo_pdf( attachment[ "path" ] )
		write_json( str( zotero_item_fp ) , zotero_item )

if __name__=="__main__":
	main()