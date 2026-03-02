from docling.document_converter import DocumentConverter
from pprint import pprint

import json
def write_json( file_path , python_object ):
    with open( file_path , 'w', encoding='utf-8' ) as f:
        json.dump( python_object , f , ensure_ascii=False , indent=4 )

def read_json( file_path ):
    with open( file_path ) as f:
        return json.load( f )

source = "/Users/morpheous/Zotero/storage/ASPAG88U/Yao - 2025 - Rethinking inner speech through linguistic active inference.pdf"
converter = DocumentConverter()
result = converter.convert(source)
pprint( result.document.export_to_element_tree() )
# print( result.document.export_to_markdown() )
# doc = result.document.export_to_dict()
# write_json( "test_docling_output.json" , doc )
# pprint( doc )