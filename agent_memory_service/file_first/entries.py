from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple


ENTRY_PREFIX = "<!-- am:entry "
ENTRY_SUFFIX = " -->"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = dict(meta or {})
    if "created_at" not in cleaned:
        cleaned["created_at"] = _now_iso()
    return cleaned


def format_entry(*, metadata: Dict[str, Any], content_md: str) -> str:
    meta = normalize_metadata(metadata)
    header = f"{ENTRY_PREFIX}{json.dumps(meta, ensure_ascii=False, separators=(',', ':'), default=str)}{ENTRY_SUFFIX}"
    body = (content_md or "").rstrip()
    if body:
        return header + "\n" + body + "\n"
    return header + "\n"


@dataclass(frozen=True)
class ParsedEntry:
    metadata: Dict[str, Any]
    content: str
    start_line: int


def _parse_entry_header(line: str) -> Optional[Dict[str, Any]]:
    s = line.strip()
    if not (s.startswith(ENTRY_PREFIX) and s.endswith(ENTRY_SUFFIX)):
        return None
    raw = s[len(ENTRY_PREFIX) : -len(ENTRY_SUFFIX)]
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def iter_entries(text: str) -> Iterator[ParsedEntry]:
    lines = (text or "").splitlines()
    current_meta: Optional[Dict[str, Any]] = None
    current_start_line = 1
    current_body: List[str] = []

    def _emit() -> Optional[ParsedEntry]:
        if current_meta is None:
            return None
        return ParsedEntry(
            metadata=current_meta,
            content="\n".join(current_body).strip(),
            start_line=current_start_line,
        )

    for idx, line in enumerate(lines, start=1):
        maybe = _parse_entry_header(line)
        if maybe is not None:
            emitted = _emit()
            if emitted is not None:
                yield emitted
            current_meta = maybe
            current_start_line = idx
            current_body = []
            continue
        if current_meta is not None:
            current_body.append(line)

    emitted = _emit()
    if emitted is not None:
        yield emitted


def first_json_code_block(text: str) -> Optional[Dict[str, Any]]:
    """Parse the first ```json fenced code block in a markdown string."""
    lines = (text or "").splitlines()
    inside = False
    buf: List[str] = []
    for line in lines:
        s = line.strip()
        if not inside:
            if s.startswith("```") and s[3:].strip().lower() == "json":
                inside = True
            continue
        if s == "```":
            raw = "\n".join(buf).strip()
            try:
                obj = json.loads(raw)
                return obj if isinstance(obj, dict) else None
            except Exception:
                return None
        buf.append(line)
    return None


def split_chunks_with_line_numbers(text: str, *, min_chars: int = 200) -> List[Tuple[int, str]]:
    """Split a markdown string into chunks; each chunk includes its start line (1-based)."""
    lines = (text or "").splitlines()
    chunks: List[Tuple[int, str]] = []
    buf: List[str] = []
    start_line = 1

    def _flush() -> None:
        nonlocal buf, start_line
        if not buf:
            return
        chunk = "\n".join(buf).strip()
        if chunk:
            chunks.append((start_line, chunk))
        buf = []

    for idx, line in enumerate(lines, start=1):
        if not buf:
            start_line = idx
        buf.append(line)
        if len("\n".join(buf)) >= min_chars and not line.strip():
            _flush()

    _flush()
    return chunks

