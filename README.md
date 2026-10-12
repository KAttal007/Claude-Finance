# Analekh

Pick any NSE-listed company. Analekh finds its results filings, extracts and validates the
numbers, builds a model from your own template (or updates the model you already keep),
writes to Excel only after you approve, and drafts the results flash, earnings note,
initiation, slides and comps with every number traced to its source.

Design: *Analekh Technical Design Document v1.0.1*. Section numbers in code comments refer to it.

Source control: GitLab is the source of truth; GitHub is a read-only mirror updated by CI
after a green pipeline on `main` (design doc 22.5).

## Status

This is a **skeleton of all phases**. Every engine has a working core and tests. Nothing has
been run against real NSE data yet, because the build sandbox could not reach NSE. Search for
`PHASE n` and `# verify` markers to see what each phase still needs.

| Phase (design doc 26) | In this skeleton | Still needed |
|---|---|---|
| 0 Spike | `scripts/phase0_spike.py`: universe lists, two feeds, XBRL parse + validate, element census, optional Kite price pull | Run from an Indian network; hand-check values; confirm element names, SME list path, pubDate format |
| 1 Data layer | Universe loader (renames, delistings), sector -> taxonomy, search (pg_trgm), watchlist and coverage levels, feeds, polite fetcher, linking, XBRL, V1-V10, backfill | Real fixtures; bank/NBFC/insurance element tables; sector map and Nifty 500 list; backfill run |
| 2 Builder and sync | Workbook understanding engine, template onboarding + test build, built-in NBFC and consumer templates, Coverage Builder (fill, propose assumptions, finalize with checks), discovery and tags, change sets, headless apply, Excel bridge CLI, review screens | Try on your real templates and models; balance sheet and cash flow in built-ins; xlwings on your machine |
| 3 Document AI | PDF read, page classifier, Claude KPI extraction with quote check, chunking, transcripts | API key, golden set, classifier tuning, embeddings choice, V10 wiring |
| 4 GenAI outputs | Tools (incl. model reader), calc, grounding check, report loop (flash, note, initiation), Q&A, Word/PowerPoint writers | Prompt tuning on 10 companies; reports as Celery jobs |
| 5 Discovery, IB, polish | Discovery and linking, comps, profile slide, pitch refresh, alerts, Office.js task pane, Streamlit admin | EBITDA/debt/cash elements, branded templates, demo |

## Quick start

```bash
cp .env.example .env            # fill in ANTHROPIC_API_KEY, USER_AGENT and storage keys
docker compose up -d            # postgres, redis, minio, api, worker, beat, web
docker compose exec api alembic upgrade head
docker compose exec api analekh universe load      # published NSE equity lists (Indian network)
docker compose exec api analekh watch MUTHOOTFIN   # deep coverage for one company
docker compose exec api analekh build MUTHOOTFIN --out muthoot.xlsx
```

Without NSE access, load the universe from a file downloaded by hand:
`analekh universe load --file EQUITY_L.csv`.

API docs: http://localhost:8000/docs. Web app: http://localhost:5173.

### Excel bridge (on the analyst's machine)

```bash
uv sync --group bridge
# .env: WATCH_FOLDERS=C:/Models;D:/Coverage  ANALEKH_API=http://<server>:8000
uv run python -m analekh.excel_bridge scan                   # find and identify models
uv run python -m analekh.excel_bridge link Muthoot.xlsx MUTHOOTFIN   # confirm a link
uv run python -m analekh.excel_bridge watch                  # keep models in step
uv run python -m analekh.excel_bridge apply 42 Muthoot.xlsx  # apply an approved change set
```

The bridge talks to the API at `ANALEKH_API`. It never runs macros and never overwrites the
original workbook; `SAVE_MODE=versioned` (the default) writes a new file per apply.

### Excel task pane (optional)

See `office-addin/README.md`.

## Development

```bash
uv sync                  # dev group installs by default
uv run pytest            # DB tests need PostgreSQL + pgvector (docker compose up -d postgres)
uv run ruff check . && uv run ruff format --check . && uv run mypy analekh
cd web && npm install && npm run dev
pre-commit install       # ruff, gitleaks, no exchange files or workbooks
```

Pinned dependencies: `uv.lock`, with `requirements*.txt` exported from it (design doc
Appendix G). Front-end types are generated from the API: `cd web && npm run api-types`.

## CI/CD (GitLab)

`.gitlab-ci.yml` runs lint, tests (PostgreSQL + Redis services), the web build, GitLab SAST,
secret detection, dependency and container scanning, and builds the image. Jobs that need
infrastructure run only once it is configured (CI/CD variables, all masked and protected):

| Job | Needs |
|---|---|
| `deploy_staging`, `dast` | `STAGING_URL`, a runner tagged `india` |
| `deploy_production` | `PRODUCTION_URL`, a release tag, manual approval |
| `mirror_to_github` | `GITHUB_MIRROR_TOKEN`, `GITHUB_MIRROR_USER`, `GITHUB_MIRROR_REPO` |

## Data rules (design doc 23)

- Only NSE's **published RSS feeds**, the **published equity list CSVs** and the files they
  link to, at the published TTL. Never NSE's internal JSON endpoints, never crawling.
  `analekh/ingest/http.py` enforces a host allow-list.
- Raw exchange files, user models and keys are never committed (`.gitignore` and the
  pre-commit hooks cover `data/`, `import/`, `out/`, `*.xlsx`, `.env`).
- Get written confirmation from NSE, or license a feed, before any public or commercial use.
- No buy/sell/hold ratings or target prices in anything shared.
