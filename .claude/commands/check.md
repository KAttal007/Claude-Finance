---
description: Run every check CI runs, and fix what fails
---
Run, in order, and fix any failure before moving on:

1. `uv run ruff check . && uv run ruff format --check . && uv run mypy analekh`
2. `uv run alembic upgrade head && uv run alembic check` (PostgreSQL must be up:
   `docker compose up -d postgres`)
3. `uv run pytest -q`
4. If `web/` changed: `cd web && npm run lint && npm test && npm run build`

Report what failed and what you changed. Never skip or weaken a test, and never relax the
grounding check, to make a check pass.
