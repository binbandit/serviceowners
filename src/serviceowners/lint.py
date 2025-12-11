from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import GitError
from .gitutils import git_ls_files
from .ownership import OwnershipIndex
from .serviceowners_file import Rule
from .services_file import Service


@dataclass(frozen=True)
class Issue:
    severity: str  # "ERROR" | "WARN"
    code: str
    message: str
    file: str | None = None
    line: int | None = None
    hint: str | None = None


@dataclass(frozen=True)
class LintResult:
    issues: list[Issue]

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "ERROR" for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == "WARN" for i in self.issues)


def lint_rules(
    rules: list[Rule],
    *,
    services: dict[str, Service] | None = None,
    strict: bool = False,
    check_matches: bool = False,
    check_overlaps: bool = False,
    repo_root: Path | None = None,
) -> LintResult:
    """Lint SERVICEOWNERS (+ optional services metadata).

    Philosophy:
    - Default is *fast* and low-noise.
    - Expensive checks are opt-in.
    - Strict mode turns warnings into errors for "enforce in CI" use-cases.
    """
    issues: list[Issue] = []
    services = services or {}

    # Duplicate patterns are nearly always a mistake.
    seen: dict[str, Rule] = {}
    for r in rules:
        prev = seen.get(r.pattern)
        if prev is not None and prev.service != r.service:
            issues.append(
                Issue(
                    severity="WARN" if not strict else "ERROR",
                    code="DUPLICATE_PATTERN",
                    message=(
                        f"Pattern '{r.pattern}' is defined multiple times (last-match wins). "
                        f"Previous: {prev.service} (line {prev.line}), this: {r.service} (line {r.line})."
                    ),
                    file=r.source,
                    line=r.line,
                    hint="Remove duplicates or make precedence explicit.",
                )
            )
        else:
            seen[r.pattern] = r

    # If services metadata exists, validate references and quality.
    if services:
        for r in rules:
            if r.service not in services:
                issues.append(
                    Issue(
                        severity="WARN" if not strict else "ERROR",
                        code="UNKNOWN_SERVICE",
                        message=f"SERVICEOWNERS references unknown service '{r.service}'.",
                        file=r.source,
                        line=r.line,
                        hint="Add it to services.yaml (or fix the spelling).",
                    )
                )

        for name, svc in services.items():
            if not svc.owners and not (svc.contact and (svc.contact.slack or svc.contact.email)):
                issues.append(
                    Issue(
                        severity="WARN",
                        code="SERVICE_HAS_NO_CONTACT",
                        message=f"Service '{name}' has no owners and no contact (slack/email).",
                        hint="Add owners/contact so PRs have someone to page.",
                    )
                )

    idx = OwnershipIndex(rules)

    # Optional: ensure patterns match at least one tracked file.
    if check_matches:
        if repo_root is None:
            issues.append(
                Issue(
                    severity="ERROR",
                    code="GIT_REQUIRED",
                    message="--check-matches requires repo_root (git repo).",
                )
            )
        else:
            try:
                tracked = git_ls_files(repo_root)
            except GitError as e:
                issues.append(Issue(severity="ERROR", code="GIT_ERROR", message=str(e)))
                tracked = []

            for r in rules:
                matched = False
                for f in tracked:
                    if r.compiled.matches(f):
                        matched = True
                        break
                if not matched:
                    issues.append(
                        Issue(
                            severity="WARN" if not strict else "ERROR",
                            code="PATTERN_MATCHES_NOTHING",
                            message=f"Pattern '{r.pattern}' matches no git-tracked files.",
                            file=r.source,
                            line=r.line,
                            hint="Remove it or fix the glob (or ignore if files are generated later).",
                        )
                    )

    # Optional: detect overlaps across different services by scanning tracked files.
    if check_overlaps:
        if repo_root is None:
            issues.append(
                Issue(
                    severity="ERROR",
                    code="GIT_REQUIRED",
                    message="--check-overlaps requires repo_root (git repo).",
                )
            )
        else:
            try:
                tracked = git_ls_files(repo_root)
            except GitError as e:
                issues.append(Issue(severity="ERROR", code="GIT_ERROR", message=str(e)))
                tracked = []

            overlap_examples: list[str] = []
            cap = 25
            for f in tracked:
                m = idx.match(f)
                if len(m.matches) > 1:
                    svcs = [rr.service for rr in m.matches]
                    if len(set(svcs)) > 1:
                        overlap_examples.append(f"{f} -> {', '.join(svcs)}")
                        if len(overlap_examples) >= cap:
                            break

            if overlap_examples:
                issues.append(
                    Issue(
                        severity="WARN",
                        code="OVERLAPPING_RULES",
                        message=(
                            "Some files match multiple services (last-match wins). Examples: "
                            + "; ".join(overlap_examples)
                        ),
                        hint="Often OK. If it's confusing, tighten globs or add comments.",
                    )
                )

    return LintResult(issues=issues)
