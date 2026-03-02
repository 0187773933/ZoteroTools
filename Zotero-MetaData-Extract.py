#!/usr/bin/env python3
import sqlite3
import json
import shutil
import tempfile
from pathlib import Path

HOME = Path.home()
ZOTERO_DB = HOME / "Zotero" / "zotero.sqlite"
ZOTERO_STORAGE = HOME / "Zotero" / "storage"

MAIN_DIR = HOME / ".zotero-cg"
META_DATA_DIR = MAIN_DIR / "meta-data"
META_DATA_DIR.mkdir(parents=True, exist_ok=True)


def write_json(file_path, python_object):
	with open(file_path, "w", encoding="utf-8") as f:
		json.dump(python_object, f, ensure_ascii=False, indent=4)


def zotero_open_snapshot():
	tmpdir = Path(tempfile.mkdtemp(prefix="zotero_db_"))
	tmpdb = tmpdir / "zotero.sqlite"
	shutil.copy2(ZOTERO_DB, tmpdb)
	conn = sqlite3.connect(tmpdb)
	conn.row_factory = sqlite3.Row
	return conn


def normalize_doi(value: str) -> str:
	if not value:
		return value
	v = value.strip()
	v = v.replace("https://doi.org/", "").replace("http://doi.org/", "")
	return v.strip()


def zotero_collect_meta_data():
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

	# If you want a sanity check that matches your expectation:
	# print(f"Base bibliographic items: {len(papers)}")

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
		if parentID not in papers:
			continue

		path = row["path"]
		attachKey = row["attachKey"]

		file_path = None
		if path and path.startswith("storage:"):
			candidate = ZOTERO_STORAGE / attachKey / path.replace("storage:", "")
			if candidate.exists():
				file_path = candidate

		papers[parentID]["attachments"].append({
			"key": attachKey,
			"contentType": row["contentType"],
			"linkMode": row["linkMode"],   # 1=imported file, 2=linked file, 3=URL
			"path": str(file_path) if file_path else None,
			"rawPath": path
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


def main():
	zmd = zotero_collect_meta_data()

	for key, item in zmd.items():
		out_file = META_DATA_DIR / f"{key}.json"
		write_json(out_file, item)

	print(f"Extracted metadata for {len(zmd)} bibliographic Zotero items")


if __name__ == "__main__":
	main()