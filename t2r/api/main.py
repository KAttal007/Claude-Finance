"""REST API (design doc 14). Long tasks return a job id; poll GET /jobs/{id}."""

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from t2r import __version__
from t2r.api import schemas
from t2r.db.models import (
    Alert,
    ChangeSet,
    Company,
    Fact,
    Filing,
    Kpi,
    Model,
    ModelVersion,
    PeerList,
    Report,
)
from t2r.db.session import get_session
from t2r.modelsync.mapping import load_mapping

app = FastAPI(title="Ticker-to-Report", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB = Annotated[Session, Depends(get_session)]


def _company(db: Session, symbol: str) -> Company:
    c = db.scalar(select(Company).where(Company.nse_symbol == symbol.upper()))
    if c is None:
        raise HTTPException(404, f"unknown symbol {symbol}; load the symbol master first")
    return c


def _job(task, *args) -> schemas.JobOut:
    result = task.delay(*args)
    return schemas.JobOut(job_id=result.id, status=result.status)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "version": __version__}


# --- companies, filings, facts ------------------------------------------------------------------


@app.post("/companies", response_model=schemas.CompanyOut)
def track_company(body: schemas.TrackCompany, db: DB) -> Company:
    from t2r.jobs.tasks import backfill

    c = _company(db, body.symbol)
    c.is_tracked = True
    db.flush()
    backfill.delay(c.nse_symbol)
    return c


@app.get("/companies/{symbol}", response_model=schemas.CompanyOut)
def get_company(symbol: str, db: DB) -> Company:
    return _company(db, symbol)


@app.post("/companies/{symbol}/refresh", response_model=schemas.JobOut)
def refresh(symbol: str, db: DB) -> schemas.JobOut:
    from t2r.jobs.tasks import refresh_company

    return _job(refresh_company, _company(db, symbol).nse_symbol)


@app.get("/companies/{symbol}/filings", response_model=list[schemas.FilingOut])
def filings(
    symbol: str, db: DB, kind: str | None = None, start: date | None = None, end: date | None = None
) -> list[Filing]:
    q = select(Filing).where(Filing.company_id == _company(db, symbol).id)
    if kind:
        q = q.where(Filing.kind == kind)
    if start:
        q = q.where(Filing.period_end >= start)
    if end:
        q = q.where(Filing.period_end <= end)
    return list(db.scalars(q.order_by(Filing.period_end.desc().nulls_last())))


@app.get("/companies/{symbol}/facts", response_model=list[schemas.FactOut])
def facts(
    symbol: str,
    db: DB,
    elements: str | None = None,
    start: date | None = None,
    end: date | None = None,
    consolidated: bool = True,
) -> list[Fact]:
    q = select(Fact).where(
        Fact.company_id == _company(db, symbol).id,
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


@app.get("/companies/{symbol}/kpis", response_model=list[schemas.KpiOut])
def kpis(symbol: str, db: DB, names: str | None = None) -> list[Kpi]:
    q = select(Kpi).where(Kpi.company_id == _company(db, symbol).id)
    if names:
        q = q.where(Kpi.name.in_(names.split(",")))
    return list(db.scalars(q.order_by(Kpi.period_end.desc())))


@app.get("/jobs/{job_id}", response_model=schemas.JobOut)
def job(job_id: str) -> schemas.JobOut:
    from t2r.jobs.app import app as celery

    res = celery.AsyncResult(job_id)
    return schemas.JobOut(
        job_id=job_id, status=res.status, result=res.result if res.ready() else None
    )


# --- models and change sets -----------------------------------------------------------------------


@app.post("/models")
def register_model(
    db: DB,
    name: Annotated[str, Form()],
    symbol: Annotated[str, Form()],
    workbook: Annotated[UploadFile, File()],
    mapping: Annotated[UploadFile, File()],
) -> dict:
    from t2r.ingest.storage import default_store, sha256

    mapping_text = mapping.file.read().decode()
    load_mapping(mapping_text)  # validate before storing
    data = workbook.file.read()
    m = Model(company_id=_company(db, symbol).id, name=name, mapping_yaml=mapping_text)
    db.add(m)
    db.flush()
    key = f"models/{m.id}/v1-{sha256(data)[:12]}.xlsx"
    default_store().put(key, data)
    db.add(ModelVersion(model_id=m.id, version=1, storage_key=key, created_by="upload"))
    return {"model_id": m.id, "version": 1}


@app.post("/models/{model_id}/sync", response_model=schemas.JobOut)
def sync(model_id: int, body: schemas.SyncRequest) -> schemas.JobOut:
    from t2r.jobs.tasks import sync_model

    return _job(sync_model, model_id, body.filing_id)


@app.get("/change-sets/{cs_id}", response_model=schemas.ChangeSetOut)
def change_set(cs_id: int, db: DB) -> ChangeSet:
    cs = db.get(ChangeSet, cs_id)
    if cs is None:
        raise HTTPException(404)
    return cs


@app.post("/change-sets/{cs_id}/decisions", response_model=schemas.ChangeSetOut)
def decide(cs_id: int, body: schemas.Decisions, db: DB) -> ChangeSet:
    cs = db.get(ChangeSet, cs_id)
    if cs is None:
        raise HTTPException(404)
    if cs.status not in ("proposed", "approved"):
        raise HTTPException(409, f"change set is {cs.status}")
    items = {i.id: i for i in cs.items}
    for kind in body.accept_kinds:
        for i in cs.items:
            if i.kind == kind and i.decision == "pending":
                i.decision, i.final_value = "accepted", i.new_value
    for d in body.decisions:
        item = items.get(d.item_id)
        if item is None:
            raise HTTPException(422, f"item {d.item_id} not in change set")
        if d.decision == "edited" and d.final_value is None:
            raise HTTPException(422, "edited decisions need final_value")
        item.decision = d.decision
        item.final_value = (
            d.final_value
            if d.decision == "edited"
            else (item.new_value if d.decision == "accepted" else None)
        )
    if all(i.decision != "pending" for i in cs.items):
        cs.status, cs.decided_at = "approved", datetime.now(UTC)
    return cs


@app.post("/change-sets/{cs_id}/apply")
def apply(cs_id: int, db: DB) -> dict:
    """Headless apply into a new model version. The xlwings bridge offers the same on the
    analyst's machine (native recalculation)."""
    from t2r.ingest.storage import default_store, sha256
    from t2r.modelsync.apply import ApprovedItem, apply_headless, recalc_with_libreoffice

    cs = db.get(ChangeSet, cs_id)
    if cs is None:
        raise HTTPException(404)
    if cs.status != "approved":
        raise HTTPException(409, "decide every item first")
    base = db.scalar(
        select(ModelVersion).where(
            ModelVersion.model_id == cs.model_id, ModelVersion.version == cs.base_version
        )
    )
    if base is None:
        raise HTTPException(404, "base version missing")
    store = default_store()
    approved = [
        ApprovedItem(
            i.kind,
            i.sheet or "",
            i.cell or "",
            i.final_value,
            i.formula_after if i.decision == "accepted" else None,
        )
        for i in cs.items
        if i.decision in ("accepted", "edited")
    ]
    out = recalc_with_libreoffice(apply_headless(store.get(base.storage_key), approved))
    latest = (
        db.scalar(
            select(ModelVersion.version)
            .where(ModelVersion.model_id == cs.model_id)
            .order_by(ModelVersion.version.desc())
        )
        or 0
    )
    key = f"models/{cs.model_id}/v{latest + 1}-{sha256(out)[:12]}.xlsx"
    store.put(key, out)
    db.add(
        ModelVersion(
            model_id=cs.model_id,
            version=latest + 1,
            parent_version=cs.base_version,
            storage_key=key,
            created_by="api",
        )
    )
    cs.status = "applied"
    return {"model_id": cs.model_id, "version": latest + 1, "written": len(approved)}


@app.get("/models/{model_id}/versions/{version}")
def download_version(model_id: int, version: int, db: DB) -> Response:
    from t2r.ingest.storage import default_store

    mv = db.scalar(
        select(ModelVersion).where(
            ModelVersion.model_id == model_id, ModelVersion.version == version
        )
    )
    if mv is None:
        raise HTTPException(404)
    return Response(
        default_store().get(mv.storage_key),
        media_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    )


# --- reports, Q&A, comps, alerts ------------------------------------------------------------------


@app.post("/reports")
def create_report(body: schemas.ReportRequest, db: DB) -> dict:
    """PHASE 4: move to a Celery job; runs inline for now."""
    from t2r.genai.client import Claude
    from t2r.genai.reports import run_report
    from t2r.genai.tools import ToolExecutor

    c = _company(db, body.symbol)
    run = run_report(
        Claude(db),
        ToolExecutor(db),
        body.kind,
        company=c.nse_symbol,
        period_end=body.period_end.isoformat(),
        model_id=body.model_id,
    )
    report = Report(
        company_id=c.id,
        kind=body.kind,
        model_used=Claude(db).model,
        citations={"tool_calls": run.tool_calls, "grounding": run.grounding.__dict__},
    )
    db.add(report)
    db.flush()
    return {
        "report_id": report.id,
        "blocked": run.blocked,
        "unmatched_numbers": run.grounding.unmatched,
        "text": run.text,
    }


@app.get("/reports/{report_id}")
def get_report(report_id: int, db: DB) -> dict:
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404)
    return {
        "id": r.id,
        "kind": r.kind,
        "storage_key": r.storage_key,
        "citations": r.citations,
        "created_at": r.created_at,
    }


@app.post("/qa")
def qa(body: schemas.QaRequest, db: DB) -> dict:
    from t2r.genai.client import Claude
    from t2r.genai.reports import run_report
    from t2r.genai.tools import ToolExecutor

    c = _company(db, body.symbol)
    run = run_report(
        Claude(db), ToolExecutor(db), "qa", company=c.nse_symbol, question=body.question
    )
    return {
        "answer": run.text,
        "blocked": run.blocked,
        "unmatched_numbers": run.grounding.unmatched,
    }


@app.post("/comps")
def comps(body: schemas.CompsRequest, db: DB) -> Response:
    from t2r.ib.comps import compute, gather, to_xlsx

    symbols = body.symbols
    if body.peer_list:
        pl = db.scalar(select(PeerList).where(PeerList.name == body.peer_list))
        if pl is None:
            raise HTTPException(404, "peer list not found")
        symbols = pl.symbols
    rows = [compute(gather(db, s.upper())) for s in symbols]
    return Response(
        to_xlsx(rows),
        media_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    )


@app.get("/alerts")
def alerts(db: DB, limit: int = 50) -> list[dict]:
    rows = db.scalars(select(Alert).order_by(Alert.id.desc()).limit(limit))
    return [
        {
            "id": a.id,
            "kind": a.kind,
            "payload": a.payload,
            "channel": a.channel,
            "sent_at": a.sent_at,
        }
        for a in rows
    ]
