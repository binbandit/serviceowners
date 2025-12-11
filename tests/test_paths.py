from pathlib import Path

from serviceowners.paths import normalize_repo_path


def test_normalize_repo_path_keeps_dotfiles():
    p = normalize_repo_path(".github/workflows/ci.yml", repo_root=Path("/tmp/irrelevant"))
    assert p == ".github/workflows/ci.yml"
