"""Hidden tag (design doc 13.2): after the first link, the model ID and company symbol are written
into the workbook's custom document properties, so renames and moves keep working."""

import uuid
from dataclasses import dataclass

from openpyxl import Workbook
from openpyxl.packaging.custom import StringProperty

MODEL_ID = "analekh_model_id"
SYMBOL = "analekh_symbol"


@dataclass(frozen=True)
class Tag:
    model_id: uuid.UUID
    symbol: str


def read_tag(wb: Workbook) -> Tag | None:
    props = {p.name: p.value for p in wb.custom_doc_props.props}
    if MODEL_ID not in props or SYMBOL not in props:
        return None
    try:
        return Tag(uuid.UUID(str(props[MODEL_ID])), str(props[SYMBOL]))
    except ValueError:
        return None


def write_tag(wb: Workbook, tag: Tag) -> None:
    for name in (MODEL_ID, SYMBOL):
        if name in wb.custom_doc_props.names:
            del wb.custom_doc_props[name]
    wb.custom_doc_props.append(StringProperty(name=MODEL_ID, value=str(tag.model_id)))
    wb.custom_doc_props.append(StringProperty(name=SYMBOL, value=tag.symbol))
