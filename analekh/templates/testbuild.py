"""Template test build (design doc 14.3): fill the template with one real company's history,
recalculate, and report checks passing or failing, template rows the company does not report,
reported items with no template row, and broken formulas. Only a passing test activates."""

import io

from sqlalchemy.orm import Session

from analekh.builder.fill import fill_history
from analekh.db.models import Company, Template, TemplateTest
from analekh.facts import DbValueSource
from analekh.ingest.storage import ObjectStore
from analekh.workbook.checks import run_checks
from analekh.workbook.hygiene import scan_hygiene
from analekh.workbook.mapping import Mapping
from analekh.workbook.reader import load


def run_test_build(
    session: Session,
    store: ObjectStore,
    template: Template,
    company: Company,
    source: DbValueSource | None = None,
) -> TemplateTest:
    if template.mapping is None:
        raise ValueError("confirm the template mapping before a test build")
    mapping = Mapping.model_validate(template.mapping)
    source = source or DbValueSource(session, company.id)
    last_actual = source.latest_quarter(mapping.consolidated)
    issues: dict[str, object] = {}
    if last_actual is None:
        issues["error"] = f"no quarterly results stored for {company.nse_symbol}"
        test = TemplateTest(
            template_id=template.id, company_id=company.id, result="fail", issues=issues
        )
        session.add(test)
        session.flush()
        return test

    wb = load(store.get(template.storage_key))
    fill = fill_history(wb, mapping, source, last_actual)
    out = io.BytesIO()
    wb.save(out)
    checks = run_checks(out.getvalue(), mapping, wb)

    mapped = {t.key for r in mapping.rows for t in r.terms() if t.kind == "xbrl"}
    unmapped = sorted(source.elements(last_actual, mapping.consolidated) - mapped)
    broken = [
        f"{h.sheet}!{h.cell}: {h.detail}" for h in scan_hygiene(wb) if h.kind == "error_value"
    ]
    issues = {
        "period": fill.axis.columns[
            max(c for c in fill.axis.columns if not fill.axis.is_estimate(c))
        ].label,
        "checks": checks.as_dict(),
        "template_rows_not_reported": fill.blank_rows,
        "partially_reported_rows": fill.partial_rows,
        "mapped_rows_not_found": fill.missing_rows,
        "reported_items_without_row": unmapped,
        "broken_formulas": broken + list(checks.broken_formulas),
        "written": len(fill.written),
    }
    passed = checks.passed and not fill.missing_rows and not broken and bool(fill.written)
    test = TemplateTest(
        template_id=template.id,
        company_id=company.id,
        result="pass" if passed else "fail",
        issues=issues,
    )
    session.add(test)
    if passed and template.status == "draft":
        template.status = "tested"
    session.flush()
    return test
