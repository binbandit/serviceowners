from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

from .errors import GitError


def _run_git(repo_root: Path, args: Sequence[str]) -> str:
    try:
        cp = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        return cp.stdout
    except FileNotFoundError as e:
        raise GitError("git not found on PATH") from e
    except subprocess.CalledProcessError as e:
        msg = e.stderr.strip() or e.stdout.strip() or str(e)
        raise GitError(f"git {' '.join(args)} failed: {msg}") from e


def find_repo_root(cwd: Path | None = None) -> Path:
    cwd = cwd or Path.cwd()
    out = _run_git(cwd, ["rev-parse", "--show-toplevel"]).strip()
    if not out:
        raise GitError("Not a git repository (or any of the parent directories)")
    return Path(out)


def git_diff_name_only(repo_root: Path, rev_range: str) -> list[str]:
    # Include renames and deletions; callers can decide how to treat missing files.
    out = _run_git(repo_root, ["diff", "--name-only", rev_range])
    files = [line.strip() for line in out.splitlines() if line.strip()]
    return files


def git_ls_files(repo_root: Path) -> list[str]:
    out = _run_git(repo_root, ["ls-files", "-z"])
    if not out:
        return []
    parts = out.split("\0")
    return [p for p in parts if p]


def is_git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False
