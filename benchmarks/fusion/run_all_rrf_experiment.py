"""Run two serial all-channel RRF experiments on the frozen LME-S graph.

The caller pauses ingestion before launching this script and resumes it afterward.
This script owns only its API on 18101; it never controls the API on 18100.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
BENCH = REPO.parent / "moi-benchmark/memoria"
RUNTIME = ROOT / "runtime"
PYTHON = RUNTIME / "embed-venv/bin/python"
BINARY = RUNTIME / "bin/all-rrf-memoria"
API = "http://127.0.0.1:18101"
PROXY = "http://127.0.0.1:18200/v1"
LME = BENCH / "runs/fusion-lme-bgem3-full500-v2"
DATASET = ROOT / "assets/longmemeval_s_cleaned.json"
STATE = RUNTIME / "all-rrf-execution-state.json"
PAUSED = RUNTIME / "all-rrf-paused-locomo.json"
API_PROC = None


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n")
    temp.replace(path)


def state(stage, status="running", **extra):
    record = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "stage": stage, "status": status, "orchestrator_pid": os.getpid(),
              "api_pid": API_PROC.pid if API_PROC is not None else None, **extra}
    atomic(STATE, record)
    print(json.dumps(record), flush=True)


def request(path, key, post=False, timeout=60):
    req = urllib.request.Request(API + path, data=b"" if post else None,
                                 headers={"Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def stop_api():
    global API_PROC
    if API_PROC is None:
        return
    if API_PROC.poll() is None:
        API_PROC.terminate()
    API_PROC.wait(timeout=60)
    API_PROC = None


def paused_processes():
    record = json.loads(PAUSED.read_text())
    return [(record["scheduler_pid"], "run_full_retrieval.py"),
            (record["ingest_pid"], "scripts/locomo/ingest.py")]


def process_details(pid):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "stat=,command="],
                            capture_output=True, text=True)
    line = result.stdout.strip()
    return line.split(None, 1) if line else ("", "")


def validate_paused():
    for pid, expected in paused_processes():
        status, command = process_details(pid)
        if "T" not in status or expected not in command:
            raise RuntimeError("LoCoMo task is not safely paused")


def resume_paused():
    rows = []
    for pid, expected in paused_processes():
        status, command = process_details(pid)
        if not status:
            rows.append({"pid": pid, "status": "exited"})
        elif expected not in command:
            rows.append({"pid": pid, "status": "refused-command-mismatch"})
        elif "T" in status:
            try:
                os.kill(pid, signal.SIGCONT)
                rows.append({"pid": pid, "status": "resumed"})
            except ProcessLookupError:
                rows.append({"pid": pid, "status": "exited"})
        else:
            rows.append({"pid": pid, "status": "already-running"})
    atomic(RUNTIME / "all-rrf-locomo-resume.json", rows)
    print(json.dumps({"original_locomo_processes": rows}), flush=True)


def start_api(env, label, hybrid_weight):
    global API_PROC
    stop_api()
    try:
        with socket.create_connection(("127.0.0.1", 18101), timeout=2):
            raise RuntimeError("Experimental API port already occupied")
    except ConnectionRefusedError:
        pass
    configured = {**env, "RRF_ALL_CHANNELS": "true", "RRF_GRAPH_WEIGHT": "1",
                  "RRF_HYBRID_WEIGHT": str(hybrid_weight), "PORT": "18101"}
    with (RUNTIME / f"all-rrf-{label}-api.log").open("a") as log:
        API_PROC = subprocess.Popen([str(BINARY), "serve", "--port", "18101"],
                                    cwd=REPO, env=configured, stdout=log,
                                    stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(90):
        if API_PROC.poll() is not None:
            raise RuntimeError("Experimental API exited before health check")
        try:
            health = request("/health/instance", env["MEMORIA_MASTER_KEY"], timeout=5)
            if health.get("db") is True:
                config = request("/admin/config", env["MEMORIA_MASTER_KEY"])
                expected = {"embedding_model": "bge-m3", "embedding_dim": 1024,
                            "embedding_base_url": PROXY, "has_embedding": True}
                if any(config.get(k) != v for k, v in expected.items()):
                    raise RuntimeError("Experimental embedding config mismatch")
                return
        except (OSError, ValueError):
            pass
        time.sleep(2)
    raise RuntimeError("Experimental API failed health gate")


def prewarm(questions):
    state("embedding-prewarm", total=len(questions))
    for index, question in enumerate(questions, 1):
        req = urllib.request.Request(PROXY + "/embeddings",
            data=json.dumps({"model": "bge-m3", "input": str(question["question"])}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as response:
            data = json.load(response).get("data", [])
        if len(data) != 1:
            raise RuntimeError("Prewarm embedding count mismatch")
        vector = data[0].get("embedding", [])
        if len(vector) != 1024 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vector):
            raise RuntimeError("Prewarm embedding invalid")
        if index % 50 == 0:
            state("embedding-prewarm", completed=index, total=len(questions))
    atomic(RUNTIME / "all-rrf-prewarm.json", {"dataset_sha256": sha(DATASET),
           "queries": len(questions), "model": "bge-m3", "dimension": 1024,
           "proxy": PROXY, "success": True})


def execute(stage, command):
    state(stage)
    with (RUNTIME / (stage + ".log")).open("a") as log:
        code = subprocess.run([str(PYTHON), *map(str, command)], cwd=BENCH,
                              stdout=log, stderr=subprocess.STDOUT).returncode
    if code != 0:
        raise RuntimeError(stage + " failed")


def verify_snapshot(out, ids, hybrid_weight):
    latest = {}
    with (out / "retrieval.jsonl").open() as source:
        for line in source:
            row = json.loads(line)
            latest[str(row["question_id"])] = row
    if set(latest) != set(ids):
        raise RuntimeError("Experiment snapshot selection incomplete")
    for qid in ids:
        row = latest[qid]
        explain = row.get("explain", {})
        if (row.get("status") != "success" or row.get("validation_ok") is not True
                or len(row.get("results", [])) != 20):
            raise RuntimeError("Experiment snapshot validation failed")
        if not explain.get("vector_attempted") or not explain.get("graph_attempted"):
            raise RuntimeError("Embedding unavailable: rejecting experiment speed comparison")
        if (explain.get("fusion_policy") != "all_channels_rrf"
                or explain.get("channel_weight") != {"graph": 1.0, "hybrid": hybrid_weight}):
            raise RuntimeError("Experiment routing/weights not applied")


def accepted(out, ids, hybrid_weight):
    if not (out / "summary.json").exists() or not (out / "metrics.json").exists():
        return False
    summary = json.loads((out / "summary.json").read_text())
    expected = {"selected_questions": 500, "snapshot_records": 500,
                "successful_questions": 500, "failed_questions": 0}
    if any(summary.get(k) != v for k, v in expected.items()):
        return False
    metrics = json.loads((out / "metrics.json").read_text())
    if metrics.get("stability_gate", {}).get("passed") is not True:
        return False
    verify_snapshot(out, ids, hybrid_weight)
    return True


def main():
    sys.path.insert(0, str(BENCH / "scripts/longmemeval"))
    from ingest import read_env
    env = {**os.environ, **read_env(ROOT / "runtime.env")}
    env.update(EMBEDDING_BASE_URL=PROXY, MEMORIA_SENSITIVITY_FILTER_ENABLED="false",
               ENTITY_POOL_SIZE="0", MEMORIA_GOVERNANCE_ENABLED="false")
    key = env["MEMORIA_MASTER_KEY"]
    validate_paused()
    questions = json.loads(DATASET.read_text())
    if len(questions) != 500:
        raise RuntimeError("Expected all 500 LME-S questions")
    ids = [str(question["question_id"]) for question in questions]
    users = ["fusion-lme-bgem3-v2-" + qid for qid in ids]
    graph = LME / "graph-preparation.jsonl"
    done = {json.loads(line)["user_id"] for line in graph.read_text().splitlines()}
    if not set(users).issubset(done):
        raise RuntimeError("Frozen graph preparation is incomplete")
    prewarm(questions)
    completed = []
    for label, hybrid_weight in [("equal", 1.0), ("hybrid2", 2.0)]:
        out = LME / "retrieval" / f"all-rrf-{label}-top20-full500-v1"
        out.mkdir(parents=True, exist_ok=True)
        expected = {"binary_sha256": sha(BINARY), "dataset_sha256": sha(DATASET),
                    "graph_checkpoint_sha256": sha(graph), "policy": "all_channels_rrf",
                    "channel_weight": {"graph": 1.0, "hybrid": hybrid_weight},
                    "rrf_k": 60, "top_k": 20, "graph_candidate_depth": 20,
                    "hybrid_candidate_depth": 20, "workers": 1, "embedding_proxy": PROXY,
                    "build_provenance": json.loads((ROOT / "build-provenance/all-rrf-build.json").read_text()),
                    "routing_limit": "Requests both channels; does not ensure both contain candidates.",
                    "reader_or_judge": False}
        saved = out / "execution-provenance.json"
        snapshot = out / "retrieval.jsonl"
        if saved.exists():
            if json.loads(saved.read_text()) != expected:
                raise RuntimeError("Experiment provenance changed; refusing mixed snapshot")
        elif snapshot.exists() and snapshot.stat().st_size:
            raise RuntimeError("Existing experiment snapshot lacks provenance")
        else:
            atomic(saved, expected)
        if accepted(out, ids, hybrid_weight):
            state("all-rrf-" + label, "skipped-complete")
            completed.append(str(out))
            continue
        start_api(env, label, hybrid_weight)
        # Resume partial snapshots without perturbing already-observed accesses.
        if not snapshot.exists() or not snapshot.stat().st_size:
            state("all-rrf-" + label + "-reset-counts")
            reset = [request("/admin/users/" + user + "/reset-access-counts", key, post=True)
                     for user in users]
            atomic(out / "access-count-reset.json", reset)
        execute("all-rrf-" + label + "-retrieve", [BENCH / "scripts/longmemeval/retrieve.py",
            "--dataset", DATASET, "--runtime-env", ROOT / "runtime.env",
            "--user-prefix", "fusion-lme-bgem3-v2-", "--run-dir", out, "--api-url", API,
            "--limit", "500", "--workers", "1", "--top-k", "20", "--explain", "verbose",
            "--timeout", "180", "--max-retries", "3", "--memoria-commit", "6247235+all-rrf",
            "--memoria-patch-sha256", expected["build_provenance"]["all_rrf_patch_sha256"]])
        verify_snapshot(out, ids, hybrid_weight)
        execute("all-rrf-" + label + "-evaluate", [BENCH / "scripts/longmemeval/evaluate_retrieval.py",
            "--run-dir", out, "--max-p95-ms", "60000"])
        if not accepted(out, ids, hybrid_weight):
            raise RuntimeError("Experiment completeness/stability gate failed")
        completed.append(str(out))
        stop_api()
    state("all-rrf-experiments", "complete", runs=completed)


if __name__ == "__main__":
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        state("all-rrf-experiments", "failed", error_type=type(exc).__name__)
        raise SystemExit(1)
    finally:
        try:
            stop_api()
        finally:
            resume_paused()
