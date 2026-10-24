"""The provider-to-component handoff must preserve evidence, not just numeric values."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from urbanium.analysis.observation_inputs import observation_input
from urbanium.core.entity import EntityReference
from urbanium.core.provider import (
    Availability,
    Freshness,
    Observation,
    ProviderDescriptor,
    ProviderError,
    ProviderErrorCode,
    ProviderResult,
)
from urbanium.registry import CityRegistry

CITIES = Path(__file__).resolve().parents[1] / "cities"
OBSERVED = datetime(2026, 10, 24, 9, 10, tzinfo=UTC)
RECEIVED = datetime(2026, 10, 24, 9, 12, tzinfo=UTC)


def weather_observation() -> Observation:
    return Observation(
        city_id="berlin",
        source_id="dwd_open_data",
        capability_id="weather",
        entity=EntityReference(
            city_id="berlin",
            entity_type="weather_station",
            entity_id="berlin_tempelhof",
        ),
        quantity_id="air_temperature",
        value=Decimal("0.00"),
        unit="Cel",
        observed_at=OBSERVED,
        received_at=RECEIVED,
        quality_scheme="dwd_quality",
        quality_code="1",
    )


def weather_descriptor() -> ProviderDescriptor:
    return ProviderDescriptor(
        city_id="berlin",
        source_id="dwd_open_data",
        capability_id="weather",
        adapter_version="1.0.0",
    )


def test_available_read_preserves_exact_observation_evidence_and_contract_version() -> None:
    city = CityRegistry.from_directory(CITIES).city("berlin")
    result = ProviderResult(
        availability=Availability.AVAILABLE,
        freshness=Freshness.FRESH,
        observations=(weather_observation(),),
    )

    capability_input = observation_input(city, weather_descriptor(), result, prepared_at=RECEIVED)

    assert capability_input.capability_id == "weather"
    assert capability_input.version == "1"
    assert capability_input.payload["prepared_at"] == RECEIVED.isoformat().replace("+00:00", "Z")
    assert capability_input.payload["provider"] == weather_descriptor().model_dump(mode="json")
    read = capability_input.payload["read"]
    assert read["availability"] == "available"
    assert read["freshness"] == "fresh"
    assert read["error"] is None
    assert len(read["observations"]) == 1
    observation = read["observations"][0]
    assert observation["entity"]["entity_id"] == "berlin_tempelhof"
    assert observation["value"] == "0.00"
    assert observation["unit"] == "Cel"
    assert observation["observed_at"] == OBSERVED.isoformat().replace("+00:00", "Z")
    assert observation["received_at"] == RECEIVED.isoformat().replace("+00:00", "Z")
    assert observation["quality_scheme"] == "dwd_quality"
    assert observation["quality_code"] == "1"
    assert ProviderResult.model_validate(read) == result


def test_degraded_read_keeps_observations_and_typed_error() -> None:
    city = CityRegistry.from_directory(CITIES).city("berlin")
    result = ProviderResult(
        availability=Availability.DEGRADED,
        freshness=Freshness.UNKNOWN,
        observations=(weather_observation(),),
        error=ProviderError(
            code=ProviderErrorCode.INVALID_RESPONSE,
            message="upstream quality flag missing",
        ),
    )

    prepared = observation_input(city, weather_descriptor(), result, prepared_at=RECEIVED)
    read = prepared.payload["read"]

    assert read["availability"] == "degraded"
    assert read["freshness"] == "unknown"
    assert read["observations"][0]["value"] == "0.00"
    assert read["error"] == {
        "code": "invalid_response",
        "message": "upstream quality flag missing",
    }


def test_unavailable_read_is_not_turned_into_synthetic_observations() -> None:
    city = CityRegistry.from_directory(CITIES).city("berlin")
    result = ProviderResult(
        availability=Availability.UNAVAILABLE,
        freshness=Freshness.UNKNOWN,
        error=ProviderError(code=ProviderErrorCode.TIMEOUT, message="provider timed out"),
    )

    prepared = observation_input(city, weather_descriptor(), result, prepared_at=RECEIVED)
    read = prepared.payload["read"]

    assert read["availability"] == "unavailable"
    assert read["observations"] == []
    assert read["error"]["code"] == "timeout"


def test_version_is_taken_from_city_capability_contract() -> None:
    city = CityRegistry.from_directory(CITIES).city("berlin")
    changed = city.model_copy(
        update={
            "capabilities": tuple(
                capability.model_copy(update={"version": "2"})
                if capability.id == "weather"
                else capability
                for capability in city.capabilities
            )
        }
    )
    result = ProviderResult(
        availability=Availability.AVAILABLE,
        freshness=Freshness.FRESH,
        observations=(weather_observation(),),
    )

    prepared = observation_input(changed, weather_descriptor(), result, prepared_at=RECEIVED)
    assert prepared.version == "2"


@pytest.mark.parametrize(
    "descriptor",
    [
        ProviderDescriptor(
            city_id="mainz",
            source_id="dwd_open_data",
            capability_id="weather",
            adapter_version="1",
        ),
        ProviderDescriptor(
            city_id="berlin",
            source_id="unknown_source",
            capability_id="weather",
            adapter_version="1",
        ),
        ProviderDescriptor(
            city_id="berlin",
            source_id="vbb_gtfs_rt",
            capability_id="weather",
            adapter_version="1",
        ),
    ],
)
def test_unverified_or_incorrect_bindings_are_rejected(descriptor: ProviderDescriptor) -> None:
    city = CityRegistry.from_directory(CITIES).city("berlin")
    result = ProviderResult(
        availability=Availability.AVAILABLE,
        freshness=Freshness.FRESH,
        observations=(weather_observation(),),
    )

    with pytest.raises(ValueError, match="provider"):
        observation_input(city, descriptor, result, prepared_at=RECEIVED)


def test_observations_from_another_source_are_rejected() -> None:
    city = CityRegistry.from_directory(CITIES).city("berlin")
    wrong_observation = weather_observation().model_copy(update={"source_id": "vbb_gtfs_rt"})
    result = ProviderResult(
        availability=Availability.AVAILABLE,
        freshness=Freshness.FRESH,
        observations=(wrong_observation,),
    )

    with pytest.raises(ValueError, match="observation does not match provider descriptor"):
        observation_input(city, weather_descriptor(), result, prepared_at=RECEIVED)


def test_preparation_time_must_be_timezone_aware() -> None:
    city = CityRegistry.from_directory(CITIES).city("berlin")
    result = ProviderResult(
        availability=Availability.UNAVAILABLE,
        freshness=Freshness.UNKNOWN,
        error=ProviderError(code=ProviderErrorCode.TIMEOUT, message="provider timed out"),
    )

    with pytest.raises(ValueError, match="prepared_at must be timezone-aware"):
        observation_input(
            city,
            weather_descriptor(),
            result,
            prepared_at=datetime(2026, 10, 24, 9, 12),
        )


def test_same_handoff_accepts_transport_evidence_without_weather_assumptions() -> None:
    city = CityRegistry.from_directory(CITIES).city("berlin")
    descriptor = ProviderDescriptor(
        city_id="berlin",
        source_id="vbb_gtfs_rt",
        capability_id="realtime_transport",
        adapter_version="1.0.0",
    )
    result = ProviderResult(
        availability=Availability.AVAILABLE,
        freshness=Freshness.FRESH,
        observations=(
            Observation(
                city_id="berlin",
                source_id="vbb_gtfs_rt",
                capability_id="realtime_transport",
                entity=EntityReference(
                    city_id="berlin",
                    entity_type="transport_network",
                    entity_id="vbb_network",
                ),
                quantity_id="active_service_alerts",
                value=Decimal(0),
                unit="1",
                observed_at=OBSERVED,
                received_at=RECEIVED,
            ),
        ),
    )

    prepared = observation_input(city, descriptor, result, prepared_at=RECEIVED)

    assert prepared.capability_id == "realtime_transport"
    assert prepared.version == "1"
    assert prepared.payload["read"]["observations"][0]["value"] == "0"
