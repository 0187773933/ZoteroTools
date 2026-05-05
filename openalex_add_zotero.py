#!/usr/bin/env python3
import sys
import time
from pathlib import Path
import requests
from pprint import pprint
import utils
import json
from tqdm import tqdm
import pypdfium2 as pdfium
import tempfile
import cv2
from deskew import determine_skew

API_KEY = "bdDEtP2Jp4MhNyiG42Ckzv"
BASE_URL = "https://api.openalex.org/works/"
HEADERS = { "User-Agent": "zotero-citation-analyzer/1.0" }
HOME = Path.home()
MAIN_DIR = HOME / ".zotero-cg"
META_DATA_DIR = MAIN_DIR / "meta-data"
YOLO_DATA_DIR = MAIN_DIR / "yolo"
YOLO_DATA_DIR.mkdir( parents=True , exist_ok=True )
MAX_PAGES = 30


YOLO_MODEL_PATH = "./doclayout_yolo_docstructbench_imgsz1024.pt"
YOLO_MODEL = None

def _load_yolo_model():
	global YOLO_MODEL
	if not YOLO_MODEL:
		from doclayout_yolo import YOLOv10
		YOLO_MODEL = YOLOv10( YOLO_MODEL_PATH )

YOLO_MODEL_IMG_SIZE = 1024
# YOLO_MODEL_CONFIDENCE = 0.2
YOLO_MODEL_CONFIDENCE = 0.1

DESKEW = True
DESKEW_THRESHOLD = 0.5
POPPLER_PATH = None
DPI = 400

OCR_ENGINE = None

def pdf_to_images( pdf_path , page_index=None , debug=False ):
	"""
	page_index: 0-based. -1 = last page. None = all pages.
	"""
	tmp = Path(tempfile.mkdtemp(prefix="pdf_pages_"))
	paths = []
	scale = DPI / 72.0 # 72 is pdf-spec for 1 inch

	try:
		with pdfium.PdfDocument(str(pdf_path)) as pdf:
			pdf.init_forms()
			n = len(pdf)

			if page_index is None:
				indices = list(range(n))
			elif page_index == -1:
				indices = [n - 1]
			else:
				if not 0 <= page_index < n:
					raise IndexError(f"page_index {page_index} out of range for {n}-page PDF")
				indices = [page_index]

			if debug:
				print(f"[pdfium] {Path(pdf_path).name}: {n} pages, rendering {indices}")

			for idx in indices:
				page = pdf[idx]
				bitmap = page.render(scale=scale)
				pil_img = bitmap.to_pil()
				p = tmp / f"page_{idx + 1:04d}.png"
				pil_img.save(p)
				paths.append(str(p))
				page.close()
	except Exception as e:
		tqdm.write(f"⚠ Error processing {Path(pdf_path).name}: {type(e).__name__}: {e}")
		return []

	return paths[0] if page_index is not None else paths

def get_skew_angle( image ):
	gray = cv2.cvtColor( image , cv2.COLOR_BGR2GRAY )
	thresh = cv2.threshold(
		gray , 0 , 255 ,
		cv2.THRESH_BINARY | cv2.THRESH_OTSU
	)[ 1 ]
	angle = determine_skew( thresh )
	return angle

# https://github.com/sbrunner/deskew
def deskew( image , angle , h , w ):
	# compute new bounds to avoid cropping
	center = ( w // 2 , h // 2 )
	angle_rad = math.radians( angle )
	new_w = abs( np.sin( angle_rad ) * h ) + abs( np.cos( angle_rad ) * w )
	new_h = abs( np.sin( angle_rad ) * w ) + abs( np.cos( angle_rad ) * h )

	M = cv2.getRotationMatrix2D( center , angle , 1.0 )

	# shift image to center in new canvas
	M[ 0 , 2 ] += ( new_w - w ) / 2
	M[ 1 , 2 ] += ( new_h - h ) / 2

	return cv2.warpAffine(
		image ,
		M ,
		( int( round( new_w ) ) , int( round( new_h ) ) ) ,
		flags=cv2.INTER_CUBIC ,
		borderMode=cv2.BORDER_REPLICATE
	)

def get_bbox_area( bbox ):
	x1 , y1 , x2 , y2 = bbox
	return ( x2 - x1 ) * ( y2 - y1 )

def yolo_img( img ):
	global YOLO_MODEL
	_load_yolo_model()
	detection = YOLO_MODEL.predict(
		img ,
		imgsz=YOLO_MODEL_IMG_SIZE ,
		conf=YOLO_MODEL_CONFIDENCE ,
		verbose=False ,
	)
	page_result = []
	if len( detection ) == 0:
		return page_result

	detection = detection[ 0 ]
	if len( detection.boxes ) == 0:
		return page_result

	names = detection.names
	boxes = detection.boxes

	h , w = img.shape[ :2 ]
	for i in range( len( boxes ) ):
		class_id = int( boxes.cls[ i ] )
		class_name = names[ class_id ]
		# normalized → pixel coords
		x1 , y1 , x2 , y2 = boxes.xyxyn[ i ].tolist()
		x1 = int( x1 * w )
		x2 = int( x2 * w )
		y1 = int( y1 * h )
		y2 = int( y2 * h )
		# clamp
		x1 = max( 0 , x1 )
		y1 = max( 0 , y1 )
		x2 = min( w , x2 )
		y2 = min( h , y2 )
		_bbox = [x1, y1, x2, y2]
		_bbox_area = get_bbox_area( _bbox )
		result = {
			"type": class_name,
			"bbox": _bbox ,
			"bbox_area": _bbox_area ,
			"confidence": float( boxes.conf[ i ] ),
		}
		page_result.append( result )
	return page_result

def yolo_attachment( pdf_path , max_pages=MAX_PAGES ):
	pages = pdf_to_images( pdf_path )
	pages = pages[ :max_pages ]
	page_results = []
	for p , page in enumerate( tqdm( pages , desc=f"Pages ({Path(pdf_path).name})" , leave=True ) ):
		original = cv2.imread( page )
		H , W = original.shape[ :2 ]
		skew_angle = get_skew_angle( original )
		if skew_angle:
			if abs( skew_angle ) > DESKEW_THRESHOLD:
				tqdm.write( f"  Deskewing page {p+1}: {skew_angle:.2f}°" )
				original = deskew( original , skew_angle , H , W )
		result = yolo_img( original )
		page_results.append( result )
	return page_results

class OpenAlexYoloAddon:
	def __init__( self , options={} ):
		self.options = options
		self.storage_dir = YOLO_DATA_DIR
		self.snapshot = utils.zotero_take_snapshot()

	def update_cache( self ):
		_values = self.snapshot.values()
		total_values = len( _values )
		for i , value in enumerate( tqdm( _values , desc="Items" , unit="item" , total=total_values ) ):
			_doi = value.get( "doi" )
			if not _doi:
				continue
			_doi = utils.normalize_doi( _doi )
			_doi_b64 = utils.base64_encode( _doi )
			_cache_fp = self.storage_dir.joinpath( f"{_doi_b64}.json" )
			if _cache_fp.exists():
				continue
			attachements = {}
			for a , attachement in enumerate( value[ "attachments" ] ):
				if "abs_path" not in attachement:
					continue
				if not attachement[ "abs_path" ].endswith( ".pdf" ):
					continue
				yolo_result = yolo_attachment( attachement[ "abs_path" ] )
				attachements[ attachement[ "key" ] ] = yolo_result
			utils.write_json( str( _cache_fp ) , attachements )

if __name__ == "__main__":
	x = OpenAlexYoloAddon()
	x.update_cache()