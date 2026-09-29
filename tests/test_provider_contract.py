from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from urbanium.core.entity import EntityReference
from urbanium.core.provider import (
    Availability,
    Freshness,
    Observation,
    ObservationProvider,
    ProviderDescriptor,
    ProviderError,
    ProviderErrorCode,
    ProviderResult,
    validate_provider_descriptor,
    validate_provider_result,
)
from urbanium.registry import load_city_definition

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)
DESCRIPTOR = ProviderDescriptor(
    city_id="mainz", source_id="dwd_open_data", capability_id="weather", adapter_version="1.0.0"
)
CITIES = Path(__file__).resolve().parents[1] / "cities"


def observation(**overrides: object) -> Observation:
    data: dict[str, object] = {
        "city_id": "mainz",
        "source_id": "dwd_open_data",
        "capability_id": "weather",
        "entity": EntityReference(
            city_id="mainz",
            entity_type="weather_station",
            entity_id="station_1",
        ),
        "quantity_id": "air_temperature",
        "value": Decimal("12.3"),
        "unit": "Cel",
        "observed_at": NOW,
        "received_at": NOW,
        "quality_scheme": "fixture_quality",
        "quality_code": "2",
    }
    data.update(overrides)
    return Observation.model_validate(data)


def test_available_result_can_be_stale_without_becoming_unavailable() -> None:
    result = ProviderResult(
        availability=Availability.AVAILABLE,
        freshness=Freshness.STALE,
        observations=(observation(),),
    )

    validate_provider_result(DESCRIPTOR, result)
    assert result.observations[0].value == Decimal("12.3")
    assert result.observations[0].quality_code == "2"


def test_adapter_contract_can_be_reused_for_a_provider_implementation() -> None:
    class FixtureProvider:
        descriptor = DESCRIPTOR

        def read(self) -> ProviderResult:
            return ProviderResult(
                availability=Availability.AVAILABLE,
                freshness=Freshness.FRESH,
                observations=(observation(),),
            )

    provider: ObservationProvider = FixtureProvider()
    validate_provider_descriptor(
        load_city_definition(CITIES / "mainz" / "city.yaml"), provider.descriptor
    )
    validate_provider_result(provider.descriptor, provider.read())


def test_adapter_cannot_bind_to_another_city_or_candidate_source() -> None:
    mainz = load_city_definition(CITIES / "mainz" / "city.yaml")
    berlin = load_city_definition(CITIES / "berlin" / "city.yaml")
    with pytest.raises(ValueError, match="does not match city"):
        validate_provider_descriptor(berlin, DESCRIPTOR)
    with pytest.raises(ValueError, match="not configured"):
        validate_provider_descriptor(
            mainz,
            ProviderDescriptor(
                city_id="mainz",
                source_id="mainz_webgis_2026",
                capability_id="open_data_catalog",
                adapter_version="1.0.0",
            ),
        )
    with pytest.raises(ValueError, match="not verified"):
        validate_provider_descriptor(
            mainz,
            ProviderDescriptor(
                city_id="mainz",
                source_id="mainz_webgis_2026",
                capability_id="weather",
                adapter_version="1.0.0",
            ),
        )


def test_unavailable_result_has_typed_error_and_no_observations() -> None:
    result = ProviderResult(
        availability=Availability.UNAVAILABLE,
        freshness=Freshness.UNKNOWN,
        error=ProviderError(code=ProviderErrorCode.TIMEOUT, message="upstream timed out"),
    )

    validate_provider_result(DESCRIPTOR, result)


def test_partial_result_is_explicitly_degraded() -> None:
    result = ProviderResult(
        availability=Availability.DEGRADED,
        freshness=Freshness.FRESH,
        observations=(observation(),),
        error=ProviderError(code=ProviderErrorCode.INVALID_RESPONSE, message="one record invalid"),
    )

    validate_provider_result(DESCRIPTOR, result)


@pytest.mark.parametrize(
    ("availability", "freshness", "records", "error"),
    [
        (Availability.AVAILABLE, Freshness.FRESH, (), None),
        (Availability.AVAILABLE, Freshness.FRESH, (observation(),), "error"),
        (Availability.DEGRADED, Freshness.FRESH, (observation(),), None),
        (Availability.UNAVAILABLE, Freshness.UNKNOWN, (observation(),), "error"),
        (Availability.UNAVAILABLE, Freshness.FRESH, (), "error"),
    ],
)
def test_inconsistent_result_is_rejected(
    availability: Availability,
    freshness: Freshness,
    records: tuple[Observation, ...],
    error: str | None,
) -> None:
    typed_error = ProviderError(code=ProviderErrorCode.UNKNOWN, message=error) if error else None
    with pytest.raises(ValidationError):
        ProviderResult(
            availability=availability,
            freshness=freshness,
            observations=records,
            error=typed_error,
        )


def test_result_cannot_claim_another_source_or_city() -> None:
    result = ProviderResult(
        availability=Availability.AVAILABLE,
        freshness=Freshness.FRESH,
        observations=(
            observation(
                city_id="berlin",
                entity=EntityReference(
                    city_id="berlin",
                    entity_type="weather_station",
                    entity_id="station_1",
                ),
            ),
        ),
    )
    with pytest.raises(ValueError, match="does not match provider descriptor"):
        validate_provider_result(DESCRIPTOR, result)


def test_observation_entity_must_belong_to_observation_city() -> None:
    with pytest.raises(ValidationError, match="entity city must match observation city"):
        observation(
            entity=EntityReference(
                city_id="berlin",
                entity_type="weather_station",
                entity_id="station_1",
            )
        )


def test_observation_rejects_naive_or_reverse_timestamps() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        observation(observed_at=datetime(2026, 9, 29, 12))
    with pytest.raises(ValidationError, match="received_at"):
        observation(received_at=datetime(2026, 9, 29, 11, tzinfo=UTC))


@pytest.mark.parametrize(
    "overrides",
    [
        {"quality_scheme": None},
        {"quality_code": None},
    ],
)
def test_observation_requires_complete_quality_provenance(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="quality_scheme and quality_code"):
        observation(**overrides)
