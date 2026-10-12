"""Link feed items to universe companies (design doc 9.2): normalised name first, then symbol or
ISIN when present; unmatched items stay unlinked and are queued for review."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from analekh.db.models import Company

FUZZY_THRESHOLD = 92
_SUFFIXES = re.compile(r"\b(limited|ltd|private|pvt|the|india|co|company|corporation|corp)\b\.?")
_ISIN = re.compile(r"\bINE[0-9A-Z]{9}\b")


def normalise_name(name: str) -> str:
    name = name.lower().replace("&", " and ")
    name = _SUFFIXES.sub(" ", name)
    return re.sub(r"[^a-z0-9]+", " ", name).strip()


@dataclass
class CompanyIndex:
    """In-memory index over the active universe, built once per polling run."""

    by_norm: dict[str, Company]
    by_symbol: dict[str, Company]
    by_isin: dict[str, Company]

    @classmethod
    def build(cls, companies: Iterable[Company]) -> "CompanyIndex":
        companies = list(companies)
        return cls(
            by_norm={normalise_name(c.name): c for c in companies},
            by_symbol={c.nse_symbol.upper(): c for c in companies},
            by_isin={c.isin: c for c in companies if c.isin},
        )

    def match(self, title: str, description: str = "") -> Company | None:
        if not title and not description:
            return None
        norm = normalise_name(title)
        if norm in self.by_norm:
            return self.by_norm[norm]
        text = f"{title} {description}".upper()
        for isin in _ISIN.findall(text):
            if isin in self.by_isin:
                return self.by_isin[isin]
        for token in re.findall(r"\b[A-Z0-9&-]{2,20}\b", title.upper()):
            if token in self.by_symbol:
                return self.by_symbol[token]
        if self.by_norm and norm:
            best = process.extractOne(norm, list(self.by_norm), scorer=fuzz.token_set_ratio)
            if best and best[1] >= FUZZY_THRESHOLD:
                return self.by_norm[best[0]]
        return None
