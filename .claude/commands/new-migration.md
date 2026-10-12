---
description: Create an Alembic migration after changing analekh/db/models.py
---
1. `uv run alembic revision --autogenerate -m "$ARGUMENTS"`
2. Read the generated file; add any `CREATE EXTENSION` or data backfill autogenerate misses.
3. `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
4. `uv run alembic check` must report no new operations.
