"""Workbook fingerprint (design doc 12, 13.3): a hash of structure and values used to detect edits
made outside the system. Any difference from the last seen fingerprint triggers a rescan before
a change set is planned."""

import hashlib

from openpyxl import Workbook


def fingerprint(wb: Workbook) -> str:
    h = hashlib.sha256()
    for ws in wb.worksheets:
        h.update(f"\x00sheet:{ws.title}".encode())
        for row in ws.iter_rows():
            for c in row:
                if c.value is None:
                    continue
                h.update(f"\x01{c.coordinate}={type(c.value).__name__}:{c.value}".encode())
    return h.hexdigest()
