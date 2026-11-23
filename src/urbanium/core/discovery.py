"""City-independent contracts for discovering source entities inside a city area.

Discovery answers "which physical source entities (stations, gauges, …) does
this source publish inside the deployment's area?". It produces sourced
reference locations only. It does not read measurements and does not claim
that a discovered entity currently delivers data.
"""

from datetime import datetime
from enum import StrEnum
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from urbanium.core.city import CityDefinition, Identifier, SourceStatus
from urbanium.core.provider import ProviderError
from urbanium.core.spatial import EntityPointLocation

AttributeValue = str | int | float | bool


class DiscoveryStatus(StrEnum):
    """Whether the source inventory could be read for this discovery run."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class DiscoveredEntity(BaseModel):
    """One sourced entity with a reference location and display metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    location: EntityPointLocation
    label: str = Field(min_length=1)
    attributes: dict[Identifier, AttributeValue] = Field(default_factory=dict)


class DiscoveryResult(BaseModel):
    """Outcome of one discovery run for one city source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    city_id: Identifier
    source_id: Identifier
    status: DiscoveryStatus
    discovered_at: datetime
    entities: tuple[DiscoveredEntity, ...] = ()
    error: ProviderError | None = None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.discovered_at.tzinfo is None or self.discovered_at.utcoffset() is None:
            raise ValueError("discovered_at must be timezone-aware")
        if self.status is DiscoveryStatus.AVAILABLE and self.error is not None:
            raise ValueError("available discovery must not carry an error")
        if self.status is DiscoveryStatus.UNAVAILABLE and (self.entities or self.error is None):
            raise ValueError("unavailable discovery requires an error and no entities")
        identities = [item.location.entity.canonical_id for item in self.entities]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate discovered entity")
        if any(item.location.entity.city_id != self.city_id for item in self.entities):
            raise ValueError("entity city must match discovery city")
        return self


class SourceDiscovery(Protocol):
    """Adapter boundary for area-based discovery of one city source."""

    @property
    def city_id(self) -> str: ...

    @property
    def source_id(self) -> str: ...

    def discover(self, city: CityDefinition) -> DiscoveryResult: ...


def validate_discovery_result(city: CityDefinition, result: DiscoveryResult) -> None:
    """Reject discoveries that leave the declared area or cite a foreign source."""

    if result.city_id != city.id:
        raise ValueError("discovery result does not match city")
    if city.area is None:
        raise ValueError(f"city '{city.id}' declares no area for discovery")
    if not any(
        source.id == result.source_id and source.status is SourceStatus.VERIFIED
        for source in city.sources
    ):
        raise ValueError(f"'{result.source_id}' is not a verified source of city '{city.id}'")
    for item in result.entities:
        location = item.location
        if not city.area.search_envelope.contains(location.point):
            raise ValueError(f"entity '{location.entity.canonical_id}' lies outside the city area")
        if any(evidence.source_id != result.source_id for evidence in location.evidence):
            raise ValueError(
                f"entity '{location.entity.canonical_id}' cites a different evidence source"
            )
