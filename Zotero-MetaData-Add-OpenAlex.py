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

HOME = Path.home()
ZOTERO_DB = HOME / "Zotero" / "zotero.sqlite"
ZOTERO_STORAGE = HOME / "Zotero" / "storage"

MAIN_DIR = HOME / ".zotero-cg"
META_DATA_DIR = MAIN_DIR.joinpath( "meta-data" )
META_DATA_DIR.mkdir( parents=True , exist_ok=True )

API_KEY = "bdDEtP2Jp4MhNyiG42Ckzv"
BASE_URL = "https://api.openalex.org/works/"
HEADERS = {"User-Agent": "zotero-citation-analyzer/1.0"}
def get_work_from_openalex( doi ):

	url = BASE_URL + f"https://doi.org/{doi}"
	params = {"api_key": API_KEY}

	while True:
		r = requests.get(url, params=params, headers=HEADERS)

		if r.status_code == 200:
			data = r.json()
			return data

		elif r.status_code == 429:
			retry = int(r.headers.get("Retry-After", 5))
			print(f"\nRate limited. Sleeping {retry}s")
			time.sleep(retry)

		else:
			return None

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

def main():
	zmd_fp = get_meta_data_file_paths()
	for item_index , zotero_item_fp in enumerate( tqdm( zmd_fp , desc="Collecting OpenAlex Info" ) ):
		zotero_item = read_json( str( zotero_item_fp ) )
		if "doi" not in zotero_item:
			continue
		if "openalex" in zotero_item:
			continue
		oa_info = get_work_from_openalex( zotero_item["doi"] )
		if oa_info is None:
			continue
		zotero_item["openalex"] = oa_info
		write_json( str( zotero_item_fp ) , zotero_item )

if __name__=="__main__":
	main()