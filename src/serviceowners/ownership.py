from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .serviceowners_file import Rule


@dataclass(frozen=True)
class Match:
    path: str
    chosen: Rule | None
    matches: list[Rule]

    @property
    def service(self) -> str | None:
        return self.chosen.service if self.chosen else None


class OwnershipIndex:
    """In-memory index for SERVICEOWNERS rules."""

    def __init__(self, rules: Iterable[Rule]):
        self._rules = list(rules)

    @property
    def rules(self) -> list[Rule]:
        return list(self._rules)

    def match(self, path: str) -> Match:
        matches: list[Rule] = []
        for r in self._rules:
            if r.compiled.matches(path):
                matches.append(r)
        chosen = matches[-1] if matches else None
        return Match(path=path, chosen=chosen, matches=matches)
