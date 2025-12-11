from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .ownership import Match, OwnershipIndex
from .paths import normalize_paths


@dataclass(frozen=True)
class ImpactReport:
    services_to_files: dict[str, list[str]] = field(default_factory=dict)
    unmapped_files: list[str] = field(default_factory=list)
    overlaps: dict[str, list[str]] = field(default_factory=dict)  # path -> services matched (order)

    def impacted_services(self) -> list[str]:
        return sorted(self.services_to_files.keys())

    def file_count_for(self, service: str) -> int:
        return len(self.services_to_files.get(service, []))

    def total_files(self) -> int:
        return sum(len(v) for v in self.services_to_files.values()) + len(self.unmapped_files)


def compute_impact(index: OwnershipIndex, changed_files: Iterable[str]) -> ImpactReport:
    services_to_files: dict[str, list[str]] = {}
    unmapped: list[str] = []
    overlaps: dict[str, list[str]] = {}

    for path in changed_files:
        m: Match = index.match(path)
        if m.service is None:
            unmapped.append(path)
            continue
        services_to_files.setdefault(m.service, []).append(path)
        if len(m.matches) > 1:
            overlaps[path] = [r.service for r in m.matches]

    # Sort for stable output
    for svc, files in services_to_files.items():
        services_to_files[svc] = sorted(set(files))
    unmapped = sorted(set(unmapped))

    return ImpactReport(services_to_files=services_to_files, unmapped_files=unmapped, overlaps=overlaps)
