from __future__ import annotations

import os
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import torch
import torch.nn.functional as F


TASK_ADAPTERS = {
    "retrieval.query": "retrieval_query",
    "retrieval.passage": "retrieval_passage",
    "separation": "separation",
    "classification": "classification",
    "text-matching": "text_matching",
}


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str | None = None
    task: str | None = None
    truncate: bool = True


class EmbeddingDatum(BaseModel):
    object: str = "embedding"
    index: int
    embedding: list[float]


class EmbeddingUsage(BaseModel):
    prompt_tokens: int
    total_tokens: int


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: list[EmbeddingDatum]
    model: str
    usage: EmbeddingUsage


class HealthResponse(BaseModel):
    service: str
    status: str
    model_id: str = Field(alias="modelId")
    model_loaded: bool = Field(alias="modelLoaded")

    model_config = {"populate_by_name": True}


class LocalJinaEmbeddingService:
    def __init__(self, *, model_id: str, max_length: int) -> None:
        self.model_id = model_id
        self.max_length = max_length
        self._lock = Lock()
        self._model: Any | None = None
        self._tokenizer: Any | None = None
        self._loaded_adapters: set[str] = set()

    def is_loaded(self) -> bool:
        return self._model is not None and self._tokenizer is not None

    def _load_model(self) -> Any:
        if self._model is not None and self._tokenizer is not None:
            return self._model, self._tokenizer

        with self._lock:
            if self._model is None or self._tokenizer is None:
                from transformers import AutoModel, AutoTokenizer

                self._tokenizer = AutoTokenizer.from_pretrained(self.model_id)
                self._model = AutoModel.from_pretrained(
                    self.model_id,
                    torch_dtype=torch.float32,
                )
                self._model.eval()
        return self._model, self._tokenizer

    def embed(self, texts: list[str], *, task: str | None, truncate: bool) -> list[list[float]]:
        model, tokenizer = self._load_model()
        adapter_name = TASK_ADAPTERS.get(task or default_task)
        if adapter_name is None:
            raise HTTPException(status_code=400, detail=f"Unsupported embedding task: {task}")

        with self._lock:
            if adapter_name not in self._loaded_adapters:
                model.load_adapter(
                    self.model_id,
                    adapter_name=adapter_name,
                    adapter_kwargs={"subfolder": adapter_name},
                )
                self._loaded_adapters.add(adapter_name)
            model.set_adapter(adapter_name)

        tokenize_kwargs: dict[str, Any] = {
            "padding": True,
            "return_tensors": "pt",
            "truncation": truncate,
        }
        if truncate:
            tokenize_kwargs["max_length"] = self.max_length
        try:
            encoded = tokenizer(texts, **tokenize_kwargs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        with torch.no_grad():
            outputs = model(**encoded)

        attention_mask = encoded["attention_mask"].unsqueeze(-1)
        pooled = (outputs.last_hidden_state * attention_mask).sum(dim=1)
        pooled = pooled / attention_mask.sum(dim=1).clamp(min=1e-9)
        normalized = F.normalize(pooled, p=2, dim=1)
        return normalized.cpu().tolist()


model_id = os.getenv("LOCAL_EMBEDDING_MODEL", "jinaai/jina-embeddings-v3-hf")
max_length = int(os.getenv("LOCAL_EMBEDDING_MAX_LENGTH", "8192"))
default_task = os.getenv("LOCAL_EMBEDDING_DEFAULT_TASK", "retrieval.passage")
service = LocalJinaEmbeddingService(model_id=model_id, max_length=max_length)
app = FastAPI(title="local-jina-embeddings")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        service="local-jina-embeddings",
        status="ok",
        modelId=service.model_id,
        modelLoaded=service.is_loaded(),
    )


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
def create_embeddings(request: EmbeddingRequest) -> EmbeddingResponse:
    texts = [request.input] if isinstance(request.input, str) else request.input
    normalized_texts = [text for text in texts if text.strip()]
    if len(normalized_texts) != len(texts):
        raise HTTPException(status_code=400, detail="Embedding inputs must not contain empty strings.")

    requested_model = request.model or service.model_id
    if requested_model != service.model_id:
        raise HTTPException(
            status_code=400,
            detail=f"Configured model is {service.model_id}, requested {requested_model}.",
        )

    task = request.task or default_task
    vectors = service.embed(normalized_texts, task=task, truncate=request.truncate)
    usage = EmbeddingUsage(prompt_tokens=0, total_tokens=0)
    return EmbeddingResponse(
        data=[
            EmbeddingDatum(index=index, embedding=vector)
            for index, vector in enumerate(vectors)
        ],
        model=service.model_id,
        usage=usage,
    )
