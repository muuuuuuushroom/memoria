"""Reuse the historical ingestion/retrieval scripts with a frozen pilot selection."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[1]
SCRIPTS = WORKSPACE.parent / "moi-benchmark/memoria/scripts/longmemeval"
RUN = WORKSPACE.parent / "moi-benchmark/memoria/runs/fusion-lme-maas-bge-m3-v1"
manifest = json.loads((ROOT / "pilot-manifest.json").read_text())
parser = argparse.ArgumentParser()
parser.add_argument("stage", choices=["dry-run", "ingest", "baseline", "modified"])
args = parser.parse_args()
ids = [flag for qid in manifest["selected_question_ids"] for flag in ("--question-id", qid)]
common = ["--dataset", str(ROOT / "assets/longmemeval_s_cleaned.json"),
          "--runtime-env", str(ROOT / "runtime.env"), "--user-prefix", "fusion-lme-maas-bge-m3-"]
if args.stage in ("dry-run", "ingest"):
    command = [sys.executable, str(SCRIPTS / "ingest.py"), *common, *ids,
               "--run-dir", str(RUN / ("ingest30" if args.stage == "ingest" else args.stage)), "--api-url", "http://127.0.0.1:18100",
               "--tokenizer-model", str(ROOT / "assets/sentencepiece.bpe.model"),
               "--max-tokens", "7000", "--subject-per-session", "--workers", "4",
               "--timeout", "180", "--memoria-commit", "6247235"]
    if args.stage == "dry-run":
        command.append("--dry-run")
else:
    command = [sys.executable, str(SCRIPTS / "retrieve.py"), *common, *ids,
               "--run-dir", str(RUN / args.stage), "--api-url", "http://127.0.0.1:18100",
               "--top-k", "20", "--workers", "1", "--timeout", "180",
               "--memoria-commit", "6247235" if args.stage == "baseline" else "6247235+fusion"]
subprocess.run(command, check=True)
if args.stage in ("baseline", "modified"):
    subprocess.run([sys.executable, str(SCRIPTS / "evaluate_retrieval.py"),
                    "--run-dir", str(RUN / args.stage), "--max-p95-ms", "60000"], check=True)
