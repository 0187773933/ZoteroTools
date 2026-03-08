#!/usr/bin/env python3
import time
from pathlib import Path
import requests
from pprint import pprint
import utils
from tqdm import tqdm

API_KEY = "bdDEtP2Jp4MhNyiG42Ckzv"
BASE_URL = "https://api.openalex.org/works/"
HEADERS = { "User-Agent": "zotero-citation-analyzer/1.0" }
HOME = Path.home()
MAIN_DIR = HOME / ".zotero-cg"
META_DATA_DIR = MAIN_DIR / "meta-data"

MAX_RETRIES = 10

class OpenAlex:
	def __init__( self , options={} ):
		self.options = options
		self.api_key = options.get( "api_key" , API_KEY )
		self.base_url = options.get( "base_url" , BASE_URL )
		self.headers = options.get( "headers" , HEADERS )
		self.params = { "api_key": self.api_key }
		self.meta_data_dir = options.get( "meta_data_dir" , META_DATA_DIR )
		self.storage_dir = self.meta_data_dir.joinpath( "openalex" )
		self.storage_dir.mkdir( parents=True , exist_ok=True )
		self.references_dir = self.storage_dir.joinpath( "references" )
		self.references_dir.mkdir( parents=True , exist_ok=True )

	def get_zotero_id( self , zotero_item ):
		_save_path = self.storage_dir.joinpath( f"{zotero_item['key']}.json" )
		return zotero_item.get( "key" )

	def api_get_doi( self , doi ):
		url = self.base_url + f"https://doi.org/{doi}"
		while True:
			r = requests.get( url , params=self.params , headers=self.headers )
			if r.status_code == 200:
				data = r.json()
				return data
			elif r.status_code == 429:
				retry = int( r.headers.get( "Retry-After" , 5 ) )
				print( f"\nRate limited. Sleeping {retry}s" )
				time.sleep( retry )
			else:
				return None

	def api_get_id( self , open_alex_id ):
		wid = open_alex_id.split( "/" )[ -1 ]
		url = BASE_URL + wid
		for attempt in range( MAX_RETRIES ):
			try:
				r = requests.get(
					url,
					params=self.params,
					headers=self.headers,
					timeout=30
				)
				if r.status_code == 200:
					return r.json()
				elif r.status_code == 429:
					retry = int(r.headers.get("Retry-After", 5))
					print(f"\nRate limited resolving refs. Sleeping {retry}s")
					time.sleep(retry)
					continue

				else:
					# print(f"Error fetching {wid}: HTTP {r.status_code}")
					return None
			except requests.exceptions.RequestException as e:
				wait = min(2 ** attempt, 60)
				print(f"\nNetwork error ({e}). Retry {attempt+1}/{MAX_RETRIES}. Sleeping {wait}s")
				time.sleep(wait)
		print(f"\nFailed after {MAX_RETRIES} retries: {wid}")
		return None

	def update_cache( self ):
		snapshot = utils.zotero_take_snapshot()
		for key in tqdm( snapshot , desc="Zotero-DB" , position=0 ):
			if "doi" not in snapshot[ key ]:
				continue
			if snapshot[ key ][ "doi" ] is None:
				continue
			_doi = utils.normalize_doi( snapshot[ key ][ "doi" ] )
			_doi_b64 = utils.base64_encode( _doi )
			_cache_fp = self.storage_dir.joinpath( f"{_doi_b64}.json" )
			if _cache_fp.exists():
				data = utils.read_json( _cache_fp )
			else:
				data = self.api_get_doi( snapshot[ key ][ "doi" ] )
				if data is None:
					data = {}
					utils.write_json( _cache_fp , data )
					continue
				utils.write_json( _cache_fp , data )
			if not data:
				continue
			if  "referenced_works" in data:
				for i , item in enumerate( tqdm( data[ "referenced_works" ] , desc="\tReferences" , position=1 , leave=False ) ):
					wid = item.split( "/" )[ -1 ]
					_referenced_cached_fp = self.references_dir.joinpath( f"{wid}.json" )
					if _referenced_cached_fp.exists():
						continue
					reference_data = self.api_get_id( item )
					if reference_data is None:
						utils.write_json( _referenced_cached_fp , {} )
						continue
					utils.write_json( _referenced_cached_fp , reference_data )

					## Symlinks for references by DOI (if available) - this is optional and can be skipped to save space
					# _r_doi = reference_data.get( "doi" )
					# if not isinstance( _r_doi , str ) or not _r_doi:
					# 	continue
					# _r_doi = utils.normalize_doi( _r_doi )
					# _r_doi_b64 = utils.base64_encode( _r_doi )
					# _r_cached_fp = self.storage_dir.joinpath( f"{_r_doi_b64}.json" )
					# utils.write_json( _r_cached_fp , reference_data )
					# if not _r_cached_fp.exists():
					# 	_r_cached_fp.symlink_to( _referenced_cached_fp )

	def doi( self , doi ):
		_doi = utils.doi_fp( doi )
		_cache_fp = self.storage_dir.joinpath( f"{_doi}.json" )
		if _cache_fp.exists():
			return utils.read_json( _cache_fp )
		data = self.api_get_doi( doi )
		utils.write_json( _cache_fp , data )
		return data

if __name__ == "__main__":
	x = OpenAlex()
	# pprint( x.get_doi( "10.3389/fnhum.2015.00423" ) )
	x.update_cache()
	# pprint( x.doi( "10.3389/fnhum.2015.00423" ) )
	# pprint( x.api_get_id( "W72886680" ) )