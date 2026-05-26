"""Entity extraction for evidence metadata.

Extraction is deliberately provenance-labeled:

1. explicit metadata fields from the caller
2. schema regex patterns over evidence content
3. optional LLM fallback supplied by the host application

LLM fallback output is only an annotation for indexing/search. It is not an
acceptable fact source.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any, Optional, Union

from pydantic import BaseModel

from evidence_gated_memory.schemas.loader import DomainSchema, EntityDef


class ExtractedEntity(BaseModel):
    entity_type: str
    value: str
    source: str
    field: Optional[str] = None
    pattern: Optional[str] = None


FallbackValue = Union[str, dict[str, Any], ExtractedEntity]
EntityFallback = Callable[[str, EntityDef, dict[str, Any]], Iterable[FallbackValue]]


def extract_entities(
    content: str,
    metadata: Optional[dict[str, Any]],
    schema: DomainSchema,
    llm_fallback: Optional[EntityFallback] = None,
) -> list[ExtractedEntity]:
    """Extract entities using metadata, regex, then optional LLM fallback."""
    metadata = metadata or {}
    entities: list[ExtractedEntity] = []
    seen: set[tuple[str, str]] = set()

    def add(entity: ExtractedEntity) -> None:
        key = (entity.entity_type, entity.value)
        if not entity.value or key in seen:
            return
        seen.add(key)
        entities.append(entity)

    for entity_def in schema.entities:
        for field in entity_def.metadata_fields:
            if field not in metadata:
                continue
            values = metadata[field]
            if not isinstance(values, (list, tuple, set)):
                values = [values]
            for value in values:
                add(ExtractedEntity(
                    entity_type=entity_def.name,
                    value=str(value),
                    source="metadata",
                    field=field,
                ))

        for pattern in entity_def.patterns:
            try:
                regex = re.compile(pattern)
            except re.error:
                continue
            for match in regex.finditer(content):
                value = match.group(1) if match.groups() else match.group(0)
                add(ExtractedEntity(
                    entity_type=entity_def.name,
                    value=value,
                    source="regex",
                    pattern=pattern,
                ))

        if llm_fallback is None or not entity_def.llm_fallback:
            continue
        if any(e.entity_type == entity_def.name for e in entities):
            continue
        for raw in llm_fallback(content, entity_def, metadata):
            entity = _coerce_fallback_value(raw, entity_def.name)
            if entity is not None:
                add(entity)

    return entities


def _coerce_fallback_value(raw: FallbackValue, entity_type: str) -> Optional[ExtractedEntity]:
    if isinstance(raw, ExtractedEntity):
        return raw.model_copy(update={"source": raw.source or "llm_fallback"})
    if isinstance(raw, str):
        return ExtractedEntity(entity_type=entity_type, value=raw, source="llm_fallback")
    if isinstance(raw, dict):
        value = raw.get("value")
        if value is None:
            return None
        return ExtractedEntity(
            entity_type=str(raw.get("entity_type", entity_type)),
            value=str(value),
            source=str(raw.get("source", "llm_fallback")),
            field=raw.get("field"),
            pattern=raw.get("pattern"),
        )
    return None
