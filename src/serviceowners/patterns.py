from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache


class PatternSyntaxError(ValueError):
    pass


@dataclass(frozen=True)
class CompiledPattern:
    raw: str
    normalized: str
    regex: re.Pattern[str]

    def matches(self, path: str) -> bool:
        return bool(self.regex.match(path))


def _normalize_pattern(pat: str) -> str:
    pat = pat.strip()
    if not pat:
        raise PatternSyntaxError("empty pattern")
    # Normalize path separators
    pat = pat.replace("\\", "/")

    # Strip leading ./ (common when pasting file paths)
    while pat.startswith("./"):
        pat = pat[2:]

    # Leading slash is allowed but doesn't change our internal representation.
    if pat.startswith("/"):
        pat = pat[1:]

    if not pat:
        raise PatternSyntaxError("pattern points to repo root ('/') which is not a file glob")

    # Trailing slash is shorthand for "this directory and everything under it"
    if pat.endswith("/"):
        pat = pat.rstrip("/") + "/**"

    return pat


def _glob_to_regex(pat: str) -> str:
    """Translate a glob to a regex.

    Supported:
      - *  (within a segment)
      - ** (across directories)
      - ?  (single char within a segment)
      - [] character classes (basic)
    """
    out: list[str] = []
    i = 0
    L = len(pat)

    while i < L:
        c = pat[i]

        if c == "*":
            # ** => match across dirs
            if i + 1 < L and pat[i + 1] == "*":
                # collapse consecutive *'s in a ** run
                while i + 1 < L and pat[i + 1] == "*":
                    i += 1
                out.append(".*")
            else:
                out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            # Basic glob character class. We translate it to a regex class.
            j = i + 1
            if j < L and pat[j] in ("!", "^"):
                j += 1
            # Find closing bracket.
            while j < L and pat[j] != "]":
                j += 1
            if j >= L:
                # Treat lone '[' literally.
                out.append(re.escape(c))
            else:
                inner = pat[i + 1 : j]
                # Glob uses ! for negation; regex uses ^
                if inner.startswith("!"):
                    inner = "^" + inner[1:]
                # We intentionally do minimal escaping here; users can still escape with backslashes in pattern.
                inner = inner.replace("\\", "\\\\")
                out.append("[" + inner + "]")
                i = j
        else:
            out.append(re.escape(c))

        i += 1

    return "".join(out)


@lru_cache(maxsize=4096)
def compile_pattern(pattern: str) -> CompiledPattern:
    raw = pattern
    norm = _normalize_pattern(pattern)

    body = _glob_to_regex(norm)

    # Anchoring rules:
    # - If pattern contains '/', we match from repo root (start of path)
    # - If pattern has no '/', we treat it as a basename glob (matches any file basename)
    if "/" in norm:
        rx = "^" + body + "$"
    else:
        rx = r"(^|.*/)" + body + "$"

    try:
        compiled = re.compile(rx)
    except re.error as e:
        raise PatternSyntaxError(f"invalid pattern '{raw}': {e}") from e

    return CompiledPattern(raw=raw, normalized=norm, regex=compiled)
