"""
Diagnostic: shows the raw quotes an extraction returned and whether each one
appears verbatim in the source. Used to diagnose the T-Pot case where an
all-or-nothing critic was discarding three valid quotes because a fourth was
paraphrased. Uses the same cache keys as the pipeline, so it costs no quota.
"""

import pipeline, tools

REPO = "telekom-security/tpotce"

metadata = tools.get_metadata(REPO)
readme = tools.get_readme(REPO)
doc_files = tools.get_doc_files(REPO)
docs = f"{metadata}\n\nDocumentation files: {doc_files}\n\n{readme}"

extracted = pipeline.extract_ethics(docs)

print("=== QUOTES THE MODEL RETURNED ===")
for q in extracted.get("quotes", []):
    print(f"\n--- {q!r}")
    haystack = " ".join(docs.split()).lower()
    needle = " ".join(q.split()).lower()
    print(f"    exact match in source: {needle in haystack}")

print("\n=== VERDICT ===")
print(pipeline.verify(docs, extracted.get("quotes", [])))