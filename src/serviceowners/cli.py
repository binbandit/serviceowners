from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .action_runner import ActionInputs, run_action
from .errors import GitError, ParseError, UsageError
from .gitutils import find_repo_root, git_diff_name_only
from .impact import compute_impact
from .lint import lint_rules
from .markdown import render_impact_markdown, render_lint_markdown
from .ownership import OwnershipIndex
from .paths import normalize_repo_path, normalize_paths
from .serviceowners_file import load_serviceowners, parse_serviceowners_text
from .services_file import load_services
from .version import __version__


def _repo_root(args_repo_root: str | None) -> Path:
    if args_repo_root:
        return Path(args_repo_root).resolve()
    try:
        return find_repo_root()
    except GitError:
        return Path.cwd()


def _load(repo_root: Path, serviceowners_file: str, services_file: str):
    rules = load_serviceowners(repo_root / serviceowners_file)
    services = load_services(repo_root / services_file)
    return rules, services


def cmd_who_owns(args: argparse.Namespace) -> int:
    repo_root = _repo_root(args.repo_root)
    rules, services = _load(repo_root, args.serviceowners_file, args.services_file)

    idx = OwnershipIndex(rules)
    path = normalize_repo_path(args.path, repo_root=repo_root)
    m = idx.match(path)

    if args.format == "json":
        payload = {
            "path": path,
            "service": m.service,
            "chosen_rule": {
                "pattern": m.chosen.pattern,
                "service": m.chosen.service,
                "line": m.chosen.line,
                "source": m.chosen.source,
            }
            if m.chosen
            else None,
            "matches": [
                {"pattern": r.pattern, "service": r.service, "line": r.line, "source": r.source}
                for r in m.matches
            ],
            "version": __version__,
        }
        print(json.dumps(payload, indent=2))
        return 0

    if m.service is None:
        print(f"{path}: (unmapped)")
        if args.explain and m.matches:
            print("")
            print("Matched rules:")
            for r in m.matches:
                print(f"- {r.pattern} -> {r.service} ({r.source}:{r.line})")
        return 0

    print(f"{path}: {m.service}")
    meta = services.get(m.service)
    if meta:
        owners = ", ".join([o.display() for o in meta.owners if o.display()])
        if owners:
            print(f"  owners: {owners}")
        if meta.contact and meta.contact.slack:
            print(f"  slack: {meta.contact.slack}")
        if meta.contact and meta.contact.email:
            print(f"  email: {meta.contact.email}")
        if meta.runbook:
            print(f"  runbook: {meta.runbook}")
        if meta.docs:
            print(f"  docs: {meta.docs}")

    if args.explain:
        print("")
        if not m.matches:
            print("No matching rules.")
        else:
            print("Matched rules (last-match wins):")
            for r in m.matches:
                chosen = "  <== chosen" if m.chosen and r == m.chosen else ""
                print(f"- {r.pattern} -> {r.service} ({r.source}:{r.line}){chosen}")

    return 0


def cmd_impacted(args: argparse.Namespace) -> int:
    repo_root = _repo_root(args.repo_root)
    rules, services = _load(repo_root, args.serviceowners_file, args.services_file)

    if args.stdin:
        changed = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
    else:
        diff = args.diff or "HEAD~1...HEAD"
        changed = git_diff_name_only(repo_root, diff)

    changed = normalize_paths(changed, repo_root=repo_root)
    idx = OwnershipIndex(rules)
    report = compute_impact(idx, changed)

    if args.format == "json":
        payload = {
            "diff": args.diff,
            "impacted_services": report.impacted_services(),
            "services": {k: {"count": len(v), "files": v} for k, v in sorted(report.services_to_files.items())},
            "unmapped_files": report.unmapped_files,
            "total_files": report.total_files(),
            "version": __version__,
        }
        print(json.dumps(payload, indent=2))
    else:
        md = render_impact_markdown(
            report,
            services=services,
            include_files=args.show_files,
            max_files_per_service=args.max_files,
            include_unmapped=True,
            title="Impacted services",
        )
        print(md)

    if args.fail_on_unmapped and report.unmapped_files:
        return 3
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    repo_root = _repo_root(args.repo_root)
    rules, services = _load(repo_root, args.serviceowners_file, args.services_file)

    res = lint_rules(
        rules,
        services=services,
        strict=False,
        check_matches=args.check_matches,
        check_overlaps=args.check_overlaps,
        repo_root=repo_root,
    )

    if args.format == "json":
        payload = {
            "issues": [
                {
                    "severity": i.severity,
                    "code": i.code,
                    "message": i.message,
                    "file": i.file,
                    "line": i.line,
                    "hint": i.hint,
                }
                for i in res.issues
            ],
            "version": __version__,
        }
        print(json.dumps(payload, indent=2))
    else:
        print(render_lint_markdown(res, title="Lint"))

    if res.has_errors:
        return 2
    if args.strict and res.has_warnings:
        return 2
    return 0


def _find_codeowners(repo_root: Path) -> Path | None:
    candidates = [repo_root / "CODEOWNERS", repo_root / ".github" / "CODEOWNERS", repo_root / "docs" / "CODEOWNERS"]
    for p in candidates:
        if p.exists():
            return p
    return None


def _infer_service_from_pattern(pattern: str) -> str | None:
    # Extract last non-glob path segment.
    p = pattern.strip().lstrip("/")
    if p.endswith("/"):
        p = p.rstrip("/")
    p = p.replace("\\", "/")

    # Drop trailing glob segments.
    parts = [seg for seg in p.split("/") if seg]
    if not parts:
        return None

    # Remove segments that are clearly globs.
    def is_literal(seg: str) -> bool:
        return not any(ch in seg for ch in ("*", "?", "[", "]"))

    literals = [seg for seg in parts if is_literal(seg)]
    if not literals:
        return None

    candidate = literals[-1].strip().lower()
    if candidate in (".github", "src", "lib", "apps", "services"):
        # not great; but still better than nothing
        pass
    return candidate or None


def _infer_service_from_owner(owner: str) -> str | None:
    o = owner.strip()
    if not o:
        return None
    if o.startswith("@"):
        o = o[1:]
    if "/" in o:
        o = o.split("/", 1)[1]
    o = o.replace("-", "_").lower()
    return o or None


def cmd_init(args: argparse.Namespace) -> int:
    repo_root = _repo_root(args.repo_root)
    codeowners_path = Path(args.codeowners).resolve() if args.codeowners else _find_codeowners(repo_root)
    if not codeowners_path or not codeowners_path.exists():
        raise UsageError("CODEOWNERS file not found (use --codeowners PATH)")

    txt = codeowners_path.read_text(encoding="utf-8")
    lines_out: list[str] = []
    lines_out.append("# Generated from CODEOWNERS")
    lines_out.append("# pattern    service")
    for raw in txt.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # CODEOWNERS: pattern + one or more owners
        parts = line.split()
        if len(parts) < 2:
            continue
        pattern = parts[0]
        owners = parts[1:]

        svc = _infer_service_from_pattern(pattern) or _infer_service_from_owner(owners[0]) or "service"
        lines_out.append(f"{pattern}\t{svc}")

    out_text = "\n".join(lines_out) + "\n"

    if args.write:
        out_path = repo_root / args.serviceowners_file
        if out_path.exists() and not args.force:
            raise UsageError(f"{out_path} already exists (use --force to overwrite)")
        out_path.write_text(out_text, encoding="utf-8")
        print(f"Wrote {out_path}")
    else:
        print(out_text)

    return 0


def cmd_action(args: argparse.Namespace) -> int:
    inputs = ActionInputs(
        serviceowners_file=args.serviceowners_file,
        services_file=args.services_file,
        diff=args.diff,
        comment=(args.comment.lower() == "true"),
        fail_on_unmapped=(args.fail_on_unmapped.lower() == "true"),
        strict_lint=(args.strict_lint.lower() == "true"),
    )
    return run_action(inputs)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sowners", description="ServiceOwners - repo-native service ownership mapping")
    p.add_argument("--serviceowners-file", default="SERVICEOWNERS", help="Path to SERVICEOWNERS (relative to repo root)")
    p.add_argument("--services-file", default="services.yaml", help="Path to services.yaml (relative to repo root)")
    p.add_argument("--repo-root", default=None, help="Repository root (default: auto-detect with git)")
    p.add_argument("--version", action="version", version=f"serviceowners {__version__}")

    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("who-owns", aliases=["who", "owner"], help="Find the service for a path")
    w.add_argument("path", help="Path to a file (relative or absolute)")
    w.add_argument("--format", choices=["text", "json"], default="text")
    w.add_argument("--explain", action="store_true", help="Show the matching rules and precedence")
    w.set_defaults(func=cmd_who_owns)

    im = sub.add_parser("impacted", aliases=["impact"], help="Compute impacted services for a diff or file list")
    im.add_argument("--diff", default=None, help="Git rev range, e.g. origin/main...HEAD")
    im.add_argument("--stdin", action="store_true", help="Read changed files (one per line) from stdin")
    im.add_argument("--format", choices=["text", "json"], default="text")
    im.add_argument("--show-files", action="store_true", help="List changed files per service")
    im.add_argument("--max-files", type=int, default=50, help="Max files to show per service in text output")
    im.add_argument("--fail-on-unmapped", action="store_true", help="Exit 3 if any unmapped files exist")
    im.set_defaults(func=cmd_impacted)

    l = sub.add_parser("lint", help="Lint SERVICEOWNERS and services.yaml")
    l.add_argument("--format", choices=["text", "json"], default="text")
    l.add_argument("--strict", action="store_true", help="Exit non-zero on warnings")
    l.add_argument("--check-matches", action="store_true", help="Check each pattern matches at least one git-tracked file (can be slow)")
    l.add_argument("--check-overlaps", action="store_true", help="Scan repo for overlaps across services (slow)")
    l.set_defaults(func=cmd_lint)

    ini = sub.add_parser("init", help="Bootstrap a SERVICEOWNERS file from CODEOWNERS")
    ini.add_argument("--codeowners", default=None, help="Path to CODEOWNERS (default: search common locations)")
    ini.add_argument("--write", action="store_true", help="Write SERVICEOWNERS to disk (otherwise print to stdout)")
    ini.add_argument("--force", action="store_true", help="Overwrite existing SERVICEOWNERS when --write")
    ini.set_defaults(func=cmd_init)

    a = sub.add_parser("action", help="(internal) run inside GitHub Actions")
    a.add_argument("--diff", default=None, help="Override diff range (default: from GitHub event)")
    a.add_argument("--comment", default="true", help="true/false - comment on PR")
    a.add_argument("--fail-on-unmapped", default="true", help="true/false - fail if unmapped files exist")
    a.add_argument("--strict-lint", default="false", help="true/false - treat lint warnings as errors")
    a.set_defaults(func=cmd_action)

    return p


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()

    try:
        args = parser.parse_args(argv)
        rc = args.func(args)
    except UsageError as e:
        print(f"error: {e}", file=sys.stderr)
        rc = 2
    except ParseError as e:
        print(f"parse error: {e}", file=sys.stderr)
        rc = 2
    except GitError as e:
        print(f"git error: {e}", file=sys.stderr)
        rc = 2
    except KeyboardInterrupt:
        rc = 130

    raise SystemExit(rc)
