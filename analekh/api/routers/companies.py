"""Universe, company pages, watchlist and on-demand coverage (design doc 4, 19.1, 20)."""

from datetime import date

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from analekh import coverage
from analekh.api import schemas
from analekh.api.deps import DB, User, company_or_404, job
from analekh.db.models import ChangeSet, Fact, Filing, Kpi, Model
from analekh.universe.search import search

router = APIRouter(tags=["companies"])


@router.get("/companies/search", response_model=list[schemas.SearchHitOut])
def search_companies(db: DB, q: str, limit: int = 10) -> list[schemas.SearchHitOut]:
    return [schemas.SearchHitOut(**h.__dict__) for h in search(db, q, min(limit, 50))]


@router.get("/companies/{symbol}", response_model=schemas.CompanyDetail)
def get_company(symbol: str, db: DB) -> schemas.CompanyDetail:
    c = company_or_404(db, symbol)
    return schemas.CompanyDetail.model_validate(
        {
            **schemas.CompanyOut.model_validate(c).model_dump(),
            "coverage_level": coverage.level(db, c),
            "watched": coverage.is_watched(db, c.id),
        }
    )


@router.post("/watchlist", response_model=schemas.CompanyDetail)
def watch(body: schemas.WatchRequest, db: DB, user: User) -> schemas.CompanyDetail:
    c = company_or_404(db, body.symbol)
    coverage.add(db, c, user, body.settings)
    db.flush()
    return get_company(c.nse_symbol, db)


@router.delete("/watchlist/{symbol}", status_code=204)
def unwatch(symbol: str, db: DB, user: User) -> None:
    coverage.remove(db, company_or_404(db, symbol), user)


@router.get("/watchlist", response_model=list[schemas.WatchlistEntryOut])
def watchlist(db: DB, user: User) -> list[schemas.WatchlistEntryOut]:
    out = []
    for w in coverage.entries(db, user):
        last = db.scalar(
            select(Filing)
            .where(Filing.company_id == w.company_id, Filing.kind == "results_xbrl")
            .order_by(Filing.period_end.desc().nulls_last())
        )
        pending = (
            db.scalar(
                select(func.count(ChangeSet.id))
                .join(Model)
                .where(Model.company_id == w.company_id, ChangeSet.status == "proposed")
            )
            or 0
        )
        out.append(
            schemas.WatchlistEntryOut(
                symbol=w.company.nse_symbol,
                name=w.company.name,
                added_at=w.added_at,
                settings=w.settings,
                last_filing=last.period_end if last else None,
                validation_blocked=bool(last and last.meta.get("blocks_auto_apply")),
                pending_change_sets=pending,
            )
        )
    return out


@router.post("/companies/{symbol}/refresh", response_model=schemas.JobOut)
def refresh(symbol: str, db: DB) -> schemas.JobOut:
    from analekh.jobs.tasks import refresh_company

    return job(refresh_company, company_or_404(db, symbol).nse_symbol)


@router.post("/companies/{symbol}/analyse", response_model=schemas.JobOut)
def analyse(symbol: str, db: DB) -> schemas.JobOut:
    """On-demand deep coverage for any company: backfill history and run the document pipeline."""
    from analekh.jobs.tasks import analyse_company

    return job(analyse_company, company_or_404(db, symbol).nse_symbol)


@router.get("/companies/{symbol}/filings", response_model=list[schemas.FilingOut])
def filings(
    symbol: str, db: DB, kind: str | None = None, start: date | None = None, end: date | None = None
) -> list[Filing]:
    q = select(Filing).where(Filing.company_id == company_or_404(db, symbol).id)
    if kind:
        q = q.where(Filing.kind == kind)
    if start:
        q = q.where(Filing.period_end >= start)
    if end:
        q = q.where(Filing.period_end <= end)
    return list(db.scalars(q.order_by(Filing.period_end.desc().nulls_last(), Filing.id.desc())))


@router.get("/companies/{symbol}/facts", response_model=list[schemas.FactOut])
def facts(
    symbol: str,
    db: DB,
    elements: str | None = None,
    start: date | None = None,
    end: date | None = None,
    consolidated: bool = True,
) -> list[Fact]:
    q = select(Fact).where(
        Fact.company_id == company_or_404(db, symbol).id,
        Fact.is_latest,
        Fact.consolidated == consolidated,
    )
    if elements:
        q = q.where(Fact.element.in_(elements.split(",")))
    if start:
        q = q.where(Fact.period_end >= start)
    if end:
        q = q.where(Fact.period_end <= end)
    return list(db.scalars(q.order_by(Fact.period_end.desc(), Fact.element)))


@router.get("/companies/{symbol}/kpis", response_model=list[schemas.KpiOut])
def kpis(symbol: str, db: DB, names: str | None = None) -> list[Kpi]:
    q = select(Kpi).where(Kpi.company_id == company_or_404(db, symbol).id)
    if names:
        q = q.where(Kpi.name.in_(names.split(",")))
    return list(db.scalars(q.order_by(Kpi.period_end.desc())))


@router.get("/jobs/{job_id}", response_model=schemas.JobOut)
def job_status(job_id: str) -> schemas.JobOut:
    from analekh.jobs.app import app as celery

    res = celery.AsyncResult(job_id)
    if res is None:
        raise HTTPException(404)
    return schemas.JobOut(
        job_id=job_id, status=res.status, result=res.result if res.ready() else None
    )
