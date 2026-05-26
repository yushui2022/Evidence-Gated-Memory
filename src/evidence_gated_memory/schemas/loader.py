"""Domain schema: declarative business rules driving gates and freshness."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field


# ISO-8601-ish duration parser (PT5M, PT1H, P30D, P1Y) — enough for v0.1.
_DURATION_RE = re.compile(
    r"^P"
    r"(?:(?P<years>\d+)Y)?"
    r"(?:(?P<months>\d+)M)?"
    r"(?:(?P<days>\d+)D)?"
    r"(?:T"
    r"(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+)S)?"
    r")?$"
)


def parse_duration_seconds(value: Optional[str]) -> Optional[int]:
    """Parse an ISO-8601 duration into seconds. Treats months=30d, years=365d."""
    if value is None:
        return None
    m = _DURATION_RE.match(value.strip())
    if not m:
        raise ValueError(f"invalid duration: {value!r}")
    parts = {k: int(v) if v else 0 for k, v in m.groupdict().items()}
    total = (
        parts["years"] * 365 * 86400
        + parts["months"] * 30 * 86400
        + parts["days"] * 86400
        + parts["hours"] * 3600
        + parts["minutes"] * 60
        + parts["seconds"]
    )
    return total


class EntityDef(BaseModel):
    name: str
    patterns: list[str] = Field(default_factory=list)
    metadata_fields: list[str] = Field(default_factory=list)
    llm_fallback: bool = False


class EvidenceTypeDef(BaseModel):
    name: str
    stale_after: Optional[str] = None       # ISO-8601 duration
    expired_after: Optional[str] = None
    source_systems: list[str] = Field(default_factory=list)
    risk: str = "medium"

    @property
    def stale_after_seconds(self) -> Optional[int]:
        return parse_duration_seconds(self.stale_after)

    @property
    def expired_after_seconds(self) -> Optional[int]:
        return parse_duration_seconds(self.expired_after)


class ClaimTypeDef(BaseModel):
    name: str
    required_evidence: list[str] = Field(default_factory=list)
    requires_fresh_evidence: bool = False
    description: str = ""


class GateRule(BaseModel):
    """Declarative gate rule. v0.1 supports a small but useful set of conditions."""

    name: str
    when_claim_type: Optional[str] = None
    require_evidence_types: list[str] = Field(default_factory=list)
    require_freshness: str = "fresh"       # "fresh" | "stale" | "any"
    suggested_action: Optional[str] = None


class DomainSchema(BaseModel):
    name: str
    description: str = ""
    entities: list[EntityDef] = Field(default_factory=list)
    evidence_types: list[EvidenceTypeDef] = Field(default_factory=list)
    claim_types: list[ClaimTypeDef] = Field(default_factory=list)
    gates: list[GateRule] = Field(default_factory=list)

    def evidence_type(self, name: str) -> Optional[EvidenceTypeDef]:
        for et in self.evidence_types:
            if et.name == name:
                return et
        return None

    def claim_type(self, name: str) -> Optional[ClaimTypeDef]:
        for ct in self.claim_types:
            if ct.name == name:
                return ct
        return None


def load_schema(path: str | Path) -> DomainSchema:
    """Load a domain schema from a YAML file."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return _from_raw(raw)


def load_schema_dict(raw: dict[str, Any]) -> DomainSchema:
    return _from_raw(raw)


def _from_raw(raw: dict[str, Any]) -> DomainSchema:
    """Convert raw YAML dict (with `evidence_types: {name: {...}}` shorthand) into DomainSchema."""

    def _listify(section: Any, key: str = "name") -> list[dict]:
        if section is None:
            return []
        if isinstance(section, list):
            return section
        # dict-of-dicts shorthand: {order_record: {ttl: PT5M}} → [{name: order_record, ...}]
        out = []
        for k, v in section.items():
            item = dict(v or {})
            item[key] = k
            out.append(item)
        return out

    return DomainSchema(
        name=raw.get("name", "unnamed"),
        description=raw.get("description", ""),
        entities=[EntityDef(**e) for e in _listify(raw.get("entities"))],
        evidence_types=[EvidenceTypeDef(**e) for e in _listify(raw.get("evidence_types"))],
        claim_types=[ClaimTypeDef(**c) for c in _listify(raw.get("claim_types"))],
        gates=[
            GateRule(
                name=g["name"],
                when_claim_type=(g.get("when") or {}).get("claim_type"),
                require_evidence_types=(g.get("require") or {}).get("evidence_types", []),
                require_freshness=(g.get("require") or {}).get("freshness", "fresh"),
                suggested_action=g.get("suggested_action"),
            )
            for g in raw.get("gates", [])
        ],
    )
