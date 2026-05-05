#!/usr/bin/env python3
import time
from pathlib import Path
import requests
from pprint import pprint
import utils
from tqdm import tqdm
import csv
from rapidfuzz import fuzz
from collections import Counter
from openpyxl import Workbook
from openpyxl.styles import Font

API_KEY = "bdDEtP2Jp4MhNyiG42Ckzv"
BASE_URL = "https://api.openalex.org/works/"
HEADERS = { "User-Agent": "zotero-citation-analyzer/1.0" }
STORAGE_DIR = Path.home().joinpath( ".zotero-cg" , "openalex" )
MAX_RETRIES = 10

class OpenAlex:
	def __init__( self , options={} ):
		self.options = options
		self.api_key = options.get( "api_key" , API_KEY )
		self.base_url = options.get( "base_url" , BASE_URL )
		self.headers = options.get( "headers" , HEADERS )
		self.params = { "api_key": self.api_key }
		self.storage_dir = options.get( "storage_dir" , STORAGE_DIR )
		self.storage_dir.mkdir( parents=True , exist_ok=True )
		self.references_dir = self.storage_dir.joinpath( "references" )
		self.references_dir.mkdir( parents=True , exist_ok=True )
		self.problem_dois = set()

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

	def api_search_title( self , title , per_page=10 ):
		url = self.base_url.rstrip( "/" )
		params = dict( self.params )
		params.update({
			"search": f'"{title}"',
			"per-page": per_page,
			"select": "id,doi,title,display_name,publication_year,cited_by_count,relevance_score,authorships"
		})
		while True:
			r = requests.get( url , params=params , headers=self.headers )
			if r.status_code == 200:
				return r.json().get( "results" , [] )
			elif r.status_code == 429:
				retry = int( r.headers.get( "Retry-After" , 5 ) )
				print( f"\nRate limited. Sleeping {retry}s" )
				time.sleep( retry )
			else:
				print( f"\nOpenAlex title search failed: {r.status_code} {r.url} {r.text[:500]}" )
				return []

	def api_get_id( self , open_alex_wid ):
		url = BASE_URL + open_alex_wid
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
					return None
			except requests.exceptions.RequestException as e:
				wait = min(2 ** attempt, 60)
				print(f"\nNetwork error ({e}). Retry {attempt+1}/{MAX_RETRIES}. Sleeping {wait}s")
				time.sleep(wait)
		print(f"\nFailed after {MAX_RETRIES} retries: {wid}")
		return None

	def update_cache( self ):
		self.zotero_snapshot = utils.zotero_simple_snapshot()
		self.zotero_snapshot_keys = self.zotero_snapshot.keys()
		for k , key in enumerate( tqdm( self.zotero_snapshot_keys , desc="Papers" , position=0 ) ):

			# 1.) Download Info for Papers in Zotero Library
			paper_doi = self.zotero_snapshot[ key ].get( "doi" )
			paper_title = self.zotero_snapshot[ key ].get( "title" )
			paper_title_normalized = utils.openalex_normalize_title( paper_title )
			z_id = self.zotero_snapshot[ key ].get( "id" )
			zotero_cached_fp = self.storage_dir.joinpath( f"{z_id}.json" )
			if not paper_doi:
				if zotero_cached_fp.exists():
					# info = utils.read_json( zotero_cached_fp )
					# paper_doi = info.get( "doi" )
					# paper_title = info.get( "title" )
					continue
				else:
					print( "searching title" , paper_title_normalized )
					search_results = self.api_search_title( paper_title_normalized )
					if len( search_results ) > 1:
						# Todo , fix to find one that has a doi ?? or idk
						paper_dois = [ p.get( "doi" ) for p in search_results if p.get( "doi" ) is not None ]
						if len( paper_dois ) > 1:
							paper_doi = paper_dois[ 0 ]
						else:
							print( "still nothing" , self.zotero_snapshot[ key ] , search_results )
					utils.write_json( zotero_cached_fp , { "id": z_id , "doi": paper_doi , "title": paper_title } )
			if not paper_doi:
				# print( "still nothing" , self.zotero_snapshot[ key ] )
				continue
			paper_doi_normalized = utils.normalize_doi( paper_doi )
			paper_doi_b64 = utils.base64_encode( paper_doi_normalized )
			paper_cached_fp = self.storage_dir.joinpath( f"{paper_doi_b64}.json" )
			if paper_cached_fp.exists() == True:
				continue
			paper_data = self.api_get_doi( paper_doi )
			utils.write_json( paper_cached_fp , paper_data )

			# For Each one that resolves to a doi
			# Todo , there is still potentially references in the books , etc
			# 2.) Download all of its References
			referenced_works = paper_data.get( "referenced_works" )
			if not referenced_works:
				continue
			for i , item in enumerate( tqdm( referenced_works , desc="References" , position=1 , leave=False ) ):
				wid = item.split( "/" )[ -1 ]
				reference_cached_fp = self.references_dir.joinpath( f"{wid}.json" )
				if reference_cached_fp.exists() == True:
					continue
				reference_data = self.api_get_id( wid )
				if not reference_data:
					reference_data = {}
				utils.write_json( reference_cached_fp , reference_data )

	def stats( self , keywords=None , fuzz_threshold=80 ):
		# 1. OpenAlex data we have for library papers
		zp = {}
		for fp in tqdm( list( self.storage_dir.glob( "*.json" ) ) , desc="Loading library" ):
			d = utils.read_json( fp ) or {}
			oid = d.get( "id" , "" )
			if isinstance( oid , str ) and oid.startswith( "https://openalex.org/" ):
				zp[ oid.rsplit( "/" , 1 )[ -1 ] ] = d

		# 2. Source of truth: Zotero snapshot
		snap = utils.zotero_simple_snapshot()
		lib_dois = { utils.normalize_doi( i[ "doi" ] ) for i in snap.values() if i.get( "doi" ) }
		lib_titles = { utils.openalex_normalize_title( i[ "title" ] ) for i in snap.values() if i.get( "title" ) }
		lib_wids = set( zp.keys() )

		# 3. Tally refs (skip wid hits early)
		counts , citers = Counter() , {}
		for wid , p in tqdm( zp.items() , desc="Tallying refs" ):
			for r in p.get( "referenced_works" ) or []:
				rw = r.rsplit( "/" , 1 )[ -1 ]
				if rw in lib_wids:
					continue
				counts[ rw ] += 1
				citers.setdefault( rw , set() ).add( wid )

		# 4. Build rows, second-pass dedup via DOI/title
		title_of = lambda d: d.get( "title" ) or d.get( "display_name" ) or ""
		rows , skipped = [] , 0
		for rw , n in tqdm( counts.most_common() , desc="Building rows" ):
			fp = self.references_dir / f"{rw}.json"
			m = ( utils.read_json( fp ) or {} ) if fp.exists() else {}
			rd = m.get( "doi" )
			rt = m.get( "title" ) or m.get( "display_name" )
			if rd and utils.normalize_doi( rd ) in lib_dois:
				skipped += 1
				continue
			if rt and utils.openalex_normalize_title( rt ) in lib_titles:
				skipped += 1
				continue
			clean_doi = utils.normalize_doi( rd ) if rd else None
			proxy_url = f"https://doi-org.ezproxy.libraries.wright.edu/{clean_doi}" if clean_doi else None
			doi_url   = f"https://doi.org/{clean_doi}" if clean_doi else None
			proxy = utils.Link( proxy_url , proxy_url ) if proxy_url else ""
			link  = utils.Link( doi_url , doi_url ) if doi_url else ""
			cited_by = " | ".join( title_of( zp[ w ] )[ :80 ] for w in sorted( citers[ rw ] ) )
			rows.append([ n , title_of( m ) or "(no metadata)" , m.get( "publication_year" ) , proxy , clean_doi , link , m.get( "cited_by_count" ) , rw , cited_by ])

		# 5. Build sheets
		headers = [ "Cites" , "Title" , "Year" , "Proxy" , "DOI" , "Link" , "OA Cited-By" , "WID" , "Citing Papers" ]
		sheets = [
			( "Top 1000 by Cites"   , headers , rows[ :1000 ] ),
			( "Top 1000 by Recency" , headers , sorted( rows , key=lambda r: r[ 2 ] or 0 , reverse=True )[ :1000 ] ),
		]

		if keywords:

			kws = [ k.lower() for k in keywords ]
			def hit( title ):
				if not title: return False
				t = title.lower()
				return any( fuzz.partial_ratio( k , t ) >= fuzz_threshold for k in kws )
			matched = [ r for r in tqdm( rows , desc="Keyword filter" ) if hit( r[ 1 ] ) ]
			matched.sort( key=lambda r: r[ 2 ] or 0 , reverse=True )
			sheets.append( ( f"Keyword Matches" , headers , matched[ :1000 ] ) )
			print( f"keyword hits: {len(matched)} (threshold={fuzz_threshold}, kws={kws})" )

		out = self.storage_dir / "missing.xlsx"
		utils.write_xlsx( out , sheets )
		print( f"library={len(snap)} resolved={len(zp)} missing={len(rows)} (deduped {skipped}) -> {out}" )

if __name__ == "__main__":
	x = OpenAlex()
	# x.update_cache()
	x.stats( keywords=["speech" , "imagined"] )