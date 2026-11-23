"""Sourced WGS84 entity points; no implicit footprint or spatial relationship."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from urbanium.core.entity import EntityReference, EvidenceReference, StateCategory
from urbanium.core.geometry import CityArea, Wgs84Point, distance_km

__all__ = ["CityArea", "EntityPointLocation", "Wgs84Point", "distance_km"]


class EntityPointLocation(BaseModel):
    """An evidenced point assertion about an entity at a stated instant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity: EntityReference
    point: Wgs84Point
    state_category: StateCategory
    asserted_at: datetime
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_provenance(self) -> "EntityPointLocation":
        if self.asserted_at.tzinfo is None or self.asserted_at.utcoffset() is None:
            raise ValueError("asserted_at must be timezone-aware")
        if any(item.city_id != self.entity.city_id for item in self.evidence):
            raise ValueError("evidence city must match entity city")
        if any(item.retrieved_at > self.asserted_at for item in self.evidence):
            raise ValueError("evidence retrieval must not postdate location assertion")
        keys = [(item.city_id, item.source_id, item.record_id) for item in self.evidence]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate evidence reference")
        return self
