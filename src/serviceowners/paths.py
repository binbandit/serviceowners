from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Iterable


def to_posix(path: str) -> str:
    return path.replace("\\", "/")


def normalize_repo_path(path: str, repo_root: Path | None = None) -> str:
    """Normalize a file path for matching.

    - Converts backslashes to slashes
    - If absolute and repo_root is provided, makes it relative to repo_root
    - Strips leading './' (repeatable) and a single leading '/'
    """
    p = to_posix(path).strip()

    # Trim surrounding quotes (common when copying from tooling)
    if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
        p = p[1:-1]

    if repo_root is not None:
        try:
            pp = Path(p)
            if pp.is_absolute():
                p = str(pp.relative_to(repo_root))
        except Exception:
            # If we can't relativize, continue with original.
            pass

    while p.startswith("./"):
        p = p[2:]
    if p.startswith("/"):
        p = p[1:]

    return str(PurePosixPath(p))


def normalize_paths(paths: Iterable[str], repo_root: Path | None = None) -> list[str]:
    return [normalize_repo_path(p, repo_root=repo_root) for p in paths if p and p.strip()]
