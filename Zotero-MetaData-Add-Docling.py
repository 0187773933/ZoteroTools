#!/usr/bin/env python3
import sys
import json
from pprint import pprint
from pathlib import Path
from tqdm import tqdm
from docling.document_converter import DocumentConverter

HOME = Path.home()
ZOTERO_DB = HOME / "Zotero" / "zotero.sqlite"
ZOTERO_STORAGE = HOME / "Zotero" / "storage"

MAIN_DIR = HOME / ".zotero-cg"
META_DATA_DIR = MAIN_DIR.joinpath( "meta-data" )
META_DATA_DIR.mkdir( parents=True , exist_ok=True )

def write_json( file_path , python_object ):
    with open( file_path , 'w' , encoding='utf-8' ) as f:
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

	converter = DocumentConverter()

	for item_index , zotero_item_fp in enumerate( tqdm( zmd_fp , desc="Adding Docling Layout Info" ) ):
		zotero_item = read_json( str( zotero_item_fp ) )
		if "doi" not in zotero_item:
			continue
		if "attachments" not in zotero_item:
			continue
		for attachment_index , attachment in enumerate( zotero_item[ "attachments" ] ):
			if attachment[ "contentType" ] != "application/pdf":
				continue
			if "docling_dict" in attachment:
				continue
			print( f"\nProcessing {item_index+1}/{len(zmd_fp)}: {zotero_item['key']} : Attachment {attachment_index}/{len(zotero_item[ 'attachments' ])}" )
			result = converter.convert( attachment[ "path" ] )
			_dict = result.document.export_to_dict()
			_md = result.document.export_to_markdown()
			attachment[ "docling_dict" ] = _dict
			attachment[ "docling_md" ] = _md
		write_json( str( zotero_item_fp ) , zotero_item )

if __name__ == "__main__":
    main()