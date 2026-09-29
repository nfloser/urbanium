"""Canonical city, capability and source metadata contracts."""

from enum import StrEnum
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]


class CapabilitySupport(StrEnum):
    """Static deployment support, intentionally separate from runtime health."""

    CONFIGURED = "configured"
    CANDIDATE = "candidate"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class SourceStatus(StrEnum):
    """Whether a source boundary is verified for the current deployment."""

    VERIFIED = "verified"
    CANDIDATE = "candidate"


class SourceAuthority(StrEnum):
    """Authority classification for the provider within the documented scope."""

    AUTHORITATIVE = "authoritative"
    NON_AUTHORITATIVE = "non_authoritative"
    UNKNOWN = "unknown"


class RedistributionStatus(StrEnum):
    """Conservative redistribution classification for source data."""

    PERMITTED = "permitted"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


class LicenseMetadata(BaseModel):
    """Licence/terms metadata retained at the external-source boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identifier: str | None = None
    terms_url: HttpUrl | None = None
    redistribution: RedistributionStatus = RedistributionStatus.UNKNOWN
    notes: str | None = None

    @model_validator(mode="after")
    def require_some_licence_metadata(self) -> "LicenseMetadata":
        if not (self.identifier or self.terms_url or self.notes):
            raise ValueError("licence metadata requires identifier, terms_url or notes")
        return self


class CapabilityDefinition(BaseModel):
    """A capability declared by a city deployment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Identifier
    support: CapabilitySupport
    notes: str | None = None


class SourceDefinition(BaseModel):
    """Metadata for one external source boundary used or evaluated by a city."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Identifier
    provider: str = Field(min_length=1)
    domain: Identifier
    protocol: str = Field(min_length=1)
    status: SourceStatus
    authority: SourceAuthority = SourceAuthority.UNKNOWN
    capabilities: tuple[Identifier, ...]
    endpoint: AnyUrl | None = None
    update_frequency: str | None = None
    license: LicenseMetadata
    notes: str | None = None


class CityDefinition(BaseModel):
    """Versioned static configuration contract for one Urbanium city deployment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"]
    id: Identifier
    name: str = Field(min_length=1)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    timezone: str
    capabilities: tuple[CapabilityDefinition, ...]
    sources: tuple[SourceDefinition, ...]

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone '{value}'") from exc
        return value

    @model_validator(mode="after")
    def validate_references(self) -> "CityDefinition":
        capability_ids = [capability.id for capability in self.capabilities]
        source_ids = [source.id for source in self.sources]

        duplicate_capabilities = _duplicates(capability_ids)
        if duplicate_capabilities:
            raise ValueError(f"duplicate capability ids: {', '.join(duplicate_capabilities)}")

        duplicate_sources = _duplicates(source_ids)
        if duplicate_sources:
            raise ValueError(f"duplicate source ids: {', '.join(duplicate_sources)}")

        known_capabilities = set(capability_ids)
        for source in self.sources:
            unknown = sorted(set(source.capabilities) - known_capabilities)
            if unknown:
                raise ValueError(
                    f"source '{source.id}' references unknown capabilities: {', '.join(unknown)}"
                )

        for capability in self.capabilities:
            matching_sources = [
                source for source in self.sources if capability.id in source.capabilities
            ]
            if capability.support is CapabilitySupport.CONFIGURED and not any(
                source.status is SourceStatus.VERIFIED for source in matching_sources
            ):
                raise ValueError(
                    f"configured capability '{capability.id}' requires at least one verified source"
                )
            if capability.support is CapabilitySupport.UNAVAILABLE and matching_sources:
                raise ValueError(
                    f"unavailable capability '{capability.id}' must not reference sources"
                )

        return self


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)
