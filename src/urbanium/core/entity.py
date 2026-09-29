"""Storage-independent entity identity and relationship contracts."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from urbanium.core.city import Identifier


class StateCategory(StrEnum):
    """Canonical state categories that must not be mixed implicitly."""

    REFERENCE = "reference"
    LIVE = "live"
    HISTORICAL = "historical"
    FORECAST = "forecast"
    SCENARIO = "scenario"
    SIMULATED = "simulated"
    DERIVED = "derived"


class EntityReference(BaseModel):
    """Stable reference to one typed entity in a city deployment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    city_id: Identifier
    entity_type: Identifier
    entity_id: Identifier

    @property
    def canonical_id(self) -> str:
        """Return the deterministic cross-city identity used by projections."""

        return f"{self.city_id}:{self.entity_type}:{self.entity_id}"


class EvidenceReference(BaseModel):
    """Trace an assertion to one provider record or source artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    city_id: Identifier
    source_id: Identifier
    record_id: str = Field(min_length=1)
    retrieved_at: datetime

    @model_validator(mode="after")
    def validate_time(self) -> "EvidenceReference":
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return self


class RelationshipAssertion(BaseModel):
    """Evidence-backed directed relationship in canonical execution state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: EntityReference
    predicate: Identifier
    object: EntityReference
    state_category: StateCategory
    asserted_at: datetime
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)

    @property
    def canonical_id(self) -> str:
        """Return a deterministic identity for this directed semantic edge."""

        return f"{self.subject.canonical_id}:{self.predicate}:{self.object.canonical_id}"

    @model_validator(mode="after")
    def validate_assertion(self) -> "RelationshipAssertion":
        if self.asserted_at.tzinfo is None or self.asserted_at.utcoffset() is None:
            raise ValueError("asserted_at must be timezone-aware")
        if any(item.retrieved_at > self.asserted_at for item in self.evidence):
            raise ValueError("evidence retrieval must not postdate assertion")
        endpoint_cities = {self.subject.city_id, self.object.city_id}
        if any(item.city_id not in endpoint_cities for item in self.evidence):
            raise ValueError("evidence city must match a relationship endpoint city")

        evidence_keys = [(item.city_id, item.source_id, item.record_id) for item in self.evidence]
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("duplicate evidence reference")
        return self
