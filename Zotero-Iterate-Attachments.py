#!/usr/bin/env python3
import sqlite3, tempfile, shutil
from pathlib import Path
from pprint import pprint

HOME = Path.home()
ZOTERO_DB = HOME / "Zotero" / "zotero.sqlite"
ZOTERO_STORAGE = HOME / "Zotero" / "storage"


def zotero_open_snapshot():
	tmpdir = Path(tempfile.mkdtemp(prefix="zotero_db_"))
	tmpdb = tmpdir / "zotero.sqlite"
	shutil.copy2(ZOTERO_DB, tmpdb)

	conn = sqlite3.connect(tmpdb)
	conn.row_factory = sqlite3.Row
	return conn


def iterate_attachments():

	conn = zotero_open_snapshot()
	c = conn.cursor()

	papers = {}

	# ------------------------------------------------
	# Load all top-level items
	# ------------------------------------------------
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

	# ------------------------------------------------
	# Attach attachments
	# ------------------------------------------------
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

		file_path = None

		if path and path.startswith("storage:"):
			candidate = ZOTERO_STORAGE / attachKey / path.replace("storage:", "")
			if candidate.exists():
				file_path = candidate

		papers[parentID]["attachments"].append({
			"key": attachKey,
			"contentType": row["contentType"],
			"linkMode": row["linkMode"],  # 1=imported file, 2=linked file, 3=URL
			"path": str(file_path) if file_path else None,
			"rawPath": path
		})

	conn.close()

	return papers


if __name__ == "__main__":
	pprint(iterate_attachments())