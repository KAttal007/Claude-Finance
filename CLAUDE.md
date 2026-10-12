# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this is

Ticker-to-Report (`t2r/`): NSE ticker in; validated XBRL facts, an analyst-approved Excel model
update and grounded research drafts out. Section numbers in comments (e.g. "design doc 8.2")
refer to *Ticker-to-Report Technical Design Document v1.0*.

## Commands

```bash
uv sync --group dev                       # install
uv run pytest -q                          # all tests; DB tests skip if PostgreSQL is down
uv run ruff check . && uv run ruff format . && uv run mypy t2r
docker compose up -d postgres             # PostgreSQL 16 + pgvector for DB tests
uv run alembic upgrade head               # migrations (t2r/db/migrations)
uv run alembic revision --autogenerate -m "..."   # after changing t2r/db/models.py
uv run python scripts/phase0_spike.py --limit 10  # needs NSE access (Indian network)
cd web && npm run dev                     # front end, proxies /api to :8000
```

Run ruff, mypy and pytest before every commit; CI runs the same plus `alembic check`.

## Layout (request flow order)

- `ingest/` feeds (RSS watcher), http (polite client + host allow-list), storage (hash-keyed
  MinIO/local), resolver (symbol master, name matching), pipeline (hash -> parse -> validate ->
  facts, restatements), backfill (import folder).
- `xbrl/` lxml instance parser, element vocabulary per taxonomy.
- `validate/rules.py` V1-V10.
- `docs/` PDF read, page classifier, Claude KPI extraction, chunking, embeddings, transcripts.
- `modelsync/` YAML mapping, workbook period axis, formula dependency graph, change-set builder,
  headless apply. `excel_bridge/` = xlwings service for the analyst's machine.
- `genai/` Claude client (token logging, refusal fallbacks), tools, calc, grounding check,
  report loop, Q&A search, Word/PowerPoint writers.
- `ib/` comps, profile slide, pitch placeholder refresh. `alerts/`, `market/kite.py`.
- `api/main.py` REST endpoints (design doc 14). `jobs/` Celery app, beat schedule, tasks.

## Rules that must not be broken

1. **NSE access**: only the published RSS feeds and files they link to. Never add NSE website or
   internal API hosts to `ALLOWED_HOSTS` in `t2r/ingest/http.py`; never crawl pages.
2. **Human in the loop**: nothing writes to an analyst's model without an approved change set.
   The original workbook is never overwritten; every apply saves a new `model_versions` row.
3. **Grounded GenAI**: generated text may only contain numbers from tool results or `calc`.
   `genai/grounding.py` blocks anything else. Do not weaken it to make output pass.
4. **Money is Decimal / NUMERIC**, never float, except at the Excel boundary.
5. **XBRL wins** over AI-extracted values (V10). Contexts are resolved by dates, never by id.
6. **No raw exchange files, keys or downloaded filings in git.**
7. No ratings or target prices in outputs.

## Where the skeleton stops

Search for `PHASE 0` .. `PHASE 5` and `# verify`:

- `xbrl/elements.py`: names marked `# verify` were never checked against a real file; bank,
  NBFC and insurance tables are empty. Fill from `scripts/phase0_spike.py` output (elements.csv).
- `ingest/feeds.py`: NSE pubDate format unconfirmed.
- `validate/rules.py` V2: exceptional-items sign convention unconfirmed.
- Test fixtures in `tests/xbrl_factory.py` are SYNTHETIC. Put real files (not committed if
  licensing is unclear) under `tests/fixtures/real/` and add golden-set tests marked `golden`.
- `docs/pipeline.py`: V10 not wired; embeddings provider undecided (open question 22.5).
- `ib/comps.py`: EBITDA, debt, cash, book value not yet sourced.
- Reports run inline in the API; move to Celery jobs and store files in MinIO.

## Claude API usage

All calls go through `t2r/genai/client.py` (`Claude.create`), which sets the model from
`CLAUDE_MODEL`, enables server-side refusal fallbacks (`fallbacks="default"`, beta
`server-side-fallback-2026-07-01`), and logs tokens to `llm_calls`. Structured output uses
`output_config.format` JSON schemas with `additionalProperties: false`. Backfill extraction uses
the Batch API (`docs/extract.py: batch_params`, no fallbacks on batches).
