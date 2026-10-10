"""Batch and cache upstream BGE-M3 calls for repeatable benchmark runs."""
import hashlib
import json
import os
from pathlib import Path
import queue
import sqlite3
import threading
import time

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
ENV = dict(line.split("=", 1) for line in (ROOT / "runtime.env").read_text().splitlines()
           if "=" in line and not line.startswith("#"))
DB = sqlite3.connect(ROOT / "runtime/bgem3-cache.sqlite", check_same_thread=False)
DB.execute("CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, vector TEXT)")
DB.execute("CREATE TABLE IF NOT EXISTS usage (at REAL, inputs INTEGER, tokens INTEGER, status INTEGER)")
LOCK = threading.Lock()
PENDING = queue.Queue()
app = FastAPI()


def cache_key(text):
    return hashlib.sha256((ENV["EMBEDDING_BASE_URL"] + "|bge-m3|" + text).encode()).hexdigest()


def worker():
    session = requests.Session()
    while True:
        batch = [PENDING.get()]
        deadline = time.monotonic() + 0.2
        while len(batch) < 8 and len(batch[0]) == 3:
            try:
                batch.append(PENDING.get(timeout=max(0.001, deadline - time.monotonic())))
            except queue.Empty:
                break
            if time.monotonic() >= deadline:
                break
            if len(batch[-1]) == 4:
                PENDING.put(batch.pop())
                break
        response = None
        try:
            for attempt in range(9):
                response = session.post(ENV["EMBEDDING_BASE_URL"].rstrip("/") + "/embeddings",
                                        headers={"Authorization": "Bearer " + ENV["EMBEDDING_API_KEY"]},
                                        json={"model": "bge-m3", "input": [item[0] for item in batch]},
                                        timeout=120)
                if response.status_code not in (429, 500, 502, 503, 504):
                    break
                time.sleep(min(2 ** attempt, 30))
            if response.status_code in (400, 403, 413, 422) and len(batch) > 1:
                # An invalid input must not discard the other texts in its batch.
                for item in batch:
                    PENDING.put((*item[:3], True))
                batch = []
                continue
            response.raise_for_status()
            payload = response.json()
            vectors = sorted(payload["data"], key=lambda x: x["index"])
            if len(vectors) != len(batch) or any(len(x["embedding"]) != 1024 for x in vectors):
                raise ValueError("invalid embedding response")
            with LOCK:
                for item, value in zip(batch, vectors):
                    DB.execute("INSERT OR REPLACE INTO embeddings VALUES (?, ?)",
                               (cache_key(item[0]), json.dumps(value["embedding"])))
                    item[2]["vector"] = value["embedding"]
                DB.execute("INSERT INTO usage VALUES (?, ?, ?, ?)",
                           (time.time(), len(batch), payload.get("usage", {}).get("total_tokens", 0), 200))
                DB.commit()
        except Exception as exc:
            status = response.status_code if response is not None else 502
            for item in batch:
                item[2]["error"] = f"upstream embedding status={status}: {type(exc).__name__}"
            with LOCK:
                DB.execute("INSERT INTO usage VALUES (?, ?, ?, ?)", (time.time(), len(batch), 0, status))
                DB.commit()
        finally:
            for item in batch:
                item[1].set()


threading.Thread(target=worker, daemon=True).start()


class Request(BaseModel):
    model: str
    input: str | list[str]


@app.get("/health")
def health():
    with LOCK:
        count = DB.execute("SELECT count(*) FROM embeddings").fetchone()[0]
        calls, tokens = DB.execute("SELECT count(*), coalesce(sum(tokens),0) FROM usage WHERE status=200").fetchone()
    return {"model": "bge-m3", "dimension": 1024, "cached_inputs": count,
            "upstream_calls": calls, "upstream_tokens": tokens, "queued": PENDING.qsize()}


@app.post("/v1/embeddings")
def embed(request: Request):
    if request.model != "bge-m3":
        raise HTTPException(400, "Expected bge-m3")
    texts = [request.input] if isinstance(request.input, str) else request.input
    items = []
    for text in texts:
        with LOCK:
            cached = DB.execute("SELECT vector FROM embeddings WHERE key=?", (cache_key(text),)).fetchone()
        event, result = threading.Event(), {}
        if cached:
            result["vector"] = json.loads(cached[0])
            event.set()
        else:
            PENDING.put((text, event, result))
        items.append((event, result))
    values = []
    for index, (event, result) in enumerate(items):
        if not event.wait(360) or "error" in result:
            raise HTTPException(502, result.get("error", "embedding timeout"))
        values.append({"object": "embedding", "index": index, "embedding": result["vector"]})
    return {"object": "list", "model": "bge-m3", "data": values}
