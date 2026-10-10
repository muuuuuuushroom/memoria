"""OpenAI-compatible adapter for a real local FastEmbed ONNX model."""
import os
from pathlib import Path
import threading

from fastapi import FastAPI, HTTPException
from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType
from pydantic import BaseModel

MODEL = os.environ.get("FUSION_EMBEDDING_MODEL", "BAAI/bge-m3")
if MODEL == "BAAI/bge-m3":
    TextEmbedding.add_custom_model(
        model=MODEL, pooling=PoolingType.CLS, normalization=True,
        sources=ModelSource(hf="BAAI/bge-m3"), dim=1024,
        model_file="onnx/model.onnx", additional_files=[
            "onnx/model.onnx_data", "onnx/Constant_7_attr__value"],
        description="Official BGE-M3 ONNX export", license="MIT")
model = TextEmbedding(model_name=MODEL, max_length=512,
                      cache_dir=str(Path(__file__).parent / "runtime/model-cache"),
                      threads=4)
lock = threading.Lock()
app = FastAPI()


class EmbeddingsRequest(BaseModel):
    input: str | list[str]
    model: str


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL, "max_length": 512, "dimension": 384 if "small" in MODEL else 1024}


@app.post("/v1/embeddings")
def embeddings(request: EmbeddingsRequest):
    if request.model != MODEL:
        raise HTTPException(400, "Unexpected embedding model")
    texts = [request.input] if isinstance(request.input, str) else request.input
    with lock:
        vectors = list(model.embed(texts))
    return {"object": "list", "model": MODEL, "data": [
        {"object": "embedding", "index": i, "embedding": vector.tolist()}
        for i, vector in enumerate(vectors)
    ]}
