from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping

from .errors import GitHubError


GITHUB_API = "https://api.github.com"


def _request(
    method: str,
    url: str,
    *,
    token: str,
    body: Mapping[str, Any] | None = None,
    timeout_s: int = 20,
) -> tuple[int, dict[str, Any], dict[str, str]]:
    data: bytes | None = None
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "serviceowners",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
            payload = json.loads(raw) if raw else {}
            return resp.status, payload, dict(resp.headers.items())
    except urllib.error.HTTPError as e:
        raw = (e.read() or b"").decode("utf-8", errors="replace")
        try:
            details = json.loads(raw) if raw else {}
        except Exception:
            details = {"raw": raw}
        raise GitHubError(f"GitHub API {method} {url} failed: {e.code} {e.reason}: {details}") from e
    except urllib.error.URLError as e:
        raise GitHubError(f"GitHub API {method} {url} failed: {e}") from e


def _comments_url(owner: str, repo: str, pr_number: int) -> str:
    return f"{GITHUB_API}/repos/{owner}/{repo}/issues/{pr_number}/comments"


def _comment_url(owner: str, repo: str, comment_id: int) -> str:
    return f"{GITHUB_API}/repos/{owner}/{repo}/issues/comments/{comment_id}"


def find_existing_comment_id(
    owner: str,
    repo: str,
    pr_number: int,
    *,
    token: str,
    marker: str,
    max_pages: int = 10,
) -> int | None:
    # Paginate through issue comments and find our marker.
    for page in range(1, max_pages + 1):
        url = _comments_url(owner, repo, pr_number) + f"?per_page=100&page={page}"
        _, payload, _ = _request("GET", url, token=token)
        if not isinstance(payload, list):
            return None

        for c in payload:
            body = (c.get("body") or "") if isinstance(c, dict) else ""
            if marker in body:
                cid = c.get("id")
                if isinstance(cid, int):
                    return cid

        if len(payload) < 100:
            break

    return None


def upsert_pr_comment(
    owner: str,
    repo: str,
    pr_number: int,
    *,
    token: str,
    body: str,
    marker: str,
) -> None:
    cid = find_existing_comment_id(owner, repo, pr_number, token=token, marker=marker)
    if cid is None:
        _request("POST", _comments_url(owner, repo, pr_number), token=token, body={"body": body})
    else:
        _request("PATCH", _comment_url(owner, repo, cid), token=token, body={"body": body})
