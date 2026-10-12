"""Change-set review and apply (design doc 16.4, 20): nothing is written before every item has a
decision, and apply always saves a new model version."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from analekh.api import schemas
from analekh.api.deps import DB, Store
from analekh.db.models import ChangeSet, Model, ModelVersion
from analekh.ingest.storage import sha256
from analekh.modelsync.apply import ApprovedItem, apply_headless
from analekh.workbook.fingerprint import fingerprint
from analekh.workbook.reader import load
from analekh.workbook.recalc import recalc_file

router = APIRouter(tags=["change-sets"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _cs(db: DB, cs_id: int) -> ChangeSet:
    cs = db.get(ChangeSet, cs_id)
    if cs is None:
        raise HTTPException(404)
    return cs


@router.get("/change-sets/{cs_id}", response_model=schemas.ChangeSetOut)
def change_set(cs_id: int, db: DB) -> ChangeSet:
    return _cs(db, cs_id)


@router.post("/change-sets/{cs_id}/decisions", response_model=schemas.ChangeSetOut)
def decide(cs_id: int, body: schemas.Decisions, db: DB) -> ChangeSet:
    cs = _cs(db, cs_id)
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


@router.post("/change-sets/{cs_id}/apply")
def apply(cs_id: int, db: DB, store: Store) -> dict:
    """Headless apply into a new model version (LibreOffice recalculation when installed).
    The Excel bridge offers the same on the analyst's machine with native recalculation."""
    cs = _cs(db, cs_id)
    if cs.status != "approved":
        raise HTTPException(409, "decide every item first")
    base = db.scalar(
        select(ModelVersion).where(
            ModelVersion.model_id == cs.model_id, ModelVersion.version == cs.base_version
        )
    )
    if base is None:
        raise HTTPException(404, "base version missing")
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
    written = apply_headless(store.get(base.storage_key), approved)
    out = recalc_file(written)
    latest = (
        db.scalar(
            select(ModelVersion.version)
            .where(ModelVersion.model_id == cs.model_id)
            .order_by(ModelVersion.version.desc())
        )
        or 0
    )
    key = f"models/{cs.model_id}/v{latest + 1}-{sha256(out)[:12]}.xlsx"
    store.put(key, out, XLSX)
    db.add(
        ModelVersion(
            model_id=cs.model_id,
            version=latest + 1,
            parent_version=cs.base_version,
            storage_key=key,
            created_by="api",
        )
    )
    model = db.get(Model, cs.model_id)
    if model is not None:
        model.fingerprint = fingerprint(load(written))
        model.last_seen = datetime.now(UTC)
    cs.status = "applied"
    return {"model_id": cs.model_id, "version": latest + 1, "written": len(approved)}
