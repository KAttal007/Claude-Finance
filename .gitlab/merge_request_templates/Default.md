## What and why

<!-- One or two sentences. Link the issue or design-doc section (e.g. "design doc 16.2"). -->

## Changes

-

## Checks

- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy analekh`
- [ ] `uv run pytest` (DB tests need PostgreSQL + pgvector)
- [ ] `cd web && npm run lint && npm test && npm run build` (if the web app changed)
- [ ] `uv run alembic check` (if `analekh/db/models.py` changed: a migration is included)

## Rules (CLAUDE.md)

- [ ] NSE access stays on published RSS feeds and linked files only
- [ ] Nothing writes to a model without an approved change set or approved assumptions
- [ ] No unsourced numbers in generated text; the grounding check is not weakened
- [ ] No raw exchange files, user models or keys committed
- [ ] No ratings or target prices in outputs

/label ~"needs review"
