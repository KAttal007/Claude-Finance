"""Document pipeline orchestration (design doc 9.1): read -> classify -> select -> extract ->
chunk/embed -> validate against XBRL (V10)."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from analekh.db.models import Company, Document, Filing
from analekh.docs.chunking import chunk_pages
from analekh.docs.classifier import select_pages
from analekh.docs.embeddings import Embedder, store_chunks
from analekh.docs.extract import extract, save_kpis
from analekh.docs.pdf import read_pages
from analekh.docs.sector_kpis import kpis_for
from analekh.genai.client import Claude
from analekh.ingest.storage import ObjectStore


@dataclass
class DocResult:
    pages: int
    selected: list[int]
    kpis: int
    chunks: int


def process_document(
    session: Session,
    store: ObjectStore,
    filing: Filing,
    claude: Claude | None,
    embedder: Embedder | None,
) -> DocResult:
    data = store.get(filing.storage_key)
    pages = read_pages(data)
    company = session.get(Company, filing.company_id)
    assert company is not None

    doc = Document(filing_id=filing.id, page_count=len(pages))
    session.add(doc)
    session.flush()

    selected = select_pages(pages, filing.kind)
    kpi_count = 0
    wanted = kpis_for(
        company.results_taxonomy if company.results_taxonomy != "indas" else company.sector
    )
    if claude is not None and selected and filing.kind != "transcript":
        extraction = extract(claude, data, pages, selected, company.name, wanted)
        kpi_count = save_kpis(session, filing, extraction)
        # PHASE 3: run V10 here - map KPI names to XBRL logical names where they overlap and
        # compare with stored facts; XBRL wins and the KPI is flagged.

    chunks = store_chunks(session, doc, chunk_pages(pages), embedder)
    filing.status = "parsed"
    return DocResult(len(pages), [s.page for s in selected], kpi_count, chunks)
