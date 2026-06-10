from __future__ import annotations

import html
import re

ASS_TAG_RE = re.compile(r"\{\\[^}]*\}")
HTML_TAG_RE = re.compile(r"<[^>]+>")
HEARING_IMPAIRED_RE = re.compile(
    r"^\s*[\[(]\s*(?:music|applause|laughs?|laughter|sighs?|gasps?|groans?|coughs?|thunder|door\s+opens?|door\s+closes?|phone\s+rings?|ringing|speaking\s+foreign\s+language)\s*[\])]\s*$",
    re.IGNORECASE,
)
MUSIC_WRAPPER_RE = re.compile(r"^[\s♪♫♬♩]+|[\s♪♫♬♩]+$")
WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(value: str, *, strip_hearing_impaired: bool = True) -> str:
    """Return subtitle text normalized for indexing and chunking."""

    cleaned = html.unescape(value)
    cleaned = ASS_TAG_RE.sub("", cleaned)
    cleaned = HTML_TAG_RE.sub("", cleaned)
    cleaned = cleaned.replace("\\N", "\n").replace("\\n", "\n")

    normalized_lines: list[str] = []
    previous: str | None = None
    for raw_line in cleaned.splitlines() or [cleaned]:
        line = MUSIC_WRAPPER_RE.sub("", raw_line.strip())
        line = WHITESPACE_RE.sub(" ", line).strip()
        if not line:
            continue
        if strip_hearing_impaired and HEARING_IMPAIRED_RE.match(line):
            continue
        if line == previous:
            continue
        normalized_lines.append(line)
        previous = line

    return WHITESPACE_RE.sub(" ", " ".join(normalized_lines)).strip()
