from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import GitError, UsageError
from .gitutils import find_repo_root, git_diff_name_only
from .impact import compute_impact
from .lint import lint_rules
from .markdown import render_impact_comment, render_impact_markdown, render_lint_markdown
from .ownership import OwnershipIndex
from .paths import normalize_paths
from .serviceowners_file import load_serviceowners
from .services_file import load_services
from .github_api import upsert_pr_comment


@dataclass(frozen=True)
class ActionInputs:
    serviceowners_file: str = "SERVICEOWNERS"
    services_file: str = "services.yaml"
    diff: str | None = None
    comment: bool = True
    fail_on_unmapped: bool = True
    strict_lint: bool = False


def _load_github_event() -> tuple[str | None, dict[str, Any] | None]:
    event_name = os.getenv("GITHUB_EVENT_NAME")
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if not event_name or not event_path:
        return None, None
    try:
        payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return event_name, payload
    except Exception:
        pass
    return event_name, None


def _determine_diff(inputs: ActionInputs, event_name: str | None, payload: dict[str, Any] | None) -> str:
    if inputs.diff:
        return inputs.diff

    if payload and event_name in ("pull_request", "pull_request_target"):
        pr = payload.get("pull_request") or {}
        base = (pr.get("base") or {}).get("sha")
        head = (pr.get("head") or {}).get("sha")
        if base and head:
            return f"{base}...{head}"

    if payload and event_name == "push":
        before = payload.get("before")
        after = payload.get("after")
        if before and after:
            return f"{before}...{after}"

    # Fallback: last commit
    return "HEAD~1...HEAD"


def _get_pr_number(event_name: str | None, payload: dict[str, Any] | None) -> int | None:
    if not payload:
        return None
    if event_name in ("pull_request", "pull_request_target"):
        num = payload.get("number")
        return int(num) if isinstance(num, int) else None
    return None


def _github_repo() -> tuple[str, str]:
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        raise UsageError("GITHUB_REPOSITORY is not set (expected 'owner/repo')")
    owner, name = repo.split("/", 1)
    return owner, name


def _write_step_summary(markdown: str) -> None:
    p = os.getenv("GITHUB_STEP_SUMMARY")
    if not p:
        return
    try:
        Path(p).write_text(markdown, encoding="utf-8")
    except Exception:
        # Don't fail the action if the summary can't be written.
        pass


def _write_outputs(*, impacted_services: list[str], unmapped_files: list[str]) -> None:
    out = os.getenv("GITHUB_OUTPUT")
    if not out:
        return
    try:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"impacted_services={json.dumps(impacted_services)}\n")
            f.write(f"unmapped_files={json.dumps(unmapped_files)}\n")
    except Exception:
        pass


def run_action(inputs: ActionInputs) -> int:
    repo_root = find_repo_root()

    svcowners_path = (repo_root / inputs.serviceowners_file).resolve()
    services_path = (repo_root / inputs.services_file).resolve()

    rules = load_serviceowners(svcowners_path)
    services = load_services(services_path)

    event_name, payload = _load_github_event()
    diff = _determine_diff(inputs, event_name, payload)

    try:
        changed_files = git_diff_name_only(repo_root, diff)
    except GitError as e:
        raise UsageError(
            f"Unable to compute git diff '{diff}': {e}\n"
            "If this is running in GitHub Actions, ensure actions/checkout uses fetch-depth: 0."
        ) from e

    changed_files = normalize_paths(changed_files, repo_root=repo_root)

    index = OwnershipIndex(rules)
    report = compute_impact(index, changed_files)

    # Lint (fast by default)
    lint = lint_rules(rules, services=services, strict=False, repo_root=repo_root)

    # Step summary: richer + includes lint
    summary_parts = []
    summary_parts.append(f"_Diff_: `{diff}`\n")
    summary_parts.append(
        render_impact_markdown(report, services=services, include_files=True, max_files_per_service=100)
    )
    summary_parts.append(render_lint_markdown(lint))
    _write_step_summary("\n".join(summary_parts))

    # Outputs for other steps
    _write_outputs(impacted_services=report.impacted_services(), unmapped_files=report.unmapped_files)

    # PR comment (compact)
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or ""
    pr_number = _get_pr_number(event_name, payload)

    if inputs.comment and token and pr_number is not None:
        owner, repo = _github_repo()
        body = render_impact_comment(report, services=services, marker="serviceowners", title="🧭 ServiceOwners")
        upsert_pr_comment(owner, repo, pr_number, token=token, body=body, marker="<!-- serviceowners:begin -->")

    # Exit rules
    if lint.has_errors:
        return 2
    if inputs.strict_lint and lint.has_warnings:
        return 2
    if inputs.fail_on_unmapped and report.unmapped_files:
        return 3
    return 0
