"""Operator command line (design doc 19.3, 22.4).

analekh universe load [--file EQUITY_L.csv]   analekh search QUERY
analekh watch SYMBOL | unwatch SYMBOL | watchlist
analekh refresh SYMBOL                        analekh backfill [SYMBOL]
analekh template add PATH --name N --sectors NBFC,Gold Finance [--from-model]
analekh template test TEMPLATE_ID SYMBOL      analekh template activate TEMPLATE_ID
analekh build SYMBOL [--template-id N] [--accept-all] [--out model.xlsx]
analekh sync MODEL_ID FILING_ID               analekh golden-test [--report golden.json]
"""

from pathlib import Path

import typer

app = typer.Typer(help="Analekh: the analyst's record, kept for you.", no_args_is_help=True)
universe_app = typer.Typer(help="Company universe (every NSE-listed company).")
template_app = typer.Typer(help="Model templates by sector.")
app.add_typer(universe_app, name="universe")
app.add_typer(template_app, name="template")


def _session():  # type: ignore[no-untyped-def]
    from analekh.db.session import session_scope

    return session_scope()


def _store():  # type: ignore[no-untyped-def]
    from analekh.ingest.storage import default_store

    return default_store()


def _company(s, symbol: str):  # type: ignore[no-untyped-def]
    from analekh.universe.search import get

    c = get(s, symbol)
    if c is None:
        raise typer.BadParameter(f"{symbol} is not in the universe; run `analekh universe load`")
    return c


@universe_app.command("load")
def universe_load(
    file: Path | None = typer.Option(None, help="EQUITY_L.csv downloaded by hand"),
    sme_file: Path | None = typer.Option(None, help="SME equity list CSV"),
) -> None:
    """Load or refresh the universe from files, or from NSE's published CSVs."""
    from analekh.universe.loader import parse_equity_list, refresh_from_nse, upsert_universe

    with _session() as s:
        if file:
            listed = parse_equity_list(file.read_bytes())
            if sme_file:
                listed += parse_equity_list(sme_file.read_bytes(), is_sme=True)
            summary = upsert_universe(s, listed)
        else:
            summary = refresh_from_nse(s)
    typer.echo(
        f"inserted {len(summary.inserted)}, updated {len(summary.updated)}, "
        f"renamed {len(summary.renamed)}, deactivated {len(summary.deactivated)}"
    )


@app.command()
def search(query: str, limit: int = 10) -> None:
    from analekh.universe.search import search as do_search

    with _session() as s:
        for h in do_search(s, query, limit):
            typer.echo(f"{h.nse_symbol:<14} {h.name}  {h.sector or ''}")


@app.command()
def watch(symbol: str) -> None:
    from analekh import coverage

    with _session() as s:
        coverage.add(s, _company(s, symbol))
    typer.echo(f"{symbol.upper()} added to the watchlist")


@app.command()
def unwatch(symbol: str) -> None:
    from analekh import coverage

    with _session() as s:
        coverage.remove(s, _company(s, symbol))
    typer.echo(f"{symbol.upper()} removed from the watchlist")


@app.command()
def watchlist() -> None:
    from analekh import coverage

    with _session() as s:
        for w in coverage.entries(s):
            typer.echo(f"{w.company.nse_symbol:<14} {w.company.name}")


@app.command()
def refresh(symbol: str) -> None:
    """Fetch, parse and validate the newest results filing (runs inline)."""
    from analekh.jobs.tasks import refresh_company

    typer.echo(refresh_company(symbol))


@app.command()
def backfill(symbol: str | None = typer.Argument(None)) -> None:
    """Ingest files from IMPORT_DIR/<SYMBOL>/ through the normal parser and validation path."""
    from analekh.jobs.tasks import backfill as do_backfill

    result = do_backfill(symbol)
    typer.echo(
        f"ingested {len(result['ingested'])}, skipped {len(result['skipped'])}, "
        f"unknown symbols {result['unknown_symbols']}"
    )


@template_app.command("add")
def template_add(
    path: Path,
    name: str = typer.Option(...),
    sectors: str = typer.Option(...),
    owner: str = "local",
    from_model: bool = False,
) -> None:
    from analekh.templates.onboarding import upload

    with _session() as s:
        t = upload(
            s,
            _store(),
            path.read_bytes(),
            name=name,
            owner=owner,
            sectors=[x.strip() for x in sectors.split(",")],
            from_existing_model=from_model,
        )
        low = [r for r in (t.mapping or {}).get("rows", []) if r.get("confidence", 1) < 0.8]
        typer.echo(
            f"template {t.id} v{t.version} ({t.status}); "
            f"{len((t.mapping or {}).get('rows', []))} rows mapped, {len(low)} to review"
        )


@template_app.command("test")
def template_test(template_id: int, symbol: str) -> None:
    from analekh.db.models import Template
    from analekh.templates.testbuild import run_test_build

    with _session() as s:
        t = s.get(Template, template_id)
        if t is None:
            raise typer.BadParameter("template not found")
        test = run_test_build(s, _store(), t, _company(s, symbol))
        typer.echo(f"{test.result}: {test.issues}")


@template_app.command("activate")
def template_activate(template_id: int, default: bool = False) -> None:
    from analekh.db.models import Template
    from analekh.templates.onboarding import activate

    with _session() as s:
        t = s.get(Template, template_id)
        if t is None:
            raise typer.BadParameter("template not found")
        activate(s, t, default)
        typer.echo(f"template {t.id} active")


@app.command()
def build(
    symbol: str, template_id: int | None = None, accept_all: bool = False, out: Path | None = None
) -> None:
    """Start coverage: build a model from a template with sourced history."""
    from sqlalchemy import select

    from analekh.builder.coverage import finalize_build, start_coverage
    from analekh.db.models import Assumption, ModelVersion, Template
    from analekh.templates.onboarding import default_for, ensure_builtin_templates

    store = _store()
    with _session() as s:
        company = _company(s, symbol)
        ensure_builtin_templates(s, store)
        template = (
            s.get(Template, template_id)
            if template_id
            else default_for(s, company.industry or company.sector) or default_for(s, None)
        )
        if template is None:
            raise typer.BadParameter("no active template")
        res = start_coverage(s, store, company, template)
        typer.echo(
            f"model {res.model.id}: {len(res.fill.written)} inputs filled; "
            f"rows not reported: {res.fill.blank_rows}"
        )
        for p in res.proposals:
            typer.echo(f"  {p.driver}: {p.value}  {p.rationale}")
        if not accept_all:
            typer.echo("Review assumptions in the web app, then POST /models/{id}/finalize.")
            return
        for a in s.scalars(select(Assumption).where(Assumption.model_id == res.model.id)):
            a.decision, a.final_value = "accepted", a.proposed_value
        done = finalize_build(s, store, res.model, created_by="cli")
        typer.echo(f"build {done.build.status}; checks passed: {done.checks.passed}")
        if out and done.version:
            mv = s.get(ModelVersion, done.version.id)
            assert mv is not None
            out.write_bytes(store.get(mv.storage_key))
            typer.echo(f"saved {out}")


@app.command()
def sync(model_id: int, filing_id: int) -> None:
    """Build a change set for a linked model from a filing (runs inline)."""
    from analekh.jobs.tasks import sync_model

    typer.echo(sync_model(model_id, filing_id))


@app.command("golden-test")
def golden_test(
    report: Path = typer.Option(Path("golden.json")),
    folder: Path = typer.Option(Path("tests/fixtures/golden")),
) -> None:
    """Exact-match accuracy on hand-checked filings (design doc 24)."""
    from analekh import golden

    result = golden.run(folder)
    golden.write(result, report)
    typer.echo(
        f"fixtures {result.fixtures}, checked {result.checked}, matched {result.matched}"
        f"{' - ' + result.note if result.note else ''}"
    )
    if result.checked and not result.passed:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
