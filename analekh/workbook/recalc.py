"""Headless recalculation (design doc 15.1 step 5, 16.5).

- ``evaluate``: computes every formula with the ``formulas`` library and returns the values, used
  to run Checks before a template is activated or a built model is saved.
- ``recalc_file``: round-trips through headless LibreOffice so the saved file carries fresh cached
  values. Desktop Excel (the xlwings bridge) recalculates natively instead.
"""

import os
import re
import shutil
import subprocess
import tempfile
import warnings
from pathlib import Path
from typing import Any

_KEY = re.compile(r"^'?\[(?P<book>[^\]]+)\](?P<sheet>[^!]+?)'?!(?P<ref>[A-Z]+\d+(?::[A-Z]+\d+)?)$")


def evaluate(workbook: bytes) -> dict[tuple[str, str], Any]:
    """{(sheet, "A1"): value} for every cell the formulas model knows. Sheet names upper-case."""
    os.environ.setdefault("TQDM_DISABLE", "1")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        import formulas

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "book.xlsx"
        path.write_bytes(workbook)
        model = formulas.ExcelModel().loads(str(path)).finish()
        solution = model.calculate()
    values: dict[tuple[str, str], Any] = {}
    for key, ranges in solution.items():
        m = _KEY.match(str(key))
        if not m or ":" in m.group("ref"):
            continue
        raw = getattr(ranges, "value", ranges)
        try:
            value = raw[0][0]
        except (TypeError, IndexError):
            value = raw
        values[(m.group("sheet").upper(), m.group("ref"))] = _plain(value)
    return values


def _plain(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):
            return value
    return value


def lookup(values: dict[tuple[str, str], Any], sheet: str, cell: str) -> Any:
    return values.get((sheet.upper(), cell.replace("$", "").upper()))


def recalc_file(workbook: bytes) -> bytes:
    """Round-trip through LibreOffice; returns the input unchanged when it is not installed."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice is None:
        return workbook
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.xlsx"
        src.write_bytes(workbook)
        out_dir = Path(tmp) / "out"
        subprocess.run(
            [
                soffice,
                "--headless",
                "--calc",
                "--convert-to",
                "xlsx",
                "--outdir",
                str(out_dir),
                str(src),
            ],
            check=True,
            timeout=180,
            capture_output=True,
        )
        return (out_dir / "in.xlsx").read_bytes()
