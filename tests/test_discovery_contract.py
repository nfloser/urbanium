"""Discovered entities must belong to the declared city, source and area."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from urbanium.core.city import CityDefinition
from urbanium.core.discovery import (
    DiscoveredEntity,
    DiscoveryResult,
    DiscoveryStatus,
    validate_discovery_result,
)
from urbanium.core.entity import EntityReference, EvidenceReference, StateCategory
from urbanium.core.provider import ProviderError, ProviderErrorCode
from urbanium.core.spatial import EntityPointLocation, Wgs84Point

NOW = datetime(2026, 11, 23, 9, tzinfo=UTC)


def city(*, with_area: bool = True) -> CityDefinition:
    raw: dict[str, object] = {
        "schema_version": "1",
        "id": "example",
        "name": "Example",
        "country_code": "DE",
        "timezone": "Europe/Berlin",
        "capabilities": [{"id": "weather", "support": "configured"}],
        "sources": [
            {
                "id": "station_network",
                "provider": "Example",
                "domain": "weather",
                "protocol": "https",
                "status": "verified",
                "capabilities": ["weather"],
                "license": {"notes": "Test fixture."},
            }
        ],
    }
    if with_area:
        raw["area"] = {"south": 50.0, "west": 8.0, "north": 50.2, "east": 8.4}
    return CityDefinition.model_validate(raw)


def entity(
    *,
    latitude: float = 50.1,
    city_id: str = "example",
    source_id: str = "station_network",
) -> DiscoveredEntity:
    reference = EntityReference(city_id=city_id, entity_type="weather_station", entity_id="s1")
    return DiscoveredEntity(
        location=EntityPointLocation(
            entity=reference,
            point=Wgs84Point(latitude=latitude, longitude=8.2),
            state_category=StateCategory.REFERENCE,
            asserted_at=NOW,
            evidence=(
                EvidenceReference(
                    city_id=city_id,
                    source_id=source_id,
                    record_id="inventory:s1",
                    retrieved_at=NOW,
                ),
            ),
        ),
        label="Station 1",
        attributes={"elevation_m": 110},
    )


def result(*entities: DiscoveredEntity) -> DiscoveryResult:
    return DiscoveryResult(
        city_id="example",
        source_id="station_network",
        status=DiscoveryStatus.AVAILABLE,
        discovered_at=NOW,
        entities=entities,
    )


def test_valid_discovery_inside_the_area_is_accepted() -> None:
    validate_discovery_result(city(), result(entity()))


def test_empty_discovery_is_a_valid_explicit_finding() -> None:
    validate_discovery_result(city(), result())


@pytest.mark.parametrize(
    ("candidate", "message"),
    [
        (entity(latitude=51.0), "outside the city area"),
        (entity(source_id="other"), "evidence source"),
    ],
)
def test_discovery_rejects_entities_that_do_not_belong(
    candidate: DiscoveredEntity, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_discovery_result(city(), result(candidate))


def test_discovery_requires_an_area_and_a_verified_source() -> None:
    with pytest.raises(ValueError, match="no area"):
        validate_discovery_result(city(with_area=False), result(entity()))
    unknown = DiscoveryResult(
        city_id="example",
        source_id="missing",
        status=DiscoveryStatus.AVAILABLE,
        discovered_at=NOW,
    )
    with pytest.raises(ValueError, match="not a verified source"):
        validate_discovery_result(city(), unknown)


def test_entity_city_must_match_result_city() -> None:
    with pytest.raises(ValidationError, match="entity city"):
        DiscoveryResult(
            city_id="example",
            source_id="station_network",
            status=DiscoveryStatus.AVAILABLE,
            discovered_at=NOW,
            entities=(entity(city_id="other"),),
        )


def test_unavailable_discovery_carries_an_error_and_no_entities() -> None:
    error = ProviderError(code=ProviderErrorCode.UPSTREAM, message="inventory request failed")
    unavailable = DiscoveryResult(
        city_id="example",
        source_id="station_network",
        status=DiscoveryStatus.UNAVAILABLE,
        discovered_at=NOW,
        error=error,
    )
    assert unavailable.entities == ()

    with pytest.raises(ValidationError):
        DiscoveryResult(
            city_id="example",
            source_id="station_network",
            status=DiscoveryStatus.UNAVAILABLE,
            discovered_at=NOW,
            entities=(entity(),),
            error=error,
        )
    with pytest.raises(ValidationError):
        DiscoveryResult(
            city_id="example",
            source_id="station_network",
            status=DiscoveryStatus.AVAILABLE,
            discovered_at=NOW,
            error=error,
        )


def test_duplicate_entities_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        result(entity(), entity())


def test_entities_in_the_surroundings_are_accepted_but_not_beyond() -> None:
    raw = city().model_dump(mode="json")
    raw["area"]["surroundings_km"] = 10
    with_ring = CityDefinition.model_validate(raw)

    validate_discovery_result(with_ring, result(entity(latitude=50.25)))
    with pytest.raises(ValueError, match="outside the city area"):
        validate_discovery_result(with_ring, result(entity(latitude=50.4)))
