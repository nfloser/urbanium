"""City-independent contracts for providers of numeric observations."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from urbanium.core.city import CapabilitySupport, CityDefinition, Identifier, SourceStatus


class Availability(StrEnum):
    """Whether a provider returned usable observations in this read."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class Freshness(StrEnum):
    """Product-specific assessment of the returned observations' age."""

    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class ProviderErrorCode(StrEnum):
    """Stable error categories; diagnostics remain provider-specific text."""

    TIMEOUT = "timeout"
    UNAUTHORIZED = "unauthorized"
    INVALID_RESPONSE = "invalid_response"
    UPSTREAM = "upstream"
    UNKNOWN = "unknown"


class ProviderDescriptor(BaseModel):
    """Binding of one adapter instance to one city source and capability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    city_id: Identifier
    source_id: Identifier
    capability_id: Identifier
    adapter_version: str = Field(min_length=1)


class Observation(BaseModel):
    """Normalized numeric observation with source and temporal provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    city_id: Identifier
    source_id: Identifier
    capability_id: Identifier
    entity_id: Identifier
    quantity_id: Identifier
    value: Decimal
    unit: str = Field(min_length=1)
    observed_at: datetime
    received_at: datetime

    @model_validator(mode="after")
    def validate_time(self) -> "Observation":
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.received_at.tzinfo is None or self.received_at.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")
        if self.received_at < self.observed_at:
            raise ValueError("received_at must not precede observed_at")
        return self


class ProviderError(BaseModel):
    """Categorized read failure without exposing raw provider payloads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: ProviderErrorCode
    message: str = Field(min_length=1)


class ProviderResult(BaseModel):
    """Outcome of one read; unavailable results never masquerade as cached data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    availability: Availability
    freshness: Freshness
    observations: tuple[Observation, ...] = ()
    error: ProviderError | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "ProviderResult":
        if self.availability is Availability.AVAILABLE and (
            not self.observations or self.error is not None
        ):
            raise ValueError("available result requires observations and no error")
        if self.availability is Availability.DEGRADED and (
            not self.observations or self.error is None
        ):
            raise ValueError("degraded result requires observations and an error")
        if self.availability is Availability.UNAVAILABLE and (
            self.observations or self.error is None or self.freshness is not Freshness.UNKNOWN
        ):
            raise ValueError(
                "unavailable result requires no observations, an error and unknown freshness"
            )
        return self


class ObservationProvider(Protocol):
    """Adapter boundary; implementations normalize before returning."""

    @property
    def descriptor(self) -> ProviderDescriptor: ...

    def read(self) -> ProviderResult: ...


def validate_provider_result(descriptor: ProviderDescriptor, result: ProviderResult) -> None:
    """Reject observations that do not belong to the declared binding."""

    for item in result.observations:
        if (
            item.city_id != descriptor.city_id
            or item.source_id != descriptor.source_id
            or item.capability_id != descriptor.capability_id
        ):
            raise ValueError("observation does not match provider descriptor")


def validate_provider_descriptor(city: CityDefinition, descriptor: ProviderDescriptor) -> None:
    """Ensure an adapter binds only to a configured, verified source capability."""

    if city.id != descriptor.city_id:
        raise ValueError("provider descriptor does not match city")
    if not any(
        capability.id == descriptor.capability_id
        and capability.support is CapabilitySupport.CONFIGURED
        for capability in city.capabilities
    ):
        raise ValueError("provider capability is not configured for city")
    if not any(
        source.id == descriptor.source_id
        and source.status is SourceStatus.VERIFIED
        and descriptor.capability_id in source.capabilities
        for source in city.sources
    ):
        raise ValueError("provider source is not verified for capability")
