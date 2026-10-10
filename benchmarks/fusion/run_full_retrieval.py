"""Serial, resumable full retrieval-only benchmark; credentials stay in env."""
import hashlib
import json
import os
from pathlib import Path
import signal
import shlex
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
BENCH = REPO.parent / "moi-benchmark/memoria"
RUNTIME = ROOT / "runtime"
PYTHON = RUNTIME / "embed-venv/bin/python"
API = "http://127.0.0.1:18100"
STATE = RUNTIME / "full-execution-state.json"
LME = BENCH / "runs/fusion-lme-bgem3-full500-v2"
LOCOMO = BENCH / "runs/fusion-locomo-bgem3-full1540-v1"
sys.path.insert(0, str(BENCH / "scripts/longmemeval"))
from ingest import read_env

ENV = {**os.environ, **read_env(ROOT / "runtime.env")}
ENV.update(EMBEDDING_BASE_URL="http://127.0.0.1:18200/v1",
           MEMORIA_SENSITIVITY_FILTER_ENABLED="false", ENTITY_POOL_SIZE="0",
           MEMORIA_GOVERNANCE_ENABLED="false", PORT="18100")
KEY = ENV["MEMORIA_MASTER_KEY"]
API_PID = 41225
API_PROC = None
VARIANT = "rrf"
if STATE.exists():
    previous_state = json.loads(STATE.read_text())
    API_PID = previous_state.get("api_pid", API_PID)
    VARIANT = previous_state.get("variant", VARIANT)


def stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def state(stage, status="running", **extra):
    atomic(STATE, {"updated_at": stamp(), "orchestrator_pid": os.getpid(),
                  "stage": stage, "status": status, "api_pid": API_PID,
                  "variant": VARIANT, **extra})
    print(stamp(), stage, status, extra, flush=True)


def request(path, post=False, timeout=60):
    req = urllib.request.Request(API + path, data=b"" if post else None,
                                 headers={"Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def healthy():
    try:
        return request("/health/instance", timeout=8).get("db") is True
    except Exception:
        return False


def api_process_alive(pid):
    try:
        reaped, _ = os.waitpid(pid, os.WNOHANG)
        if reaped:
            return False
    except ChildProcessError:
        pass
    proc = subprocess.run(["ps", "-p", str(pid), "-o", "stat=,command="],
                          capture_output=True, text=True)
    line = proc.stdout.strip()
    if not line:
        return False
    status, command = line.split(None, 1)
    if status.startswith("Z"):
        return False
    args = shlex.split(command)
    expected = {str((RUNTIME / f"bin/full-{v}-memoria").resolve()) for v in ("rrf", "baseline")}
    if not args or str(Path(args[0]).resolve()) not in expected or "serve" not in args:
        raise RuntimeError("Refusing to stop an unexpected process at saved API PID")
    return True


def stop_api():
    global API_PROC
    if API_PROC is not None and API_PROC.pid == API_PID:
        if API_PROC.poll() is not None:
            API_PROC.wait()
            API_PROC = None
            return
    if not api_process_alive(API_PID):
        API_PROC = None
        return
    try:
        os.kill(API_PID, signal.SIGTERM)
    except ProcessLookupError:
        pass
    for _ in range(60):
        if not api_process_alive(API_PID):
            if API_PROC is not None:
                API_PROC.poll()
            API_PROC = None
            break
        time.sleep(1)
    else:
        raise RuntimeError("API did not stop cleanly")


def switch(variant):
    global API_PID, API_PROC, VARIANT
    stop_api()
    VARIANT = variant
    with (RUNTIME / f"full-{variant}-api.log").open("a") as log:
        proc = subprocess.Popen([str(RUNTIME / f"bin/full-{variant}-memoria"),
                                 "serve", "--port", "18100"], cwd=REPO,
                                env=ENV, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
    API_PID = proc.pid
    API_PROC = proc
    for _ in range(90):
        if healthy():
            config = request("/admin/config")
            for key, expected in {"embedding_model": "bge-m3", "embedding_dim": 1024,
                                  "embedding_base_url": ENV["EMBEDDING_BASE_URL"]}.items():
                if config.get(key) != expected:
                    raise RuntimeError("Embedding configuration mismatch: " + key)
            state("api-ready")
            return
        if proc.poll() is not None:
            raise RuntimeError("API exited before ready")
        time.sleep(2)
    raise RuntimeError("API did not become healthy")


def recover():
    if healthy():
        return
    # Three failed DB health checks establish an unusable instance.
    for _ in range(2):
        time.sleep(5)
        if healthy():
            return
    state("matrixone-recovery")
    subprocess.run(["docker", "restart", "memoria-fusion-matrixone"], check=True,
                   stdout=subprocess.DEVNULL)
    time.sleep(15)
    switch(VARIANT)


def run(stage, command, attempts=3, evaluation=False):
    log_path = RUNTIME / (stage + ".log")
    for attempt in range(1, attempts + 1):
        recover()
        state(stage, attempt=attempt, log=str(log_path))
        with log_path.open("a") as log:
            result = subprocess.run([str(PYTHON), *map(str, command)], cwd=BENCH,
                                    env=ENV, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode == 0:
            return
        if evaluation:
            state(stage, "evaluation-gate-failed", exit_code=result.returncode)
            return
        state(stage, "retrying", exit_code=result.returncode)
        recover()
    raise RuntimeError(stage + " exhausted retries")


def prepare_graph(run_dir, user_ids):
    state("graph-preparation", dataset=run_dir.name, total=len(user_ids))
    output = run_dir / "graph-preparation.jsonl"
    done = set()
    if output.exists():
        done = {json.loads(line)["user_id"] for line in output.read_text().splitlines()}
    for index, uid in enumerate(user_ids, 1):
        if uid in done:
            continue
        started = time.monotonic()
        for attempt in range(3):
            try:
                record = request("/admin/governance/" + uid +
                                 "/trigger?op=extract_entities", post=True, timeout=300)
                break
            except Exception as exc:
                state("graph-preparation", dataset=run_dir.name,
                      completed=index - 1, total=len(user_ids),
                      user_id=uid, attempt=attempt + 1,
                      error_type=type(exc).__name__,
                      http_status=getattr(exc, "code", None))
                recover()
                if attempt < 2:
                    time.sleep(2 ** attempt)
        else:
            raise RuntimeError("Graph preparation failed for " + uid)
        with output.open("a") as f:
            f.write(json.dumps({"at": stamp(), "elapsed_seconds": round(time.monotonic() - started, 3), **record}) + "\n")
        state("graph-preparation", dataset=run_dir.name,
              completed=index, total=len(user_ids),
              elapsed_seconds=round(time.monotonic() - started, 3))


def reset_counts(user_ids, run_dir):
    rows = []
    for uid in user_ids:
        recover()
        rows.append(request("/admin/users/" + uid + "/reset-access-counts", post=True))
    atomic(run_dir / "access-count-reset.json", rows)


def provenance(run_dir, variant):
    build = json.loads((ROOT / "build-provenance/full-build.json").read_text())
    binary = RUNTIME / f"bin/full-{variant}-memoria"
    atomic(run_dir / "execution-provenance.json", {
        "at": stamp(), "variant": variant, "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "build": build, "batch_backfill_build": json.loads((ROOT / "build-provenance/full-batch-build-v2.json").read_text()),
        "embedding_model": "bge-m3", "embedding_dim": 1024,
        "embedding_proxy": ENV["EMBEDDING_BASE_URL"], "workers": 1,
        "background_entity_extraction": False, "governance": False,
        "graph_preparation": "same frozen graph for both variants; default backfill API caps each user at 500 active memories",
        "reader_or_judge": False})


def has_snapshot(run_dir):
    path = run_dir / "retrieval.jsonl"
    return path.exists() and path.stat().st_size > 0


def completed_retrieval(run_dir, variant, selected_ids, graph_dir, user_ids, top_k):
    if not has_snapshot(run_dir):
        return False
    try:
        saved = json.loads((run_dir / "execution-provenance.json").read_text())
    except (OSError, ValueError):
        raise RuntimeError("Existing retrieval lacks valid execution provenance")
    binary_hash = hashlib.sha256((RUNTIME / f"bin/full-{variant}-memoria").read_bytes()).hexdigest()
    if saved.get("variant") != variant or saved.get("binary_sha256") != binary_hash:
        raise RuntimeError("Existing retrieval binary provenance differs; refusing overwrite")
    manifest = json.loads((run_dir / "manifest.json").read_text())
    if manifest.get("selected_question_ids") != selected_ids or manifest.get("top_k") != top_k:
        raise RuntimeError("Existing retrieval selection differs; refusing overwrite")
    graph_rows = [json.loads(line) for line in (graph_dir / "graph-preparation.jsonl").read_text().splitlines()]
    if not set(user_ids).issubset({row.get("user_id") for row in graph_rows}):
        raise RuntimeError("Existing retrieval graph checkpoint incomplete")
    latest = {}
    with (run_dir / "retrieval.jsonl").open() as snapshot:
        for line in snapshot:
            row = json.loads(line)
            latest[str(row["question_id"])] = row
    if any(qid not in latest or latest[qid].get("status") != "success"
           or latest[qid].get("validation_ok") is not True
           or len(latest[qid].get("results", [])) != top_k for qid in selected_ids):
        return False
    try:
        summary = json.loads((run_dir / "summary.json").read_text())
        metrics = json.loads((run_dir / "metrics.json").read_text())
    except (OSError, ValueError):
        return False
    count = len(selected_ids)
    operational = metrics.get("operational", {})
    if top_k == 20:
        return (all(summary.get(k) == v for k, v in {"selected_questions": count,
                "snapshot_records": count, "successful_questions": count, "failed_questions": 0}.items())
                and all(operational.get(k) == v for k, v in {"selected_questions": count,
                    "snapshot_records": count, "final_successes": count, "final_failures": 0}.items())
                and metrics.get("stability_gate", {}).get("passed") is True)
    return (summary.get("complete") is True and summary.get("valid_retrievals") == count
            and summary.get("failed_or_invalid_retrievals") == 0
            and operational.get("valid_retrievals") == count)


def main():
    state("waiting-lme-ingest")
    summary_path = LME / "ingest/summary.json"
    while not summary_path.exists():
        time.sleep(10)
    summary = json.loads(summary_path.read_text())
    if any(summary.get(k) != v for k, v in {"selected_questions": 500,
            "completed_questions": 500, "failed_chunks": 0}.items()) or summary.get("question_failures"):
        raise RuntimeError("LME ingest acceptance failed")
    questions = json.loads((ROOT / "assets/longmemeval_s_cleaned.json").read_text())
    lme_users = ["fusion-lme-bgem3-v2-" + q["question_id"] for q in questions]
    graph_checkpoint = LME / "graph-preparation.jsonl"
    graph_done = ({json.loads(line).get("user_id") for line in graph_checkpoint.read_text().splitlines()}
                  if graph_checkpoint.exists() else set())
    if not set(lme_users).issubset(graph_done):
        switch("rrf")
        prepare_graph(LME, lme_users)
    for variant in ["rrf", "baseline"]:
        out = LME / "retrieval" / (variant + "-top20-full500-v1")
        if completed_retrieval(out, variant, [str(q["question_id"]) for q in questions],
                               LME, lme_users, 20):
            state("full-lme-" + variant, "skipped-complete")
            continue
        if VARIANT != variant or not healthy():
            switch(variant)
        out.mkdir(parents=True, exist_ok=True)
        if not has_snapshot(out):
            reset_counts(lme_users, out)
            provenance(out, variant)
        run("full-lme-" + variant + "-retrieve", [BENCH / "scripts/longmemeval/retrieve.py",
            "--dataset", ROOT / "assets/longmemeval_s_cleaned.json", "--runtime-env", ROOT / "runtime.env",
            "--user-prefix", "fusion-lme-bgem3-v2-", "--run-dir", out, "--api-url", API,
            "--limit", "500", "--workers", "1", "--top-k", "20", "--explain", "verbose",
            "--timeout", "180", "--max-retries", "3", "--memoria-commit", "6247235+" + variant])
        run("full-lme-" + variant + "-evaluate", [BENCH / "scripts/longmemeval/evaluate_retrieval.py",
            "--run-dir", out, "--max-p95-ms", "60000"], evaluation=True)
    switch("rrf")
    run("full-locomo-resume-ingest", [BENCH / "scripts/locomo/ingest.py",
        "--dataset", BENCH / "datasets/downloads/public-benchmarks/locomo/locomo10.json",
        "--runtime-env", ROOT / "runtime.env", "--tokenizer-model", ROOT / "assets/sentencepiece.bpe.model",
        "--run-dir", LOCOMO / "ingest", "--api-url", API, "--user-prefix", "fusion-locomo-bgem3-",
        "--max-tokens", "7000", "--workers", "1", "--timeout", "180", "--max-retries", "5",
        "--memoria-commit", "6247235+rrf-benchmark"])
    sys.path.insert(0, str(BENCH / "scripts/locomo"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("locomo_retrieve", BENCH / "scripts/locomo/retrieve.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dataset = BENCH / "datasets/downloads/public-benchmarks/locomo/locomo10.json"
    module.validate_ingest_run(LOCOMO / "ingest", module.sha256_file(dataset), "fusion-locomo-bgem3-")
    samples = json.loads(dataset.read_text())
    loco_users = ["fusion-locomo-bgem3-" + str(s["sample_id"]) for s in samples]
    prepare_graph(LOCOMO, loco_users)
    loco_questions, _ = module.load_questions(dataset)
    for variant in ["rrf", "baseline"]:
        out = LOCOMO / "retrieval" / (variant + "-top200-full1540-v1")
        if completed_retrieval(out, variant, [str(q["question_id"]) for q in loco_questions],
                               LOCOMO, loco_users, 200):
            state("full-locomo-" + variant, "skipped-complete")
            continue
        if VARIANT != variant:
            switch(variant)
        out.mkdir(parents=True, exist_ok=True)
        if not has_snapshot(out):
            reset_counts(loco_users, out)
            provenance(out, variant)
        # This runner includes deterministic retrieval evaluation; no LLM judge.
        run("full-locomo-" + variant + "-retrieve", [BENCH / "scripts/locomo/retrieve.py",
            "--dataset", dataset, "--runtime-env", ROOT / "runtime.env",
            "--runtime-api-route", REPO.parent / "memoria-fusion-baseline/memoria/crates/memoria-api/src/routes/memory.rs",
            "--ingest-run-dir", LOCOMO / "ingest", "--user-prefix", "fusion-locomo-bgem3-",
            "--run-dir", out, "--api-url", API, "--workers", "1", "--explain", "verbose",
            "--timeout", "180", "--max-retries", "3"])
    state("full-retrieval-comparison", "complete")


if __name__ == "__main__":
    if STATE.exists():
        previous_pid = json.loads(STATE.read_text()).get("orchestrator_pid")
        if previous_pid and previous_pid != os.getpid():
            try:
                os.kill(previous_pid, 0)
            except ProcessLookupError:
                pass
            else:
                print("Existing full orchestrator is running; refusing duplicate", flush=True)
                raise SystemExit(2)
    try:
        main()
    except Exception as exc:
        state("orchestration", "failed", error_type=type(exc).__name__)
        raise SystemExit(1)
