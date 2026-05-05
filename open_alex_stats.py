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