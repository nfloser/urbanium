"""Stable response contracts for the Urbanium v1 machine API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from urbanium.core.city import CapabilityDefinition, CityDefinition, Identifier, SourceDefinition
from urbanium.core.provider import ProviderResult

API_VERSION: Literal["1"] = "1"
API_SEMVER = "1.0.0"


class ApiProblem(BaseModel):
    """Machine-readable API problem without framework-specific wrapping."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    api_version: Literal["1"] = API_VERSION
    code: Identifier
    message: str


class CitiesResponse(BaseModel):
    """Versioned city discovery response."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    api_version: Literal["1"] = API_VERSION
    cities: tuple[CityDefinition, ...]


class CityResponse(BaseModel):
    """One validated city deployment definition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    api_version: Literal["1"] = API_VERSION
    city: CityDefinition


class CapabilitiesResponse(BaseModel):
    """Capabilities declared by one city deployment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    api_version: Literal["1"] = API_VERSION
    city_id: Identifier
    capabilities: tuple[CapabilityDefinition, ...]


class SourcesResponse(BaseModel):
    """Sources declared by one city deployment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    api_version: Literal["1"] = API_VERSION
    city_id: Identifier
    sources: tuple[SourceDefinition, ...]


class ObservationReadResponse(BaseModel):
    """Canonical provider read exposed through the versioned API."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    api_version: Literal["1"] = API_VERSION
    city_id: Identifier
    source_id: Identifier
    capability_id: Identifier
    result: ProviderResult
