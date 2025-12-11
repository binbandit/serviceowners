from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .impact import ImpactReport
from .lint import LintResult
from .services_file import Service


def _md_link(label: str, target: str) -> str:
    # GitHub-flavored markdown supports relative links in repo contexts.
    return f"[{label}]({target})"


def _owners_line(svc: Service) -> str:
    if not svc.owners:
        return ""
    owners = [o.display() for o in svc.owners if o.display()]
    if not owners:
        return ""
    return ", ".join(owners)


def render_impact_markdown(
    report: ImpactReport,
    *,
    services: Mapping[str, Service] | None = None,
    title: str = "ServiceOwners",
    include_files: bool = False,
    max_files_per_service: int = 50,
    include_unmapped: bool = True,
    show_metadata: bool = True,
) -> str:
    services = services or {}

    lines: list[str] = []
    lines.append(f"## {title}")
    lines.append("")

    if not report.services_to_files and not report.unmapped_files:
        lines.append("_No changed files detected._")
        return "\n".join(lines)

    # Impacted services
    impacted = sorted(report.services_to_files.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    lines.append(f"### Impacted services ({len(impacted)})")
    lines.append("")

    for name, files in impacted:
        count = len(files)
        meta = services.get(name)

        bits: list[str] = [f"**{name}**", f"({count} file{'s' if count != 1 else ''})"]

        if show_metadata and meta is not None:
            owners = _owners_line(meta)
            if owners:
                bits.append(f"owners: {owners}")
            if meta.contact and meta.contact.slack:
                bits.append(f"slack: `{meta.contact.slack}`")
            if meta.oncall:
                bits.append(f"oncall: {meta.oncall}")
            if meta.runbook:
                bits.append(_md_link("runbook", meta.runbook))
            if meta.docs:
                bits.append(_md_link("docs", meta.docs))

        lines.append("- " + " — ".join(bits))

        if include_files:
            shown = files[:max_files_per_service]
            for f in shown:
                lines.append(f"  - `{f}`")
            if len(files) > len(shown):
                lines.append(f"  - _…and {len(files) - len(shown)} more_")

    lines.append("")

    if include_unmapped and report.unmapped_files:
        lines.append(f"### Unmapped files ({len(report.unmapped_files)})")
        lines.append("")
        for f in report.unmapped_files[:max_files_per_service]:
            lines.append(f"- `{f}`")
        if len(report.unmapped_files) > max_files_per_service:
            lines.append(f"- _…and {len(report.unmapped_files) - max_files_per_service} more_")
        lines.append("")

    return "\n".join(lines)


def render_impact_comment(
    report: ImpactReport,
    *,
    services: Mapping[str, Service] | None = None,
    marker: str = "serviceowners",
    title: str = "🧭 ServiceOwners",
) -> str:
    """PR-comment friendly markdown (compact + collapsible)."""
    services = services or {}
    begin = f"<!-- {marker}:begin -->"
    end = f"<!-- {marker}:end -->"

    lines: list[str] = [begin, f"## {title}", ""]

    impacted = sorted(report.services_to_files.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    lines.append(f"**Impacted services:** {len(impacted)}")
    lines.append("")

    if impacted:
        for name, files in impacted:
            meta = services.get(name)
            bits: list[str] = [f"**{name}**", f"{len(files)} file{'s' if len(files)!=1 else ''}"]
            if meta is not None:
                owners = _owners_line(meta)
                if owners:
                    bits.append(f"owners: {owners}")
                if meta.contact and meta.contact.slack:
                    bits.append(f"slack: `{meta.contact.slack}`")
            lines.append("- " + " — ".join(bits))
    else:
        lines.append("_None_")

    lines.append("")

    if report.unmapped_files:
        lines.append(f"**Unmapped files:** {len(report.unmapped_files)} ⚠️")
        lines.append("")
        # show first few directly
        for f in report.unmapped_files[:10]:
            lines.append(f"- `{f}`")
        if len(report.unmapped_files) > 10:
            lines.append(f"- _…and {len(report.unmapped_files) - 10} more_")
        lines.append("")

    # Collapsible details
    lines.append("<details>")
    lines.append("<summary>Changed files by service</summary>")
    lines.append("")
    if impacted:
        for name, files in impacted:
            lines.append(f"### {name}")
            shown = files[:50]
            for f in shown:
                lines.append(f"- `{f}`")
            if len(files) > len(shown):
                lines.append(f"- _…and {len(files) - len(shown)} more_")
            lines.append("")
    else:
        lines.append("_No mapped services._")
        lines.append("")
    lines.append("</details>")
    lines.append("")
    lines.append(end)

    return "\n".join(lines)


def render_lint_markdown(result: LintResult, *, title: str = "Lint") -> str:
    if not result.issues:
        return f"### {title}\n\n✅ No lint issues found.\n"

    lines: list[str] = [f"### {title}", ""]
    for iss in result.issues:
        loc = ""
        if iss.file and iss.line:
            loc = f"{iss.file}:{iss.line}: "
        hint = f" _(hint: {iss.hint})_" if iss.hint else ""
        icon = "❌" if iss.severity == "ERROR" else "⚠️"
        lines.append(f"- {icon} **{iss.code}**: {loc}{iss.message}{hint}")
    lines.append("")
    return "\n".join(lines)
