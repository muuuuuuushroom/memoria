"""Freeze the public LongMemEval pilot and its external tokenizer assets."""
import collections
import hashlib
import json
from pathlib import Path
import random
import urllib.request

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "assets"
DATA.mkdir(parents=True, exist_ok=True)
SOURCES = {
    "longmemeval_s_cleaned.json": "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json",
    "longmemeval_oracle.json": "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_oracle.json",
    "sentencepiece.bpe.model": "https://huggingface.co/BAAI/bge-m3/resolve/main/sentencepiece.bpe.model",
}
manifest = {"seed": 20261008, "assets": {}}
for name, url in SOURCES.items():
    destination = DATA / name
    if not destination.exists():
        urllib.request.urlretrieve(url, destination)
    manifest["assets"][name] = {
        "source": url,
        "bytes": destination.stat().st_size,
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
    }
questions = json.loads((DATA / "longmemeval_s_cleaned.json").read_text())
assert len(questions) == 500
categories = collections.defaultdict(list)
for row in questions:
    if not row["question_id"].endswith("_abs"):
        categories[row["question_type"]].append(row["question_id"])
rng = random.Random(manifest["seed"])
selected = {}
for category in sorted(categories):
    selected[category] = rng.sample(sorted(categories[category]), 5)
assert len(selected) == 6
manifest["selected_by_category"] = selected
ids = {qid for group in selected.values() for qid in group}
manifest["selected_question_ids"] = [q["question_id"] for q in questions if q["question_id"] in ids]
(ROOT / "pilot-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps({"question_count": len(questions), "pilot_count": len(ids), "categories": list(selected), "assets": manifest["assets"]}, indent=2))
