from marker.convert import convert_single_pdf
from pathlib import Path
import tempfile, json

def extract_structure(pdf_path):

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)

        convert_single_pdf(
            pdf_path,
            out,
            output_format="json",
            use_llm=False
        )

        data = json.loads((out/"document.json").read_text())

    paper = {
        "title": data.get("title"),
        "authors": data.get("authors", []),
        "sections": [s["heading"] for s in data.get("sections", []) if s.get("heading")],
        "figures": {}
    }

    for fig in data.get("figures", []):
        if fig.get("label") and fig.get("caption"):
            paper["figures"][fig["label"]] = fig["caption"]

    return paper
