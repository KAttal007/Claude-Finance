"""Page classification and selection (design doc 9.1 steps 2-3).

The analyst never picks pages; this does. Keyword patterns + numeric density + position score each
page per category, then the top pages per category are sent to Claude. Tune the patterns against
the golden set in Phase 3.
"""

import re
from dataclasses import dataclass

from t2r.docs.pdf import PageText

CATEGORIES: dict[str, list[str]] = {
    "financial_statements": [
        r"statement of profit and loss",
        r"balance sheet",
        r"cash flow statement",
        r"total income",
        r"profit before tax",
    ],
    "segment": [r"segment (information|reporting|revenue|results)", r"operating segments?"],
    "kpi_table": [
        r"\baum\b",
        r"assets under management",
        r"key (performance )?(metrics|highlights)",
        r"\bnim\b",
        r"net interest margin",
        r"same[- ]store",
        r"volume",
        r"tonnes?",
    ],
    "mdna": [r"management discussion", r"md&a", r"outlook", r"industry overview"],
    "borrowings": [r"borrowings?", r"debt profile", r"cost of funds", r"liabilit(y|ies) mix"],
    "asset_quality": [
        r"\bgnpa\b",
        r"\bnnpa\b",
        r"gross npa",
        r"stage ?3",
        r"provision coverage",
        r"credit cost",
    ],
    "guidance": [r"guidance", r"we expect", r"target(ed)? (growth|margin)", r"going forward"],
}

DEFAULT_LIMITS = {"presentation": 15, "annual_report": 25, "transcript": 0, "other": 10}


@dataclass
class PageScore:
    page: int
    category: str
    score: float


def score_page(page: PageText, total_pages: int) -> dict[str, float]:
    text = page.text.lower()
    scores: dict[str, float] = {}
    for category, patterns in CATEGORIES.items():
        hits = sum(len(re.findall(p, text)) for p in patterns)
        if not hits:
            continue
        score = min(hits, 10) * 1.0
        if category in ("financial_statements", "kpi_table", "segment", "asset_quality"):
            score *= 1 + 2 * page.numeric_density
        if category == "mdna" and total_pages > 50 and page.number < total_pages * 0.5:
            score *= 1.2  # MD&A sits in the first half of an annual report
        scores[category] = score
    return scores


def select_pages(
    pages: list[PageText], kind: str = "presentation", per_category: int = 4, min_score: float = 2.0
) -> list[PageScore]:
    """Top pages per category, capped at the document kind's limit, in page order."""
    limit = DEFAULT_LIMITS.get(kind, 10)
    chosen: dict[int, PageScore] = {}
    by_cat: dict[str, list[PageScore]] = {}
    for page in pages:
        for cat, score in score_page(page, len(pages)).items():
            by_cat.setdefault(cat, []).append(PageScore(page.number, cat, score))
    for scored in by_cat.values():
        for ps in sorted(scored, key=lambda s: -s.score)[:per_category]:
            if ps.score >= min_score and (
                ps.page not in chosen or chosen[ps.page].score < ps.score
            ):
                chosen[ps.page] = ps
    best = sorted(chosen.values(), key=lambda s: -s.score)[:limit]
    return sorted(best, key=lambda s: s.page)
