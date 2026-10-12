"""Excel bridge (design doc 10.6, 13): a small local service on the analyst's machine that drives
desktop Excel through xlwings. It receives approved change items, writes them, lets Excel
recalculate natively, and saves a NEW file next to the original (never overwrites).

Runs outside Docker: ``uv sync --extra excel && python -m t2r.excel_bridge``.
Only listens on localhost.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from t2r.modelsync.apply import coerce

app = FastAPI(title="T2R Excel bridge")


class Item(BaseModel):
    kind: str
    sheet: str
    cell: str
    value: str | None = None
    formula: str | None = None


class ApplyRequest(BaseModel):
    workbook_path: str
    items: list[Item]
    change_set_id: int | None = None


class ReadRequest(BaseModel):
    workbook_path: str
    ranges: list[str]  # "Sheet!A1:D10"


def _xw() -> Any:
    try:
        import xlwings as xw
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(500, "xlwings not installed: uv sync --extra excel") from exc
    return xw


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/apply")
def apply(req: ApplyRequest) -> dict:  # pragma: no cover - needs desktop Excel
    xw = _xw()
    src = Path(req.workbook_path).expanduser().resolve()
    if not src.exists():
        raise HTTPException(404, f"{src} not found")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f"cs{req.change_set_id}-{stamp}" if req.change_set_id else stamp
    dst = src.with_name(f"{src.stem}.{suffix}{src.suffix}")

    app_ = xw.App(visible=False, add_book=False)
    try:
        book = app_.books.open(str(src))
        for item in req.items:
            rng = book.sheets[item.sheet].range(item.cell)
            if item.formula:
                rng.formula = item.formula
            else:
                rng.value = coerce(item.value)
        book.app.calculate()
        book.save(str(dst))
        book.close()
    finally:
        app_.quit()
    return {"saved_as": str(dst), "written": len(req.items)}


@app.post("/read")
def read(req: ReadRequest) -> dict:  # pragma: no cover - needs desktop Excel
    xw = _xw()
    book = xw.Book(str(Path(req.workbook_path).expanduser()))
    out = {}
    for ref in req.ranges:
        sheet, _, addr = ref.partition("!")
        out[ref] = book.sheets[sheet].range(addr).value
    return out
