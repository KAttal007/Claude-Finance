"""Shared API dependencies. Tests override get_session and get_store."""

from typing import Annotated, Any

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from analekh.api import schemas
from analekh.config import get_settings
from analekh.db.models import Company
from analekh.db.session import get_session
from analekh.ingest.storage import ObjectStore, default_store
from analekh.universe.search import get as get_company


def get_store() -> ObjectStore:
    return default_store()


def get_user() -> str:
    """Single user until authentication lands (section 19.1 settings)."""
    return get_settings().default_user_id


DB = Annotated[Session, Depends(get_session)]
Store = Annotated[ObjectStore, Depends(get_store)]
User = Annotated[str, Depends(get_user)]


def company_or_404(db: Session, symbol: str) -> Company:
    c = get_company(db, symbol)
    if c is None:
        raise HTTPException(
            404,
            f"{symbol.upper()} is not in the NSE universe; run "
            "`analekh universe load` if the list has not been loaded",
        )
    return c


def job(task: Any, *args: Any) -> schemas.JobOut:
    result = task.delay(*args)
    return schemas.JobOut(job_id=result.id, status=result.status)
