import sqlite3
import requests
import time
import csv
import json
import hashlib
import tempfile
import shutil
from pathlib import Path
from tqdm import tqdm
from collections import Counter

# -----------------------
# CONFIG
# -----------------------

API_KEY = "asdf"
BASE_URL = "https://api.openalex.org/works/"
HEADERS = {"User-Agent": "zotero-citation-analyzer/1.0"}

HOME = Path.home()
PROJECT_DIR = HOME / ".zotero-cg"
CACHE_DIR = PROJECT_DIR / "cache"
OUTPUT_CSV = PROJECT_DIR / "zotero_openalex_citations.csv"
REFERENCE_OUTPUT = PROJECT_DIR / "internal_reference_rank.csv"

ZOTERO_DB = HOME / "Zotero" / "zotero.sqlite"

MAX_RPS = 50
MAX_INTERNAL = 300
SLEEP_BETWEEN = 1 / MAX_RPS

# create dirs
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------
# UTIL
# -----------------------

def open_snapshot():
	tmpdir = Path(tempfile.mkdtemp(prefix="zotero_db_"))
	snap = tmpdir / "zotero.sqlite"
	shutil.copy2(ZOTERO_DB, snap)
	return sqlite3.connect(str(snap))

def doi_to_filename(doi: str) -> Path:
	safe = doi.replace("/", "_")
	return CACHE_DIR / f"{safe}.json"

def load_cache(doi):
	f = doi_to_filename(doi)
	if f.exists():
		with open(f, "r", encoding="utf-8") as fp:
			return json.load(fp)
	return None

def save_cache(doi, data):
	f = doi_to_filename(doi)
	with open(f, "w", encoding="utf-8") as fp:
		json.dump(data, fp)

def workid_to_filename(work_id: str) -> Path:
	wid = work_id.split("/")[-1]
	return CACHE_DIR / f"{wid}.json"

def load_work_by_id(work_id):
	f = workid_to_filename(work_id)
	if f.exists():
		with open(f, "r", encoding="utf-8") as fp:
			return json.load(fp)
	return None

# -----------------------
# GET DOIs FROM ZOTERO
# -----------------------

def extract_dois():
	conn = open_snapshot()
	c = conn.cursor()

	query = """
	SELECT DISTINCT value
	FROM itemDataValues
	JOIN itemData ON itemData.valueID = itemDataValues.valueID
	JOIN fields ON fields.fieldID = itemData.fieldID
	WHERE fields.fieldName = 'DOI'
	"""

	dois = [row[0] for row in c.execute(query) if row[0]]
	conn.close()

	cleaned = []
	for d in dois:
		d = d.strip()
		d = d.replace("https://doi.org/", "")
		d = d.replace("http://doi.org/", "")
		cleaned.append(d)

	return list(set(cleaned))

# -----------------------
# OPENALEX QUERY
# -----------------------

def get_work_from_openalex(doi):

	# check cache first
	cached = load_cache(doi)
	if cached:
		return cached

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

def fetch_work_by_id(work_id):
	cached = load_work_by_id(work_id)
	if cached:
		return cached

	wid = work_id.split("/")[-1]
	url = BASE_URL + wid
	params = {"api_key": API_KEY}

	while True:
		r = requests.get(url, params=params, headers=HEADERS)

		if r.status_code == 200:
			data = r.json()
			with open(workid_to_filename(work_id), "w", encoding="utf-8") as fp:
				json.dump(data, fp)
			return data

		elif r.status_code == 429:
			retry = int(r.headers.get("Retry-After", 5))
			print(f"\nRate limited resolving refs. Sleeping {retry}s")
			time.sleep(retry)

		else:
			return None

def build_internal_reference_rank():

	print("\nBuilding internal citation backbone...\n")

	cache_files = list(CACHE_DIR.glob("10.*.json"))
	counter = Counter()

	# count references across all local papers
	for file in tqdm(cache_files, desc="Reading references"):
		with open(file, "r", encoding="utf-8") as f:
			data = json.load(f)

		refs = data.get("referenced_works", [])
		for r in refs:
			counter[r] += 1

	if not counter:
		print("No references found.")
		return

	top_refs = counter.most_common(MAX_INTERNAL)

	print(f"\nResolving {len(top_refs)} most referenced works...\n")

	resolved = []

	for work_id, count in tqdm(top_refs, desc="Resolving titles"):
		data = fetch_work_by_id(work_id)
		time.sleep(SLEEP_BETWEEN)

		if not data:
			continue

		resolved.append({
			"count": count,
			"title": data.get("display_name"),
			"year": data.get("publication_year"),
			"global_citations": data.get("cited_by_count"),
			"openalex_id": work_id
		})

	resolved.sort(key=lambda x: x["count"], reverse=True)

	with open(REFERENCE_OUTPUT, "w", newline="", encoding="utf-8") as f:
		writer = csv.DictWriter(f, fieldnames=resolved[0].keys())
		writer.writeheader()
		writer.writerows(resolved)

	print("\nTop 20 backbone papers in YOUR library:\n")
	for r in resolved[:20]:
		print(f"{r['count']:>3}  {r['title']} ({r['year']})")

	print(f"\nSaved to {REFERENCE_OUTPUT}")

# -----------------------
# MAIN
# -----------------------

def main():
	dois = extract_dois()
	print(f"\nFound {len(dois)} DOIs in Zotero\n")

	results = []

	for doi in tqdm(dois, desc="OpenAlex lookup"):
		data = get_work_from_openalex(doi)
		time.sleep(SLEEP_BETWEEN)

		if not data:
			continue

		results.append({
			"doi": doi,
			"title": data.get("display_name"),
			"cited_by_count": data.get("cited_by_count", 0),
			"publication_year": data.get("publication_year"),
			"openalex_id": data.get("id")
		})

	if not results:
		print("No results.")
		return

	results.sort(key=lambda x: x["cited_by_count"], reverse=True)

	with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
		writer = csv.DictWriter(f, fieldnames=results[0].keys())
		writer.writeheader()
		writer.writerows(results)

	print("\nTop 20 Most Cited:\n")
	for r in results[:20]:
		print(f"{r['cited_by_count']:>6}  {r['title']}")

	print(f"\nSaved to {OUTPUT_CSV}")
	print(f"Cache directory: {CACHE_DIR}")

	build_internal_reference_rank()

if __name__ == "__main__":
	main()