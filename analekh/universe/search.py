"""Company search with autocomplete (design doc F2, 20): exact and prefix symbol matches first,
then trigram similarity on the name (pg_trgm GIN index)."""

from dataclasses import dataclass

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from analekh.db.models import Company


@dataclass(frozen=True)
class SearchHit:
    id: int
    nse_symbol: str
    name: str
    isin: str | None
    sector: str | None
    is_active: bool
    score: float


def search(
    session: Session, q: str, limit: int = 10, include_inactive: bool = False
) -> list[SearchHit]:
    q = q.strip()
    if not q:
        return []
    sym = q.upper()
    similarity = func.similarity(Company.name, q)
    rank = (
        case(
            (Company.nse_symbol == sym, 3.0),
            (Company.nse_symbol.startswith(sym), 2.0),
            (Company.isin == sym, 3.0),
            else_=0.0,
        )
        + similarity
    )
    stmt = (
        select(Company, rank.label("rank"))
        .where(
            or_(
                Company.nse_symbol.startswith(sym),
                Company.isin == sym,
                Company.name.op("%")(q),
                Company.name.ilike(f"%{q}%"),
            )
        )
        .order_by(rank.desc(), Company.nse_symbol)
        .limit(limit)
    )
    if not include_inactive:
        stmt = stmt.where(Company.is_active)
    return [
        SearchHit(c.id, c.nse_symbol, c.name, c.isin, c.sector, c.is_active, float(r))
        for c, r in session.execute(stmt).all()
    ]


def get(session: Session, symbol: str) -> Company | None:
    return session.scalar(select(Company).where(Company.nse_symbol == symbol.strip().upper()))
