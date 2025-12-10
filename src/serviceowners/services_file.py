from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from .errors import ParseError


@dataclass(frozen=True)
class OwnerRef:
    team: str | None = None
    user: str | None = None
    email: str | None = None

    @staticmethod
    def from_obj(obj: Any, *, source: str) -> "OwnerRef":
        if isinstance(obj, str):
            # Allow simple strings like "@org/team" or "user@example.com"
            if "@" in obj and "." in obj and " " not in obj and not obj.startswith("@"):
                return OwnerRef(email=obj)
            if obj.startswith("@"):
                return OwnerRef(team=obj)
            return OwnerRef(user=obj)

        if not isinstance(obj, Mapping):
            raise ParseError(f"{source}: owners entries must be strings or mappings, got {type(obj).__name__}")

        team = obj.get("team")
        user = obj.get("user")
        email = obj.get("email")
        if not any([team, user, email]):
            raise ParseError(f"{source}: owners entry must include one of: team/user/email")
        return OwnerRef(team=team, user=user, email=email)

    def display(self) -> str:
        return self.team or self.user or self.email or ""


@dataclass(frozen=True)
class Contact:
    slack: str | None = None
    email: str | None = None

    @staticmethod
    def from_obj(obj: Any, *, source: str) -> "Contact":
        if obj is None:
            return Contact()
        if not isinstance(obj, Mapping):
            raise ParseError(f"{source}: contact must be a mapping")
        return Contact(slack=obj.get("slack"), email=obj.get("email"))


@dataclass(frozen=True)
class Service:
    name: str
    description: str | None = None
    owners: list[OwnerRef] = field(default_factory=list)
    contact: Contact = field(default_factory=Contact)
    docs: str | None = None
    runbook: str | None = None
    oncall: str | None = None
    dashboards: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def _ensure_str_list(value: Any, *, source: str, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ParseError(f"{source}: '{field_name}' must be a list of strings")
    return value


def parse_services_obj(data: Any, *, source: str) -> dict[str, Service]:
    if data is None:
        return {}

    if not isinstance(data, Mapping):
        raise ParseError(f"{source}: expected a mapping")

    # Accept either:
    # - {services: {api: {...}}}
    # - {api: {...}, web: {...}}
    if "services" in data and isinstance(data.get("services"), Mapping):
        services_map = data["services"]
    else:
        services_map = data

    if not isinstance(services_map, Mapping):
        raise ParseError(f"{source}: services must be a mapping")

    services: dict[str, Service] = {}
    for name, raw in services_map.items():
        if not isinstance(name, str) or not name.strip():
            raise ParseError(f"{source}: service keys must be non-empty strings")
        if raw is None:
            raw = {}
        if not isinstance(raw, Mapping):
            raise ParseError(f"{source}: service '{name}' must be a mapping")

        owners_raw = raw.get("owners") or []
        if not isinstance(owners_raw, list):
            raise ParseError(f"{source}: service '{name}': owners must be a list")

        owners = [OwnerRef.from_obj(o, source=f"{source}:service:{name}") for o in owners_raw]
        contact = Contact.from_obj(raw.get("contact"), source=f"{source}:service:{name}")

        services[name] = Service(
            name=name,
            description=raw.get("description"),
            owners=owners,
            contact=contact,
            docs=raw.get("docs"),
            runbook=raw.get("runbook"),
            oncall=raw.get("oncall"),
            dashboards=_ensure_str_list(raw.get("dashboards"), source=source, field_name=f"{name}.dashboards"),
            tags=_ensure_str_list(raw.get("tags"), source=source, field_name=f"{name}.tags"),
        )

    return services


def load_services(path: Path) -> dict[str, Service]:
    if not path.exists():
        return {}
    try:
        obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ParseError(f"Failed to parse services file {path}: {e}") from e
    return parse_services_obj(obj, source=str(path))
