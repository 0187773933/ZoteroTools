import json
from pprint import pprint

def resolve_ref(doc, ref):
    # "#/texts/123" -> doc["texts"][123]
    parts = ref.lstrip("#/").split("/")
    obj = doc
    for p in parts:
        if p.isdigit():
            obj = obj[int(p)]
        else:
            obj = obj[p]
    return obj


def flatten_docling(doc):

    ordered_text = []

    for child in doc["body"]["children"]:
        node = resolve_ref(doc, child["$ref"])

        # only actual readable text
        if node.get("label") in ("text", "paragraph", "title", "section_header", "caption"):
            txt = node.get("text", "").strip()
            if txt:
                ordered_text.append(txt)

    return "\n\n".join(ordered_text)


with open("test_docling_output.json") as f:
    doc = json.load(f)

pprint(flatten_docling(doc))