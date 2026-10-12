"""Static formula dependency graph (design doc 10.2).

Built from openpyxl's formula tokenizer, so no Excel is needed. INDIRECT/OFFSET (and other
volatile reference functions) cannot be resolved statically: any cell using them is reported as
unknown impact rather than guessed at.
"""

import re
from collections import defaultdict, deque

from openpyxl.formula.tokenizer import Token, Tokenizer
from openpyxl.utils.cell import column_index_from_string, get_column_letter, range_boundaries
from openpyxl.workbook import Workbook

VOLATILE = {"INDIRECT", "OFFSET"}
MAX_RANGE_CELLS = 50_000

CellKey = tuple[str, str]  # (sheet, "A1")

_REF = re.compile(
    r"^(?:(?P<sheet>'[^']+'|[^!]+)!)?(?P<ref>\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?)$"
)


def expand(ref: str) -> list[str]:
    ref = ref.replace("$", "")
    if ":" not in ref:
        return [ref]
    min_col, min_row, max_col, max_row = range_boundaries(ref)
    assert min_col and min_row and max_col and max_row
    if (max_col - min_col + 1) * (max_row - min_row + 1) > MAX_RANGE_CELLS:
        return []
    return [
        f"{get_column_letter(c)}{r}"
        for c in range(min_col, max_col + 1)
        for r in range(min_row, max_row + 1)
    ]


def references(formula: str, own_sheet: str) -> tuple[set[CellKey], bool]:
    """Cells a formula reads, and whether it uses a volatile reference function."""
    refs: set[CellKey] = set()
    volatile = False
    for tok in Tokenizer(formula).items:
        if tok.type == Token.FUNC and tok.subtype == Token.OPEN:
            if tok.value.rstrip("(").upper() in VOLATILE:
                volatile = True
        elif tok.type == Token.OPERAND and tok.subtype == Token.RANGE:
            m = _REF.match(tok.value)
            if not m:
                continue  # named ranges, whole columns, external links: not resolved
            sheet = (m.group("sheet") or own_sheet).strip("'")
            refs.update((sheet, cell) for cell in expand(m.group("ref")))
    return refs, volatile


class DependencyGraph:
    def __init__(self, wb: Workbook) -> None:
        self.dependents: dict[CellKey, set[CellKey]] = defaultdict(set)
        self.volatile: set[CellKey] = set()
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    value = cell.value
                    if isinstance(value, str) and value.startswith("="):
                        key = (ws.title, cell.coordinate)
                        refs, is_volatile = references(value, ws.title)
                        if is_volatile:
                            self.volatile.add(key)
                        for ref in refs:
                            self.dependents[ref].add(key)

    def downstream(self, cells: list[CellKey]) -> set[CellKey]:
        seen: set[CellKey] = set()
        queue = deque(cells)
        while queue:
            for dep in self.dependents.get(queue.popleft(), ()):
                if dep not in seen:
                    seen.add(dep)
                    queue.append(dep)
        return seen

    def impact(self, cells: list[CellKey]) -> dict[str, object]:
        downstream = self.downstream(cells)
        return {
            "dependents": len(downstream),
            "unknown_impact": sorted(f"{s}!{c}" for s, c in self.volatile),
            "sheets": sorted({s for s, _ in downstream}),
        }


def column_letter_shift(cell: str, by: int) -> str:
    m = re.match(r"([A-Z]+)(\d+)", cell)
    assert m
    return f"{get_column_letter(column_index_from_string(m.group(1)) + by)}{m.group(2)}"
