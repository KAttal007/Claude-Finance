"""Reports, initiation drafts, Q&A, comps and alerts (design doc 17, 18, 20)."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from sqlalchemy import select

from analekh.api import schemas
from analekh.api.deps import DB, Store, company_or_404
from analekh.db.models import Alert, Model, PeerList, Report

router = APIRouter(tags=["outputs"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.post("/reports")
def create_report(body: schemas.ReportRequest, db: DB, store: Store) -> dict:
    """Flash, note, slides, digest or initiation. Ungrounded output is returned blocked.
    PHASE 4: move to a Celery job; runs inline for now."""
    from analekh.genai.client import Claude
    from analekh.genai.reports import run_report
    from analekh.genai.tools import ModelReader, ToolExecutor

    c = company_or_404(db, body.symbol)
    if body.kind == "initiation" and body.model_id is None:
        raise HTTPException(422, "an initiation draft needs the built model (model_id)")
    if body.model_id is not None:
        model = db.get(Model, body.model_id)
        if model is None or model.company_id != c.id:
            raise HTTPException(404, "model not found for this company")
    claude = Claude(db)
    run = run_report(
        claude,
        ToolExecutor(db, ModelReader(db, store)),
        body.kind,
        company=c.nse_symbol,
        period_end=body.period_end.isoformat(),
        model_id=body.model_id,
    )
    report = Report(
        company_id=c.id,
        model_id=body.model_id,
        kind=body.kind,
        model_used=claude.model,
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


@router.get("/reports/{report_id}")
def get_report(report_id: int, db: DB) -> dict:
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404)
    return {
        "id": r.id,
        "kind": r.kind,
        "model_id": r.model_id,
        "storage_key": r.storage_key,
        "citations": r.citations,
        "created_at": r.created_at,
    }


@router.post("/qa")
def qa(body: schemas.QaRequest, db: DB) -> dict:
    from analekh.genai.client import Claude
    from analekh.genai.reports import run_report
    from analekh.genai.tools import ToolExecutor

    c = company_or_404(db, body.symbol)
    run = run_report(
        Claude(db), ToolExecutor(db), "qa", company=c.nse_symbol, question=body.question
    )
    return {
        "answer": run.text,
        "blocked": run.blocked,
        "unmatched_numbers": run.grounding.unmatched,
    }


@router.post("/comps")
def comps(body: schemas.CompsRequest, db: DB) -> Response:
    from analekh.ib.comps import compute, gather, to_xlsx

    symbols = body.symbols
    if body.peer_list:
        pl = db.scalar(select(PeerList).where(PeerList.name == body.peer_list))
        if pl is None:
            raise HTTPException(404, "peer list not found")
        symbols = pl.symbols
    rows = [compute(gather(db, company_or_404(db, s).nse_symbol)) for s in symbols]
    return Response(to_xlsx(rows), media_type=XLSX)


@router.get("/alerts")
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
