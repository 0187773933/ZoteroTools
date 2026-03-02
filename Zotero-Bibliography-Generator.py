#!/usr/bin/env python3
from pprint import pprint
from pyzotero import zotero

# https://github.com/urschrei/pyzotero
# https://www.zotero.org/settings/keys
# https://www.zotero.org/settings/keys/new

# Personal = "7686596"
# Group 9 - Thalamus = "2837521"

if __name__ == "__main__":
	zot = zotero.Zotero( "2837521" , "group" , "k8L2xYDcW5g4R6GyagQM855L" )
	#folders = zot.collections_top()
	#pprint( folders )

	# subfolders = zot.collections_sub( "2FB8BFB2" )
	# pprint( subfolders )

	single_subfolder_test = zot.collection( "6P4VW9BN" )
	pprint( single_subfolder_test )

	# for item in items:
	# 	print('Item: %s | Key: %s' % (item['data']['itemType'], item['data']['key']))