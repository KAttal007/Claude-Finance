"""REST API (design doc 20). Long tasks return a job id; poll GET /jobs/{id}. Swagger at /docs."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from analekh import __version__
from analekh.api.routers import change_sets, companies, models, outputs, templates

app = FastAPI(
    title="Analekh", version=__version__, description="The analyst's record, kept for you."
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    companies.router,
    templates.router,
    models.router,
    change_sets.router,
    outputs.router,
):
    app.include_router(router)


@app.get("/health", tags=["ops"])
def health() -> dict:
    return {"ok": True, "version": __version__}
