#!/usr/bin/env python3
# import deepdoctection as dd
import tempfile
import shutil
from pathlib import Path
import fitz  # pip install pymupdf
import os
import logging
import sys
from tqdm import tqdm
from doclayout_yolo import YOLOv10
import cv2
import json
from PIL import Image
from PIL.PngImagePlugin import PngInfo

# analyzer = dd.get_dd_analyzer()
# pdf = Path("/Users/morpheous/Zotero/storage/FRTHL89X/Luo and Kobayashi - 2025 - BrainLM Enhancing Brain Encoding and Decoding Capabilities with Applications in Multilingual Learni.pdf")
# safe = safe_pdf_copy(pdf)
# doc = analyzer.analyze(path=str(safe))
# for page in doc:
# 	for block in page.layouts:
# 		print(block.category_name, block.bbox)



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

def safe_pdf_copy( original_pdf ):
	tmp = Path( tempfile.mkdtemp() ) / "paper.pdf"
	shutil.copy2( original_pdf , tmp )
	return tmp

def pdf_to_images( pdf_path , dpi=200 , fmt="png" ):
	tmp = Path( tempfile.mkdtemp( prefix="pdf_pages_" ) )
	doc = fitz.open( str( pdf_path ) )
	zoom = dpi / 72.0
	mat = fitz.Matrix( zoom , zoom )
	paths = []

	# testing 1 page only
	# i = 1
	# pix = doc.load_page(i).get_pixmap( matrix=mat , alpha=False )
	# p = tmp / f"page_{i+1:04d}.{fmt}"
	# pix.save( p )
	# paths.append( str( p ) )
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
		# results.append( result )
		# annotated_frame = result[0].plot( pil=True , line_width=5 , font_size=20 )
		# cv2.imshow( f"YOLOv10 Detection - {i+1}" , annotated_frame )
	out_path = pdf_path.with_suffix( ".json" )
	write_json( out_path , page_results )
	fitz_doc.close()

def show_model_classes():
	model = YOLO_MODEL.model  # underlying ultralytics model
	names = model.names

	print("\nModel class list:\n")
	for i, n in names.items():
		print(f"{i:02d}  {n}")

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

# def review_layout(pdf_path, dpi=400):
# 	"""
# 	Re-open detections produced earlier by yolo_pdf() and visually inspect crops.

# 	Assumes:
# 		paper.pdf -> paper.json in same directory
# 	"""

# 	pdf_path = Path(pdf_path)
# 	json_path = pdf_path.with_suffix(".json")

# 	if not json_path.exists():
# 		print(f"[ERROR] Missing json: {json_path}")
# 		return

# 	data = read_json(json_path)

# 	# high resolution re-render
# 	tmpdir, images = pdf_to_images(pdf_path, dpi=dpi)

# 	print(f"\nReviewing: {pdf_path.name}")
# 	print(f"Pages: {len(images)} @ {dpi} DPI")

# 	for page_i, detections in enumerate(data):
# 		if page_i >= len(images):
# 			continue

# 		img = cv2.imread(images[page_i])
# 		if img is None:
# 			continue

# 		H, W = img.shape[:2]

# 		print(f"\nPage {page_i+1} : {len(detections)} objects")

# 		for obj_i, det in enumerate(detections):

# 			if det["type"] != "figure":
# 				text = extract_text_here()

# 			x1n, y1n, x2n, y2n = det["bbox_xyn"]

# 			# denormalize
# 			x1 = int(x1n * W)
# 			y1 = int(y1n * H)
# 			x2 = int(x2n * W)
# 			y2 = int(y2n * H)

# 			# clamp
# 			x1 = max(0, min(W-1, x1))
# 			y1 = max(0, min(H-1, y1))
# 			x2 = max(0, min(W-1, x2))
# 			y2 = max(0, min(H-1, y2))

# 			crop = img[y1:y2, x1:x2]
# 			if crop.size == 0:
# 				continue

# 			preview = img.copy()
# 			cv2.rectangle(preview, (x1,y1), (x2,y2), (0,255,0), 2)
# 			cv2.putText(preview, f"#{obj_i}", (x1, max(20,y1-6)),
# 						cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)

# 			cv2.imshow("PAGE", preview)
# 			cv2.imshow("CROP", crop)

# 			k = cv2.waitKey(0)

# 			if k == ord('q'):
# 				cv2.destroyAllWindows()
# 				return
# 			# if k == ord('s'):
# 			# 	out = pdf_path.with_name(
# 			# 		f"{pdf_path.stem}_p{page_i+1:03d}_{obj_i}.png"
# 			# 	)
# 			# 	cv2.imwrite(str(out), crop)
# 			# 	print("saved", out)

# 	cv2.destroyAllWindows()

def review_layout(pdf_path, dpi=400):

	pdf_path = Path(pdf_path)
	json_path = pdf_path.with_suffix(".json")

	if not json_path.exists():
		print(f"[ERROR] Missing json: {json_path}")
		return

	data = read_json(json_path)

	# ---- OPEN PDF ONCE ----
	doc = fitz.open(str(pdf_path))

	# ---- RASTER ONLY FOR VIEWING ----
	tmpdir, images = pdf_to_images(pdf_path, dpi=dpi)

	print(f"\nReviewing: {pdf_path.name}")
	print(f"Pages: {len(images)} @ {dpi} DPI")

	for page_i, detections in enumerate(data):

		if page_i >= len(images):
			continue

		page = doc[page_i]   # reuse page handle

		img = cv2.imread(images[page_i])
		if img is None:
			continue

		H, W = img.shape[:2]

		print(f"\nPage {page_i+1} : {len(detections)} objects")

		for obj_i, det in enumerate(detections):

			# if det["type"] != "figure":
			# 	text = extract_text_from_page_bbox(page, det["bbox_xyn"], dpi=dpi)
			# 	if text:
			# 		print("\n--- EMBEDDED TEXT ---")
			# 		print(text)
			# 	continue

			x1n, y1n, x2n, y2n = det["bbox_xyn"]

			x1 = int(x1n * W)
			y1 = int(y1n * H)
			x2 = int(x2n * W)
			y2 = int(y2n * H)

			x1 = max(0, min(W-1, x1))
			y1 = max(0, min(H-1, y1))
			x2 = max(0, min(W-1, x2))
			y2 = max(0, min(H-1, y2))

			crop = img[y1:y2, x1:x2]
			if crop.size == 0:
				continue

			preview = img.copy()
			cv2.rectangle(preview, (x1,y1), (x2,y2), (0,255,0), 2)
			cv2.putText(preview, f"FIG #{obj_i}", (x1, max(20,y1-6)),
						cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)

			cv2.imshow("PAGE", preview)
			cv2.imshow("FIGURE", crop)

			k = cv2.waitKey(0)

			if k == ord('q'):
				cv2.destroyAllWindows()
				doc.close()
				return

	cv2.destroyAllWindows()
	doc.close()

# 00  title
# 01  plain text
# 02  abandon
# 03  figure
# 04  figure_caption
# 05  table
# 06  table_caption
# 07  table_footnote
# 08  isolate_formula
# 09  formula_caption
if __name__ == "__main__":
	# yolo_pdf( sys.argv[ 1 ] )
	review_layout( sys.argv[ 1 ] )
