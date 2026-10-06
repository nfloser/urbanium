from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urbanium.api.app import API_VERSION, create_app
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

ROOT = Path(__file__).resolve().parents[1]
CITIES = ROOT / "cities"
NOW = datetime(2026, 10, 6, 9, 30, tzinfo=UTC)


class FixtureProvider:
    def __init__(self, result: ProviderResult) -> None:
        self._result = result
        self.calls = 0

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            city_id="mainz",
            source_id="dwd_open_data",
            capability_id="weather",
            adapter_version="test-1",
        )

    def read(self) -> ProviderResult:
        self.calls += 1
        return self._result


def observation() -> Observation:
    return Observation(
        city_id="mainz",
        source_id="dwd_open_data",
        capability_id="weather",
        entity=EntityReference(
            city_id="mainz",
            entity_type="weather_station",
            entity_id="dwd_station_10637",
        ),
        quantity_id="air_temperature",
        value=Decimal("12.3"),
        unit="Cel",
        observed_at=NOW,
        received_at=NOW,
        quality_scheme="dwd_qn",
        quality_code="2",
    )


def available_result() -> ProviderResult:
    return ProviderResult(
        availability=Availability.AVAILABLE,
        freshness=Freshness.FRESH,
        observations=(observation(),),
    )


def degraded_result() -> ProviderResult:
    return ProviderResult(
        availability=Availability.DEGRADED,
        freshness=Freshness.FRESH,
        observations=(observation(),),
        error=ProviderError(
            code=ProviderErrorCode.INVALID_RESPONSE,
            message="one upstream record was invalid",
        ),
    )


def unavailable_result() -> ProviderResult:
    return ProviderResult(
        availability=Availability.UNAVAILABLE,
        freshness=Freshness.UNKNOWN,
        error=ProviderError(
            code=ProviderErrorCode.TIMEOUT,
            message="upstream timed out",
        ),
    )


def client(*providers: FixtureProvider) -> TestClient:
    registry = CityRegistry.from_directory(CITIES)
    return TestClient(create_app(registry, providers=providers))


def test_versioned_city_capability_and_source_discovery() -> None:
    api = client()

    cities = api.get("/api/v1/cities")
    assert cities.status_code == 200
    assert cities.json()["api_version"] == API_VERSION
    assert [item["id"] for item in cities.json()["cities"]] == ["berlin", "mainz"]

    capabilities = api.get("/api/v1/cities/mainz/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["api_version"] == API_VERSION
    support = {item["id"]: item["support"] for item in capabilities.json()["capabilities"]}
    assert support["weather"] == "configured"
    assert support["realtime_transport"] == "candidate"

    sources = api.get("/api/v1/cities/mainz/sources")
    assert sources.status_code == 200
    source_ids = [item["id"] for item in sources.json()["sources"]]
    assert source_ids == ["dwd_open_data", "mainz_webgis_2026", "pegelonline_mainz"]


def test_unknown_city_is_a_stable_machine_readable_problem() -> None:
    response = client().get("/api/v1/cities/not_a_city")

    assert response.status_code == 404
    assert response.json() == {
        "api_version": API_VERSION,
        "code": "city_not_found",
        "message": "unknown city 'not_a_city'",
    }


def test_available_and_degraded_provider_results_stay_canonical() -> None:
    available = FixtureProvider(available_result())
    response = client(available).get(
        "/api/v1/cities/mainz/sources/dwd_open_data/observations/weather"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["api_version"] == API_VERSION
    assert body["city_id"] == "mainz"
    assert body["source_id"] == "dwd_open_data"
    assert body["capability_id"] == "weather"
    assert body["result"]["availability"] == "available"
    assert body["result"]["observations"][0]["quantity_id"] == "air_temperature"
    assert available.calls == 1

    degraded = FixtureProvider(degraded_result())
    response = client(degraded).get(
        "/api/v1/cities/mainz/sources/dwd_open_data/observations/weather"
    )

    assert response.status_code == 200
    assert response.json()["result"]["availability"] == "degraded"
    assert response.json()["result"]["error"]["code"] == "invalid_response"


def test_unavailable_provider_result_uses_503_without_losing_typed_body() -> None:
    provider = FixtureProvider(unavailable_result())
    response = client(provider).get(
        "/api/v1/cities/mainz/sources/dwd_open_data/observations/weather"
    )

    assert response.status_code == 503
    body = response.json()
    assert body["api_version"] == API_VERSION
    assert body["result"]["availability"] == "unavailable"
    assert body["result"]["freshness"] == "unknown"
    assert body["result"]["error"]["code"] == "timeout"
    assert provider.calls == 1


def test_candidate_capability_is_not_presented_as_runtime_available() -> None:
    response = client().get(
        "/api/v1/cities/mainz/sources/mainz_webgis_2026/observations/open_data_catalog"
    )

    assert response.status_code == 409
    assert response.json()["code"] == "capability_not_configured"


def test_missing_runtime_binding_is_explicit() -> None:
    response = client().get("/api/v1/cities/mainz/sources/dwd_open_data/observations/weather")

    assert response.status_code == 503
    assert response.json()["code"] == "provider_not_bound"


def test_duplicate_provider_binding_is_rejected_at_app_creation() -> None:
    registry = CityRegistry.from_directory(CITIES)
    first = FixtureProvider(available_result())
    second = FixtureProvider(available_result())

    with pytest.raises(ValueError, match="duplicate provider binding"):
        create_app(registry, providers=(first, second))


def test_openapi_contract_is_versioned_and_declares_health_semantics() -> None:
    registry = CityRegistry.from_directory(CITIES)
    schema = create_app(registry).openapi()

    assert schema["info"]["version"] == "1.0.0"
    assert schema["openapi"].startswith("3.")
    assert {
        "/api/v1/cities",
        "/api/v1/cities/{city_id}",
        "/api/v1/cities/{city_id}/capabilities",
        "/api/v1/cities/{city_id}/sources",
        "/api/v1/cities/{city_id}/sources/{source_id}/observations/{capability_id}",
    }.issubset(schema["paths"])

    observation_path = schema["paths"][
        "/api/v1/cities/{city_id}/sources/{source_id}/observations/{capability_id}"
    ]["get"]
    assert "200" in observation_path["responses"]
    assert "409" in observation_path["responses"]
    assert "503" in observation_path["responses"]
