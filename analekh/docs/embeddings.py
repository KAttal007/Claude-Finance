"""Embeddings for search and Q&A. Anthropic has no embeddings model, so this is either a local
sentence-transformers model or a hosted API (open question 22.5). The vector dimension in
analekh.db.models.EMBEDDING_DIM must match the model chosen."""

from typing import Protocol

from sqlalchemy.orm import Session

from analekh.config import get_settings
from analekh.db.models import Chunk, Document
from analekh.docs.chunking import TextChunk

# 1024-dim, multilingual-capable, runs on CPU. Swap freely; then update EMBEDDING_DIM + migrate.
LOCAL_MODEL = "BAAI/bge-large-en-v1.5"


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LocalEmbedder:
    def __init__(self, model_name: str = LOCAL_MODEL) -> None:
        from sentence_transformers import SentenceTransformer  # pip install .[embeddings]

        self.model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self.model.encode(texts, normalize_embeddings=True)]


def get_embedder() -> Embedder:
    provider = get_settings().embeddings_provider
    if provider == "local":
        return LocalEmbedder()
    raise NotImplementedError(f"embeddings provider {provider!r}: add a client here (Phase 3)")


def store_chunks(
    session: Session,
    document: Document,
    chunks: list[TextChunk],
    embedder: Embedder | None,
    batch: int = 64,
) -> int:
    for i in range(0, len(chunks), batch):
        part = chunks[i : i + batch]
        vectors = embedder.embed([c.text for c in part]) if embedder else [None] * len(part)
        for c, vec in zip(part, vectors, strict=True):
            session.add(
                Chunk(document_id=document.id, page=c.page, ord=c.ord, text=c.text, embedding=vec)
            )
    return len(chunks)
