"""Coverage levels (design doc 4): universe for everyone, numbers for every filer, deep coverage
(AI extraction, model updates, reports, alerts) for the watchlist or on demand."""

from typing import Any

from sqlalchemy import delete, exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from analekh.config import get_settings
from analekh.db.models import Company, Watchlist


def _user(user_id: str | None) -> str:
    return user_id or get_settings().default_user_id


def add(
    session: Session,
    company: Company,
    user_id: str | None = None,
    settings: dict[str, Any] | None = None,
) -> None:
    stmt = insert(Watchlist).values(
        user_id=_user(user_id), company_id=company.id, settings=settings or {}
    )
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["user_id", "company_id"], set_={"settings": stmt.excluded.settings}
        )
    )


def remove(session: Session, company: Company, user_id: str | None = None) -> None:
    session.execute(
        delete(Watchlist).where(
            Watchlist.user_id == _user(user_id), Watchlist.company_id == company.id
        )
    )


def entries(session: Session, user_id: str | None = None) -> list[Watchlist]:
    return list(
        session.scalars(
            select(Watchlist)
            .where(Watchlist.user_id == _user(user_id))
            .order_by(Watchlist.added_at)
        )
    )


def is_watched(session: Session, company_id: int) -> bool:
    """Any user watching the company makes it deep coverage for background work."""
    return bool(session.scalar(select(exists().where(Watchlist.company_id == company_id))))


def level(session: Session, company: Company) -> str:
    """universe | numbers | deep, for display on the company page."""
    if is_watched(session, company.id):
        return "deep"
    from analekh.db.models import Filing

    has_filing = session.scalar(select(exists().where(Filing.company_id == company.id)))
    return "numbers" if has_filing else "universe"
