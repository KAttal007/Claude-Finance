"""Q&A over a company's filings with page citations (design doc 11.1, F12).

Hybrid retrieval: pgvector cosine similarity plus PostgreSQL full-text rank, merged by
reciprocal rank fusion.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from analekh.db.models import Chunk, Document, Filing

RRF_K = 60


def hybrid_search(
    session: Session, company_id: int, query: str, k: int = 8, embedder: Any = None
) -> list[dict[str, Any]]:
    base = (
        select(Chunk, Filing)
        .join(Document, Chunk.document_id == Document.id)
        .join(Filing, Document.filing_id == Filing.id)
        .where(Filing.company_id == company_id)
    )
    ranked: dict[int, float] = {}
    rows: dict[int, tuple[Chunk, Filing]] = {}

    tsq = func.websearch_to_tsquery("english", query)
    for rank, (chunk, filing) in enumerate(
        session.execute(
            base.where(Chunk.tsv.op("@@")(tsq))
            .order_by(func.ts_rank(Chunk.tsv, tsq).desc())
            .limit(k * 3)
        ).all()
    ):
        ranked[chunk.id] = ranked.get(chunk.id, 0) + 1 / (RRF_K + rank)
        rows[chunk.id] = (chunk, filing)

    if embedder is not None:
        vec = embedder.embed([query])[0]
        for rank, (chunk, filing) in enumerate(
            session.execute(
                base.where(Chunk.embedding.is_not(None))
                .order_by(Chunk.embedding.cosine_distance(vec))
                .limit(k * 3)
            ).all()
        ):
            ranked[chunk.id] = ranked.get(chunk.id, 0) + 1 / (RRF_K + rank)
            rows[chunk.id] = (chunk, filing)

    best = sorted(ranked, key=lambda cid: -ranked[cid])[:k]
    return [
        {
            "text": rows[cid][0].text,
            "page": rows[cid][0].page,
            "document": f"{rows[cid][1].kind} {rows[cid][1].period_end or ''}".strip(),
            "source": f"filing:{rows[cid][1].id} page:{rows[cid][0].page}",
        }
        for cid in best
    ]
