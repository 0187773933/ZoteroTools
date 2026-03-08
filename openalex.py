#!/usr/bin/env python3
import time
from pathlib import Path
import requests
from pprint import pprint
import utils
from tqdm import tqdm
import csv
from collections import Counter
from openpyxl import Workbook
from openpyxl.styles import Font

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
		self.citation_counter = Counter()
		self.reference_counter = Counter()
		self.external_counter = Counter()

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
			_wid = data.get( "id" ).split( "/" )[ -1 ]
			self.citation_counter[ _wid ] += 1
			if  "referenced_works" in data:
				for i , item in enumerate( tqdm( data[ "referenced_works" ] , desc="\tReferences" , position=1 , leave=False ) ):
					wid = item.split( "/" )[ -1 ]
					self.reference_counter[ wid ] += 1
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



		citations_fp = self.storage_dir.joinpath( "citations_frequency.xlsx" )
		references_fp = self.storage_dir.joinpath( "reference_frequency.xlsx" )
		for wid , count in self.reference_counter.items():
			if wid not in self.citation_counter:
				self.external_counter[wid] = count
		external_fp = self.storage_dir.joinpath( "external_frequency.xlsx" )

		self.write_frequency_stats( self.citation_counter , citations_fp )
		self.write_frequency_stats( self.reference_counter , references_fp )
		self.write_frequency_stats( self.external_counter , external_fp )

	def doi( self , doi ):
		_doi = utils.doi_fp( doi )
		_cache_fp = self.storage_dir.joinpath( f"{_doi}.json" )
		if _cache_fp.exists():
			return utils.read_json( _cache_fp )
		data = self.api_get_doi( doi )
		utils.write_json( _cache_fp , data )
		return data

	def stats( self ):
		cache_files = list( self.storage_dir.glob( "*.json" ) )
		return {
			"total_cached_dois": len( cache_files ),
		}

	def write_frequency_stats(self, counter, xlsx_path):

		rows = []

		for wid, count in counter.most_common():

			if count < 2:
				break

			ref_fp = self.references_dir.joinpath(f"{wid}.json")

			if not ref_fp.exists():
				continue

			ref = utils.read_json(ref_fp)

			if not ref:
				continue

			title = ref.get("title")

			doi = ref.get("doi")
			if not doi:
				continue

			_wsu_doi = utils.normalize_doi(doi)
			_wsu_proxy = f"https://doi-org.ezproxy.libraries.wright.edu/{_wsu_doi}"

			pub_date = ref.get("publication_date")

			source = (
				ref
				.get("primary_location", {})
				.get("source", {})
			)

			if not isinstance(source, dict):
				continue

			journal = source.get("display_name")
			publisher = source.get("host_organization_name")

			rows.append({
				"count": count,
				# "wid": wid,
				"title": title,
				"proxy": _wsu_proxy,
				"doi": doi,
				"publication_date": pub_date,
				"journal": journal,
				"publisher": publisher
			})

		headers = [
			"count",
			# "wid",
			"title",
			"proxy",
			"doi",
			"publication_date",
			"journal",
			"publisher"
		]

		wb = Workbook()
		ws = wb.active
		ws.title = "frequency"

		# header row
		ws.append(headers)

		for row in rows:

			values = [row[h] for h in headers]
			ws.append(values)

			current_row = ws.max_row

			# make proxy column clickable
			proxy_col = headers.index("proxy") + 1
			cell = ws.cell(row=current_row, column=proxy_col)
			cell.hyperlink = row["proxy"]
			cell.value = row["proxy"]
			cell.font = Font(color="0000FF", underline="single")

		wb.save(xlsx_path)

		print(f"\nFrequency stats written → {xlsx_path}")

if __name__ == "__main__":
	x = OpenAlex()
	# pprint( x.get_doi( "10.3389/fnhum.2015.00423" ) )
	x.update_cache()
	# pprint( x.doi( "10.3389/fnhum.2015.00423" ) )
	# pprint( x.api_get_id( "W72886680" ) )