# Claude-Finance

Finance projects built with Claude. The first one is **Ticker-to-Report**.

## Ticker-to-Report

Enter an NSE ticker. The system finds the newest results filing, extracts and validates the
numbers, proposes the exact changes to the analyst's Excel model, applies them after approval,
and drafts the results flash, earnings note, slides and comps.

Design: *Ticker-to-Report Technical Design Document v1.0* (section numbers in code comments
refer to it).

### Status

This is a **skeleton of all phases**: every engine exists with a working core and tests. Nothing has
been run against real NSE data yet, because the build sandbox could not reach NSE. Look for
`PHASE n` and `# verify` markers in the code for what each phase still needs.

| Phase | Area | In this skeleton | Still needed |
|---|---|---|---|
| 0 Spike | Data path | `scripts/phase0_spike.py` (feed, download, parse, validate, element census) | Run from an Indian network; hand-check values; confirm element names |
| 1 Data layer | Schema, feeds, fetcher, resolver, XBRL, V1-V10, backfill | Working and tested on synthetic XBRL + PostgreSQL | Real fixtures, bank/NBFC element tables, 30-company backfill |
| 2 Model sync | Mapping, period axis, dependency graph, roll-forward, change sets, approval API, headless apply | Working and tested on a fixture workbook | Test on your real models; xlwings bridge on your machine |
| 3 Document AI | PDF read, page classifier, Claude extraction, quote check, chunking, transcripts | Core logic tested offline | API key, golden set, tune classifier, embeddings choice, V10 wiring |
| 4 GenAI reports | Tools, calc, grounding check, tool loop, Word/PowerPoint writers | Loop + grounding tested with a fake model | Prompt tuning on 10 companies; Celery jobs for reports |
| 5 IB outputs | Comps, profile slide, pitch refresh, alerts, React UI | Core logic tested | EBITDA/debt/cash elements, branded templates, Office.js pane |

### Quick start

```bash
cp .env.example .env            # fill in keys
docker compose up -d            # postgres, redis, minio, api, worker, beat, web
docker compose exec api alembic upgrade head
python -m t2r.ingest.resolver path/to/EQUITY_L.csv   # NSE symbol master, downloaded by hand
curl -X POST localhost:8000/companies -H 'content-type: application/json' -d '{"symbol":"MUTHOOTFIN"}'
```

The API docs are at http://localhost:8000/docs and the web app at http://localhost:5173.

**Excel bridge** (on the analyst's machine, next to desktop Excel):

```bash
uv sync --extra excel
python -m t2r.excel_bridge      # listens on 127.0.0.1:8765
```

### Development

```bash
uv sync --group dev
uv run pytest            # DB tests need PostgreSQL+pgvector (docker compose up -d postgres)
uv run ruff check . && uv run ruff format --check . && uv run mypy t2r
cd web && npm install && npm run dev
```

### Data rules (design doc section 17)

- Only NSE's **published RSS feeds** and the files they link to, at the published 5-minute TTL.
  Never NSE's internal JSON endpoints, never crawling. `t2r/ingest/http.py` enforces a host
  allow-list.
- Raw exchange files and keys are never committed (`.gitignore` covers `data/`, `import/`,
  `out/`, `.env`).
- Get written confirmation from NSE, or license a feed, before any public or commercial use.
- No buy/sell/hold ratings or target prices in anything shared publicly.
