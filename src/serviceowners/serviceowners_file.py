from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .errors import ParseError
from .patterns import CompiledPattern, PatternSyntaxError, compile_pattern


@dataclass(frozen=True)
class Rule:
    pattern: str
    service: str
    line: int
    source: str

    compiled: CompiledPattern


def _strip_inline_comment(line: str) -> str:
    # Remove inline comments like: "foo/**  api  # comment"
    # but keep hashes in patterns like "docs/#/foo" (rare).
    in_quote = False
    for i, ch in enumerate(line):
        if ch in ("'", '"'):
            in_quote = not in_quote
        if ch == "#" and not in_quote:
            # Only treat as comment if preceded by whitespace.
            if i == 0 or line[i - 1].isspace():
                return line[:i].rstrip()
    return line.rstrip()


def parse_serviceowners_text(text: str, source: str = "SERVICEOWNERS") -> list[Rule]:
    rules: list[Rule] = []
    for idx, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = _strip_inline_comment(raw).strip()
        if not line:
            continue

        parts = line.split()
        if len(parts) != 2:
            raise ParseError(
                f"{source}:{idx}: expected 2 columns: <pattern> <service>. Got: {raw!r}"
            )
        pat, svc = parts[0].strip(), parts[1].strip()
        if not svc:
            raise ParseError(f"{source}:{idx}: empty service name")

        try:
            compiled = compile_pattern(pat)
        except PatternSyntaxError as e:
            raise ParseError(f"{source}:{idx}: {e}") from e

        rules.append(Rule(pattern=pat, service=svc, line=idx, source=source, compiled=compiled))

    if not rules:
        # Empty is valid; user might be starting out.
        return []

    return rules


def load_serviceowners(path: Path) -> list[Rule]:
    if not path.exists():
        raise ParseError(f"SERVICEOWNERS file not found: {path}")
    try:
        txt = path.read_text(encoding="utf-8")
    except Exception as e:
        raise ParseError(f"Failed to read SERVICEOWNERS: {path}: {e}") from e
    return parse_serviceowners_text(txt, source=str(path))
