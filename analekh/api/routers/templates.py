"""Template onboarding endpoints (design doc 14, 20)."""

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sqlalchemy import select

from analekh.api import schemas
from analekh.api.deps import DB, Store, User, company_or_404
from analekh.config import get_settings
from analekh.db.models import Template
from analekh.templates.onboarding import (
    TemplateError,
    activate,
    confirm_mapping,
    ensure_builtin_templates,
    upload,
)
from analekh.templates.testbuild import run_test_build

router = APIRouter(tags=["templates"])


def _template(db: DB, template_id: int) -> Template:
    t = db.get(Template, template_id)
    if t is None:
        raise HTTPException(404, "template not found")
    return t


@router.get("/templates", response_model=list[schemas.TemplateOut])
def list_templates(db: DB, store: Store, sector: str | None = None) -> list[Template]:
    ensure_builtin_templates(db, store)
    rows = list(db.scalars(select(Template).order_by(Template.name, Template.version.desc())))
    return [t for t in rows if sector is None or sector in t.sectors]


@router.post("/templates", response_model=schemas.TemplateOut)
def upload_template(
    db: DB,
    store: Store,
    user: User,
    workbook: Annotated[UploadFile, File()],
    name: Annotated[str, Form()],
    sectors: Annotated[str, Form(description="comma separated")],
    from_existing_model: Annotated[bool, Form()] = False,
) -> Template:
    data = workbook.file.read()
    if not data.startswith(b"PK"):
        raise HTTPException(422, "upload an .xlsx or .xlsm workbook")
    ai = None
    if get_settings().anthropic_api_key:
        from analekh.genai.client import Claude
        from analekh.genai.labels import label_resolver

        ai = label_resolver(Claude(db))
    try:
        return upload(
            db,
            store,
            data,
            name=name,
            owner=user,
            sectors=[s.strip() for s in sectors.split(",") if s.strip()],
            from_existing_model=from_existing_model,
            ai=ai,
        )
    except TemplateError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/templates/{template_id}/mapping", response_model=schemas.TemplateOut)
def confirm(template_id: int, mapping: dict[str, Any], db: DB) -> Template:
    t = _template(db, template_id)
    try:
        confirm_mapping(db, t, mapping)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return t


@router.post("/templates/{template_id}/test", response_model=schemas.TemplateTestOut)
def test_build(template_id: int, body: schemas.TemplateTestRequest, db: DB, store: Store):
    t = _template(db, template_id)
    return run_test_build(db, store, t, company_or_404(db, body.symbol))


@router.post("/templates/{template_id}/activate", response_model=schemas.TemplateOut)
def activate_template(template_id: int, db: DB, make_default: bool = False) -> Template:
    t = _template(db, template_id)
    try:
        return activate(db, t, make_default)
    except TemplateError as exc:
        raise HTTPException(409, str(exc)) from exc
