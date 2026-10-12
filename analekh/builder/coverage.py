"""Coverage Builder (design doc 15): start coverage on a company with no model.

1. ``start_coverage``: gather history from the database, fill the template's inputs with sourced
   values (formulas untouched, each input commented, Sources sheet), propose first-pass
   assumptions, and park the draft for review.
2. The analyst accepts or edits each assumption (API).
3. ``finalize_build``: write accepted drivers, run Checks (must pass), write the hidden tag and
   the confirmed mapping, save version 1. The quarterly update flow takes over from here.
"""

import io
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from analekh.builder.assumptions import Proposal, propose
from analekh.builder.fill import FillReport, fill_history, write_drivers
from analekh.db.models import Assumption, Company, Model, ModelBuild, ModelVersion, Template
from analekh.facts import DbValueSource
from analekh.ingest.storage import ObjectStore, sha256
from analekh.workbook.checks import CheckRun, run_checks
from analekh.workbook.fingerprint import fingerprint
from analekh.workbook.locate import axis_for
from analekh.workbook.mapping import Mapping
from analekh.workbook.reader import load, read_structure
from analekh.workbook.tags import Tag, write_tag

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class NoHistoryError(RuntimeError):
    """No results filings for the company yet: backfill first (design doc 4.1)."""


class BuildNotReadyError(RuntimeError):
    pass


@dataclass
class StartResult:
    model: Model
    build: ModelBuild
    fill: FillReport
    proposals: list[Proposal]


@dataclass
class FinalizeResult:
    model: Model
    build: ModelBuild
    checks: CheckRun
    version: ModelVersion | None


def _draft_key(model: Model) -> str:
    return f"models/{model.id}/draft.xlsx"


def _save(wb: Any) -> bytes:
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def start_coverage(
    session: Session,
    store: ObjectStore,
    company: Company,
    template: Template,
    source: DbValueSource | None = None,
) -> StartResult:
    if template.mapping is None:
        raise BuildNotReadyError("template mapping not confirmed")
    mapping = Mapping.model_validate(template.mapping)
    source = source or DbValueSource(session, company.id)
    last_actual = source.latest_quarter(mapping.consolidated)
    if last_actual is None:
        raise NoHistoryError(f"no quarterly results stored for {company.nse_symbol}")

    wb = load(store.get(template.storage_key))
    report = fill_history(wb, mapping, source, last_actual)
    if "Cover" in wb.sheetnames:
        wb["Cover"]["B3"] = f"{company.name} ({company.nse_symbol})"
        wb["Cover"]["B4"] = datetime.now(UTC).date().isoformat()

    model = Model(
        company_id=company.id,
        template_id=template.id,
        origin="built",
        name=f"{company.nse_symbol} {template.name} v{template.version}",
        mapping=template.mapping,
    )
    session.add(model)
    session.flush()
    actual = [p.end for c, p in report.axis.columns.items() if not report.axis.is_estimate(c)]
    build = ModelBuild(
        model_id=model.id,
        template_id=template.id,
        history_from=min(actual),
        history_to=last_actual,
        status="awaiting_assumptions",
    )
    session.add(build)

    kinds = {k: v.get("kind", "ratio") for k, v in (template.driver_cells or {}).items()}
    proposals = propose(source, mapping, last_actual, kinds)
    for p in proposals:
        session.add(
            Assumption(
                model_id=model.id,
                driver=p.driver,
                period="forecast",
                proposed_value=p.value,
                rationale=p.rationale,
                citations={"facts": p.citations, "periods": p.basis},
            )
        )
    store.put(_draft_key(model), _save(wb), XLSX)
    model.structure = {"fill": report.as_dict()}
    session.flush()
    return StartResult(model, build, report, proposals)


def finalize_build(
    session: Session, store: ObjectStore, model: Model, created_by: str = "builder"
) -> FinalizeResult:
    build = session.scalar(
        select(ModelBuild).where(ModelBuild.model_id == model.id).order_by(ModelBuild.id.desc())
    )
    if build is None:
        raise BuildNotReadyError("no build for this model")
    assumptions = list(session.scalars(select(Assumption).where(Assumption.model_id == model.id)))
    if any(a.decision == "pending" for a in assumptions):
        raise BuildNotReadyError("decide every proposed assumption first")
    if model.mapping is None:
        raise BuildNotReadyError("model has no mapping")
    mapping = Mapping.model_validate(model.mapping)

    wb = load(store.get(_draft_key(model)))
    axis = axis_for(wb, mapping)
    accepted: dict[str, float] = {}
    for a in assumptions:
        if a.decision in ("accepted", "edited"):
            value = a.final_value if a.final_value is not None else a.proposed_value
            if value is not None:
                accepted[a.driver] = float(Decimal(value))
    write_drivers(wb, mapping, axis, accepted)

    company = session.get(Company, model.company_id)
    assert company is not None
    write_tag(wb, Tag(model.doc_tag, company.nse_symbol))
    wb.calculation.fullCalcOnLoad = True  # Excel recalculates on open; checks ran headless
    data = _save(wb)
    checks = run_checks(data, mapping)
    if not checks.passed:
        build.status = "failed"
        model.structure = (model.structure or {}) | {"checks": checks.as_dict()}
        return FinalizeResult(model, build, checks, None)

    key = f"models/{model.id}/v1-{sha256(data)[:12]}.xlsx"
    store.put(key, data, XLSX)
    version = ModelVersion(model_id=model.id, version=1, storage_key=key, created_by=created_by)
    session.add(version)
    model.fingerprint = fingerprint(wb)
    model.structure = read_structure(wb).to_dict() | {"checks": checks.as_dict()}
    model.last_seen = datetime.now(UTC)
    build.status = "built"
    session.flush()
    return FinalizeResult(model, build, checks, version)
