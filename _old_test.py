import sqlite3
from pathlib import Path

ZOTERO_DB = Path.home() / "Zotero" / "zotero.sqlite"

conn = sqlite3.connect(ZOTERO_DB)
cur = conn.cursor()

cur.execute("""
SELECT
    ia.itemID,
    ia.path,
    ia.contentType
FROM itemAttachments AS ia
LIMIT 50
""")

rows = cur.fetchall()
conn.close()

print("\nFirst 50 attachment rows:\n")
for r in rows:
    print(r)
