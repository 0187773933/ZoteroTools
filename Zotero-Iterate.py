#!/usr/bin/env python3
import sqlite3, tempfile, shutil
from pathlib import Path

HOME = Path.home()
ZOTERO_DB = HOME / "Zotero" / "zotero.sqlite"
ZOTERO_STORAGE = HOME / "Zotero" / "storage"

# # Discovery - 1
# for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
#     print(row[0])

# # Discovery - 2
# rows = c.execute("""
# SELECT path, linkMode, contentType
# FROM itemAttachments
# WHERE contentType='application/pdf'
# LIMIT 20
# """).fetchall()
# for r in rows:
#     print(r)


def open_snapshot():
    tmpdir = Path(tempfile.mkdtemp(prefix="zotero_db_"))
    snap = tmpdir / "zotero.sqlite"
    shutil.copy2(ZOTERO_DB, snap)
    return sqlite3.connect(str(snap))


def main():
    conn = open_snapshot()
    c = conn.cursor()

    rows = c.execute("""
        SELECT
            parentItems.key,
            childItems.key,
            itemAttachments.path,
            itemAttachments.linkMode,
            itemAttachments.contentType
        FROM itemAttachments
        JOIN items childItems ON childItems.itemID = itemAttachments.itemID
        LEFT JOIN items parentItems ON parentItems.itemID = itemAttachments.parentItemID
    """).fetchall()

    total = 0

    for parent_key, attach_key, path, linkMode, ctype in rows:

        if ctype != "application/pdf":
            continue

        if not path.startswith("storage:"):
            continue

        filename = path.replace("storage:", "")
        pdf = ZOTERO_STORAGE / attach_key / filename

        if pdf.exists():
            print(f"{parent_key} -> {pdf}")
            total += 1

    print("\nTOTAL PDFs:", total)
    conn.close()


if __name__ == "__main__":
    main()