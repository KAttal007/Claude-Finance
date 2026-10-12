"""Model discovery and recognition, server side (design doc 13.2).

The Excel bridge sends hints from each workbook it finds; this matches them against the
universe in order of strength: hidden tag, then file name, then contents. The user confirms
every new link once; after that the hidden tag makes recognition exact.
"""

import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import PurePath

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.orm import Session

from analekh.db.models import Company, Model
from analekh.ingest.linking import normalise_name

ISIN = re.compile(r"\bINE[0-9A-Z]{9}\b")
GENERIC = {
    "MODEL",
    "MODELS",
    "FINAL",
    "DRAFT",
    "COPY",
    "UPDATED",
    "NEW",
    "OLD",
    "V1",
    "V2",
    "V3",
    "QUARTERLY",
    "ANNUAL",
    "RESULTS",
    "XLSX",
    "XLSM",
    "INITIATION",
    "IC",
    "SHEET",
}


@dataclass
class WorkbookHints:
    path: str
    tag_model_id: str | None = None
    tag_symbol: str | None = None
    text: list[str] = field(default_factory=list)  # header and cover cells, first sheets only
    modified: float | None = None
    fingerprint: str | None = None


@dataclass
class Candidate:
    path: str
    symbol: str | None
    company_name: str | None
    method: str  # tag, file_name, contents, none
    confidence: float
    model_id: int | None = None  # already linked model, when the tag matches
    reason: str = ""

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class Matcher:
    def __init__(self, companies: list[Company]) -> None:
        self.by_symbol = {c.nse_symbol: c for c in companies}
        self.by_isin = {c.isin: c for c in companies if c.isin}
        self.by_norm = {normalise_name(c.name): c for c in companies}

    def identify(self, hints: WorkbookHints, linked: dict[str, Model] | None = None) -> Candidate:
        linked = linked or {}
        if hints.tag_model_id and hints.tag_model_id in linked:
            m = linked[hints.tag_model_id]
            return Candidate(
                hints.path,
                hints.tag_symbol,
                None,
                "tag",
                1.0,
                m.id,
                "hidden tag matches a linked model",
            )
        if hints.tag_symbol and hints.tag_symbol in self.by_symbol:
            c = self.by_symbol[hints.tag_symbol]
            return Candidate(
                hints.path,
                c.nse_symbol,
                c.name,
                "tag",
                0.97,
                reason="hidden tag names this company",
            )

        stem = PurePath(hints.path).stem.upper()
        tokens = [
            t
            for t in re.split(r"[^A-Z0-9&]+", stem)
            if t and t not in GENERIC and not re.fullmatch(r"(FY|Q\d|H\d)?\d{2,4}[AE]?", t)
        ]
        for t in tokens:
            if t in self.by_symbol:
                c = self.by_symbol[t]
                return Candidate(
                    hints.path,
                    c.nse_symbol,
                    c.name,
                    "file_name",
                    0.9,
                    reason=f"file name token {t} is an NSE symbol",
                )
        if tokens and self.by_norm:
            name = normalise_name(" ".join(tokens))
            best = process.extractOne(name, list(self.by_norm), scorer=fuzz.token_set_ratio)
            if best and best[1] >= 90:
                c = self.by_norm[best[0]]
                return Candidate(
                    hints.path,
                    c.nse_symbol,
                    c.name,
                    "file_name",
                    round(0.6 + (best[1] - 90) / 40, 2),
                    reason=f"file name resembles {c.name}",
                )

        text = " ".join(hints.text)
        for isin in ISIN.findall(text.upper()):
            if isin in self.by_isin:
                c = self.by_isin[isin]
                return Candidate(
                    hints.path,
                    c.nse_symbol,
                    c.name,
                    "contents",
                    0.95,
                    reason=f"ISIN {isin} in the workbook",
                )
        for cell in hints.text:
            norm = normalise_name(cell)
            if norm in self.by_norm:
                c = self.by_norm[norm]
                return Candidate(
                    hints.path,
                    c.nse_symbol,
                    c.name,
                    "contents",
                    0.85,
                    reason=f"company name {cell!r} in the workbook",
                )
            if cell.strip().upper() in self.by_symbol and len(cell.strip()) >= 3:
                c = self.by_symbol[cell.strip().upper()]
                return Candidate(
                    hints.path,
                    c.nse_symbol,
                    c.name,
                    "contents",
                    0.75,
                    reason=f"symbol {cell.strip()} in the workbook",
                )
        return Candidate(hints.path, None, None, "none", 0.0, reason="no match: link manually")


def discover(session: Session, hints: list[WorkbookHints]) -> list[Candidate]:
    companies = list(session.scalars(select(Company).where(Company.is_active)))
    linked = {str(m.doc_tag): m for m in session.scalars(select(Model))}
    matcher = Matcher(companies)
    return [matcher.identify(h, linked) for h in hints]


def link(
    session: Session, company: Company, hints: WorkbookHints, name: str | None = None
) -> Model:
    """Confirm a discovered workbook belongs to a company. The bridge then writes the tag."""
    if hints.tag_model_id:
        try:
            existing = session.scalar(
                select(Model).where(Model.doc_tag == uuid.UUID(hints.tag_model_id))
            )
        except ValueError:
            existing = None
        if existing is not None:
            existing.file_path = hints.path
            return existing
    model = Model(
        company_id=company.id,
        origin="discovered",
        file_path=hints.path,
        name=name or PurePath(hints.path).stem,
        fingerprint=hints.fingerprint,
    )
    session.add(model)
    session.flush()
    return model
