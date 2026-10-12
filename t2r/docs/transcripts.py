"""Earnings-call transcripts: speaker-aware parsing (design doc 9.3).

Indian call transcripts usually print "Name:" at the start of each turn, with a Moderator
introducing analysts ("The next question is from X from Y Securities"). Phase 3: confirm against
real transcripts and whether they appear in the announcements feed consistently (open q 22.3).
"""

import re
from dataclasses import dataclass

from t2r.docs.pdf import PageText

_TURN = re.compile(r"^(?P<speaker>[A-Z][A-Za-z.\s]{1,60}?):\s*(?P<text>.*)$")
_NEXT_Q = re.compile(
    r"(?:question|line) is from (?:the line of )?(?P<name>[A-Z][\w.\s]+?)"
    r"(?: from| of|\.|,)",
    re.IGNORECASE,
)


@dataclass
class Turn:
    speaker: str
    role: str  # management, analyst, moderator
    page: int
    text: str


def parse_turns(pages: list[PageText], management: set[str] | None = None) -> list[Turn]:
    analysts: set[str] = set()
    management = {m.lower() for m in (management or set())}
    turns: list[Turn] = []
    for page in pages:
        for line in page.text.splitlines():
            m = _TURN.match(line.strip())
            if m:
                speaker = " ".join(m.group("speaker").split())
                turns.append(
                    Turn(
                        speaker, _role(speaker, analysts, management), page.number, m.group("text")
                    )
                )
                if turns[-1].role == "moderator":
                    for q in _NEXT_Q.finditer(m.group("text")):
                        analysts.add(" ".join(q.group("name").split()).lower())
            elif turns and line.strip():
                turns[-1].text += " " + line.strip()
    return turns


def _role(speaker: str, analysts: set[str], management: set[str]) -> str:
    s = speaker.lower()
    if s == "moderator":
        return "moderator"
    if s in management:
        return "management"
    if s in analysts or any(a.split()[0] == s.split()[0] for a in analysts if a):
        return "analyst"
    return "management"  # default: unknown speakers are usually company executives


def as_prompt_text(turns: list[Turn]) -> str:
    return "\n".join(f"[p{t.page}] {t.speaker} ({t.role}): {t.text}" for t in turns)
