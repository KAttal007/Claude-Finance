"""Single entry point for Claude API calls; logs tokens per call in llm_calls (design doc 11.3, 19).

Every call enables server-side refusal fallbacks (``fallbacks="default"``) so a safety-classifier
decline is retried on Anthropic's recommended fallback model instead of failing the job.
"""

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any

import anthropic
from sqlalchemy.orm import Session

from t2r.config import get_settings
from t2r.db.models import LlmCall

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class RefusalError(RuntimeError):
    pass


@dataclass
class ClaudeResult:
    text: str
    message: Any  # anthropic BetaMessage
    input_tokens: int
    output_tokens: int


def request_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def pdf_block(data: bytes) -> dict[str, Any]:
    return {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.standard_b64encode(data).decode(),
        },
    }


class Claude:
    def __init__(
        self, session: Session | None = None, client: anthropic.Anthropic | None = None
    ) -> None:
        s = get_settings()
        self.session = session
        self.model = s.claude_model
        self.small_model = s.claude_small_model
        self.client = client or anthropic.Anthropic(api_key=s.anthropic_api_key or None)

    def create(
        self,
        purpose: str,
        *,
        messages: list[dict[str, Any]],
        system: Any = None,
        model: str | None = None,
        max_tokens: int = 16000,
        effort: str | None = None,
        json_schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> ClaudeResult:
        model = model or self.model
        kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": messages}
        if system is not None:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
        output_config: dict[str, Any] = {}
        if effort:
            output_config["effort"] = effort
        if json_schema:
            output_config["format"] = {"type": "json_schema", "schema": json_schema}
        if output_config:
            kwargs["output_config"] = output_config

        message = self.client.beta.messages.create(
            **kwargs,
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        if message.stop_reason == "refusal":
            raise RefusalError(f"{purpose}: request declined ({message.stop_details})")
        self._log(purpose, model, kwargs, message.usage.input_tokens, message.usage.output_tokens)
        text = "".join(b.text for b in message.content if b.type == "text")
        return ClaudeResult(text, message, message.usage.input_tokens, message.usage.output_tokens)

    def create_json(self, purpose: str, schema: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        result = self.create(purpose, json_schema=schema, **kwargs)
        return json.loads(result.text)

    def _log(
        self,
        purpose: str,
        model: str,
        payload: dict[str, Any],
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        if self.session is None:
            return
        self.session.add(
            LlmCall(
                purpose=purpose,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                request_hash=request_hash(payload),
            )
        )
