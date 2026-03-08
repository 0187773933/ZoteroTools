import os
import re
import json
import tempfile
import shutil
from pathlib import Path
import sqlite3
import base64

def write_json( file_path , python_object ):
	with open( file_path , 'w', encoding='utf-8' ) as f:
		json.dump( python_object , f , ensure_ascii=False , indent=4 )

def read_json( file_path ):
	with open( file_path ) as f:
		return json.load( f )

def normalize_doi(value: str) -> str:
	if not value:
		return value
	v = value.strip()
	v = v.replace("https://doi.org/", "").replace("http://doi.org/", "")
	return v.strip()


def base64_encode( message ):
	try:
		message_bytes = message.encode( 'utf-8' )
		base64_bytes = base64.b64encode( message_bytes )
		base64_message = base64_bytes.decode( 'utf-8' )
		return base64_message
	except Exception as e:
		print( e )
		return False

def base64_decode( base64_message ):
	try:
		base64_bytes = base64_message.encode( 'utf-8' )
		message_bytes = base64.b64decode(base64_bytes)
		message = message_bytes.decode( 'utf-8' )
		return message
	except Exception as e:
		print( e )
		return False

def doi_fp( doi ):
	return re.sub( r'[^a-zA-Z0-9._-]', '_' , doi )

def _candidates_common(home):
	return [
		home / "Zotero" / "zotero.sqlite",
		home / "ZoteroBeta" / "zotero.sqlite",
		home / "Zotero Beta" / "zotero.sqlite",
		home / "Library" / "Application Support" / "Zotero" / "zotero.sqlite",
		home / "Library" / "Application Support" / "ZoteroBeta" / "zotero.sqlite",
		home / "Library" / "Application Support" / "Zotero Beta" / "zotero.sqlite",
	]

def _bounded_find_sqlite(home):
	roots = [
		home / "Zotero",
		home / "Library" / "Application Support" / "Zotero",
		home / "Library" / "Application Support",
	]
	roots = [r for r in roots if r.exists()]

	best: Optional[Tuple[float, Path]] = None  # (mtime, path)

	for root in roots:
		for pat in ("zotero.sqlite", "**/zotero.sqlite"):
			try:
				for p in root.glob(pat):
					if p.name != "zotero.sqlite":
						continue
					try:
						st = p.stat()
					except OSError:
						continue
					if best is None or st.st_mtime > best[0]:
						best = (st.st_mtime, p)
			except Exception:
				continue

	return best[1] if best else None

def resolve_zotero_db_path(cli_db ):
	# 1) CLI
	if cli_db:
		p = Path(cli_db).expanduser()
		if p.exists():
			return p
		raise SystemExit(f"--db path does not exist: {p}")

	# 2) ENV
	env = os.environ.get("ZOTERO_DB", "").strip()
	if env:
		p = Path(env).expanduser()
		if p.exists():
			return p
		raise SystemExit(f"ZOTERO_DB path does not exist: {p}")

	home = Path.home()

	# 3) Common locations
	for p in _candidates_common(home):
		if p.exists():
			return p

	# 4) Bounded search
	p = _bounded_find_sqlite(home)
	if p and p.exists():
		return p

	raise SystemExit(
		"Could not find zotero.sqlite automatically.\n"
		"Provide --db /path/to/zotero.sqlite or set ZOTERO_DB=/path/to/zotero.sqlite"
	)

ZOTERO_DB = resolve_zotero_db_path( None )
def zotero_open_snapshot():
	tmpdir = Path(tempfile.mkdtemp( prefix="zotero_db_" ) )
	tmpdb = tmpdir / "zotero.sqlite"
	shutil.copy2( ZOTERO_DB , tmpdb )
	conn = sqlite3.connect( tmpdb )
	conn.row_factory = sqlite3.Row
	return conn

def zotero_take_snapshot():
	conn = zotero_open_snapshot()
	c = conn.cursor()

	# --------------------------------------------------
	# 1) BASE ITEMS: ONLY "REAL" BIB ITEMS (exclude attachments/notes/annotations)
	# --------------------------------------------------
	# Zotero's UI count (~681) corresponds to bibliographic items, not the raw items table.
	EXCLUDE_TYPES = ("attachment", "note", "annotation")

	papers = {}

	for row in c.execute("""
		SELECT items.itemID, items.key, itemTypes.typeName
		FROM items
		JOIN itemTypes ON itemTypes.itemTypeID = items.itemTypeID
		LEFT JOIN deletedItems ON deletedItems.itemID = items.itemID
		WHERE deletedItems.itemID IS NULL
		  AND itemTypes.typeName NOT IN ('attachment','note','annotation')
	"""):
		itemID = row["itemID"]
		papers[itemID] = {
			"itemID": itemID,
			"key": row["key"],
			"type": row["typeName"],
			"doi": None,
			"attachments": [],
			"meta": {},
			"creators": [],
			"tags": [],
			"collections": []
		}

	# --------------------------------------------------
	# 2) METADATA (title, DOI, journal, year, etc)
	# --------------------------------------------------
	for row in c.execute("""
		SELECT itemData.itemID, fields.fieldName, itemDataValues.value
		FROM itemData
		JOIN fields ON fields.fieldID = itemData.fieldID
		JOIN itemDataValues ON itemDataValues.valueID = itemData.valueID
	"""):
		itemID = row["itemID"]
		if itemID not in papers:
			continue

		field = row["fieldName"]
		value = row["value"]

		papers[itemID]["meta"][field] = value

		if field == "DOI" and value:
			papers[itemID]["doi"] = normalize_doi(value)

	# --------------------------------------------------
	# 3) CREATORS (authors/editors)
	# --------------------------------------------------
	for row in c.execute("""
		SELECT itemCreators.itemID,
			   creators.firstName,
			   creators.lastName,
			   creatorTypes.creatorType
		FROM itemCreators
		JOIN creators ON creators.creatorID = itemCreators.creatorID
		JOIN creatorTypes ON creatorTypes.creatorTypeID = itemCreators.creatorTypeID
		ORDER BY itemCreators.itemID, itemCreators.orderIndex
	"""):
		itemID = row["itemID"]
		if itemID not in papers:
			continue

		papers[itemID]["creators"].append({
			"type": row["creatorType"],
			"first": row["firstName"],
			"last": row["lastName"]
		})

	# --------------------------------------------------
	# 4) ALL ATTACHMENTS (child items) grouped onto their parent bib item
	# --------------------------------------------------
	for row in c.execute("""
		SELECT itemAttachments.parentItemID AS parentID,
			   itemAttachments.itemID       AS attachItemID,
			   items.key                    AS attachKey,
			   itemAttachments.path         AS path,
			   itemAttachments.contentType  AS contentType,
			   itemAttachments.linkMode     AS linkMode
		FROM itemAttachments
		JOIN items ON items.itemID = itemAttachments.itemID
	"""):

		parentID = row["parentID"]

		# if missing parent, create placeholder
		if parentID not in papers:
			papers[parentID] = {
				"itemID": parentID,
				"key": None,
				"type": "unknown",
				"doi": None,
				"attachments": [],
				"meta": {},
				"creators": [],
				"tags": [],
				"collections": []
			}

		path = row["path"]
		attachKey = row["attachKey"]

		# file_path = None

		# if path and path.startswith("storage:"):
		# 	candidate = ZOTERO_STORAGE / attachKey / path.replace("storage:", "")
		# 	if candidate.exists():
		# 		file_path = candidate

		papers[parentID]["attachments"].append({
			"key": attachKey,
			"contentType": row["contentType"],
			"linkMode": row["linkMode"],  # 1=imported file, 2=linked file, 3=URL
			# "path": str(file_path) if file_path else None,
			# "rawPath": path
			"path": path
		})

	# --------------------------------------------------
	# 5) TAGS (only for base bib items)
	# --------------------------------------------------
	for row in c.execute("""
		SELECT itemTags.itemID, tags.name
		FROM itemTags
		JOIN tags ON tags.tagID = itemTags.tagID
	"""):
		itemID = row["itemID"]
		if itemID not in papers:
			continue
		papers[itemID]["tags"].append(row["name"])

	# --------------------------------------------------
	# 6) COLLECTIONS (only for base bib items)
	# --------------------------------------------------
	for row in c.execute("""
		SELECT collectionItems.itemID, collections.collectionName
		FROM collectionItems
		JOIN collections ON collections.collectionID = collectionItems.collectionID
	"""):
		itemID = row["itemID"]
		if itemID not in papers:
			continue
		papers[itemID]["collections"].append(row["collectionName"])

	conn.close()

	# Sort tag/collection lists for stability
	for item in papers.values():
		item["tags"] = sorted(set(item["tags"]))
		item["collections"] = sorted(set(item["collections"]))

	# Return keyed by Zotero key (one per bib item)
	return {item["key"]: item for item in papers.values()}