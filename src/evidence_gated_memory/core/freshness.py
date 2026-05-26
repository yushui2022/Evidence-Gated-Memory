"""Freshness engine — the heart of EGM.

Three-state per evidence:
  - FRESH    : safe to use directly
  - STALE    : usable, but prompt context must flag it (⚠)
  - EXPIRED  : hard-blocked, must reverify before any high-stakes claim

TTLs come from the domain schema (per evidence_type), with per-evidence overrides.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from evidence_gated_memory.core.models import Evidence, Freshness
from evidence_gated_memory.schemas.loader import DomainSchema


def freshness_of(
    evidence: Evidence,
    schema: DomainSchema,
    now: Optional[datetime] = None,
) -> Freshness:
    """Classify an Evidence as fresh / stale / expired / unknown."""
    now = now or datetime.now(timezone.utc)

    if evidence.revoked_at and evidence.revoked_at <= now:
        return Freshness.EXPIRED

    # Per-evidence overrides take precedence over schema defaults.
    stale_after = evidence.stale_after_seconds
    expired_after = evidence.expired_after_seconds

    if stale_after is None or expired_after is None:
        type_def = schema.evidence_type(evidence.evidence_type)
        if type_def is not None:
            if stale_after is None:
                stale_after = type_def.stale_after_seconds
            if expired_after is None:
                expired_after = type_def.expired_after_seconds

    if stale_after is None and expired_after is None:
        return Freshness.UNKNOWN

    age = (now - evidence.observed_at).total_seconds()

    if expired_after is not None and age >= expired_after:
        return Freshness.EXPIRED
    if stale_after is not None and age >= stale_after:
        return Freshness.STALE
    return Freshness.FRESH


def is_usable(freshness: Freshness, required: str = "fresh") -> bool:
    """Whether a freshness state satisfies a gate's `require_freshness` setting."""
    if required == "any":
        return freshness != Freshness.EXPIRED
    if required == "stale":
        return freshness in (Freshness.FRESH, Freshness.STALE, Freshness.UNKNOWN)
    # default: fresh
    return freshness in (Freshness.FRESH, Freshness.UNKNOWN)
