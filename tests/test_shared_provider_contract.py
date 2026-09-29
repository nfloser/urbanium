from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tests.contracts.provider import ProviderContractCases, assert_provider_contract
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
from urbanium.registry import load_city_definition

CITIES = Path(__file__).resolve().parents[1] / "cities"
DESCRIPTOR = ProviderDescriptor(
    city_id="mainz",
    source_id="dwd_open_data",
    capability_id="weather",
    adapter_version="1.0.0",
)


def observation(*, source_id: str = "dwd_open_data") -> Observation:
    observed_at = datetime(2026, 9, 29, 12, tzinfo=UTC)
    return Observation(
        city_id="mainz",
        source_id=source_id,
        capability_id="weather",
        entity=EntityReference(
            city_id="mainz",
            entity_type="weather_station",
            entity_id="station_1",
        ),
        quantity_id="air_temperature",
        value=Decimal("12.3"),
        unit="Cel",
        observed_at=observed_at,
        received_at=observed_at,
    )


class FixtureProvider:
    def __init__(self, result: ProviderResult) -> None:
        self.descriptor = DESCRIPTOR
        self._result = result

    def read(self) -> ProviderResult:
        return self._result


def cases() -> ProviderContractCases:
    partial_error = ProviderError(
        code=ProviderErrorCode.INVALID_RESPONSE,
        message="one fixture row was invalid",
    )
    outage = ProviderError(code=ProviderErrorCode.TIMEOUT, message="fixture timeout")
    return ProviderContractCases(
        city=load_city_definition(CITIES / "mainz" / "city.yaml"),
        available=FixtureProvider(
            ProviderResult(
                availability=Availability.AVAILABLE,
                freshness=Freshness.FRESH,
                observations=(observation(),),
            )
        ),
        degraded=FixtureProvider(
            ProviderResult(
                availability=Availability.DEGRADED,
                freshness=Freshness.STALE,
                observations=(observation(),),
                error=partial_error,
            )
        ),
        unavailable=FixtureProvider(
            ProviderResult(
                availability=Availability.UNAVAILABLE,
                freshness=Freshness.UNKNOWN,
                error=outage,
            )
        ),
    )


def test_shared_contract_accepts_all_explicit_provider_states() -> None:
    assert_provider_contract(cases())


def test_shared_contract_rejects_wrong_state_for_case() -> None:
    contract = cases()
    with pytest.raises(AssertionError, match="degraded case returned available"):
        assert_provider_contract(
            ProviderContractCases(
                city=contract.city,
                available=contract.available,
                degraded=contract.available,
                unavailable=contract.unavailable,
            )
        )


def test_shared_contract_rejects_observation_provenance_mismatch() -> None:
    contract = cases()
    invalid = FixtureProvider(
        ProviderResult(
            availability=Availability.AVAILABLE,
            freshness=Freshness.FRESH,
            observations=(observation(source_id="pegelonline_mainz"),),
        )
    )
    with pytest.raises(ValueError, match="does not match provider descriptor"):
        assert_provider_contract(
            ProviderContractCases(
                city=contract.city,
                available=invalid,
                degraded=contract.degraded,
                unavailable=contract.unavailable,
            )
        )
