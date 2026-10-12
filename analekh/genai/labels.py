"""AI fallback for row labels the synonym and fuzzy passes could not place (design doc 12).

Uses the small model with a closed list of fields; the workbook engine caps AI confidence below
fuzzy-match confidence, so these rows are always shown to the user for confirmation.
"""

from typing import Any

from analekh.genai.client import Claude
from analekh.workbook.labels import AiResolver


def _schema(fields: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "field": {"type": ["string", "null"], "enum": [*fields, None]},
            "confidence": {"type": "number"},
        },
        "required": ["field", "confidence"],
        "additionalProperties": False,
    }


def label_resolver(claude: Claude) -> AiResolver:
    """Return an AiResolver backed by ``claude.small_model``; memoised per label."""
    cache: dict[str, tuple[str | None, float]] = {}

    def resolve(label: str, fields: list[str]) -> tuple[str | None, float]:
        if label not in cache:
            out = claude.create_json(
                "label_match",
                _schema(fields),
                model=claude.small_model,
                max_tokens=200,
                system=(
                    "You map row labels from Indian equity research spreadsheets to standard "
                    "financial fields. Answer null when no field clearly fits."
                ),
                messages=[{"role": "user", "content": f"Row label: {label!r}"}],
            )
            conf = max(0.0, min(1.0, float(out.get("confidence", 0))))
            cache[label] = (out.get("field"), conf)
        return cache[label]

    return resolve
