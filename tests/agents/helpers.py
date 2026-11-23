"""Builders for agent tests; values are illustrative, not real measurements."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from urbanium.analysis.observation_inputs import observation_input
from urbanium.core.entity import EntityReference
from urbanium.core.execution import CapabilityInput
from urbanium.core.provider import (
    Availability,
    Freshness,
    Observation,
    ProviderDescriptor,
    ProviderError,
    ProviderErrorCode,
    ProviderResult,
)
from urbanium.registry import load_city_definition

ROOT = Path(__file__).resolve().parents[2]
BERLIN = load_city_definition(ROOT / "cities" / "berlin" / "city.yaml")
NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)

WEATHER = ProviderDescriptor(
    city_id="berlin", source_id="dwd_open_data", capability_id="weather", adapter_version="1.0.0"
)
RIVER = ProviderDescriptor(
    city_id="berlin", source_id="pegelonline", capability_id="river_level", adapter_version="1.0.0"
)


def observation(
    descriptor: ProviderDescriptor,
    entity_id: str,
    value: str,
    minutes_ago: int,
) -> Observation:
    entity_type = "weather_station" if descriptor.capability_id == "weather" else "river_gauge"
    return Observation(
        city_id=descriptor.city_id,
        source_id=descriptor.source_id,
        capability_id=descriptor.capability_id,
        entity=EntityReference(city_id="berlin", entity_type=entity_type, entity_id=entity_id),
        quantity_id="air_temperature" if descriptor.capability_id == "weather" else "water_level",
        value=Decimal(value),
        unit="Cel" if descriptor.capability_id == "weather" else "cm",
        observed_at=NOW - timedelta(minutes=minutes_ago),
        received_at=NOW,
    )


def read(*observations: Observation, degraded: str | None = None) -> ProviderResult:
    if not observations:
        return ProviderResult(
            availability=Availability.UNAVAILABLE,
            freshness=Freshness.UNKNOWN,
            error=ProviderError(code=ProviderErrorCode.UPSTREAM, message="source down"),
        )
    if degraded:
        return ProviderResult(
            availability=Availability.DEGRADED,
            freshness=Freshness.FRESH,
            observations=observations,
            error=ProviderError(code=ProviderErrorCode.UPSTREAM, message=degraded),
        )
    return ProviderResult(
        availability=Availability.AVAILABLE, freshness=Freshness.FRESH, observations=observations
    )


def capability_input(descriptor: ProviderDescriptor, result: ProviderResult) -> CapabilityInput:
    return observation_input(BERLIN, descriptor, result, prepared_at=NOW)
