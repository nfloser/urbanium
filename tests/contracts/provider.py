"""Shared behavioral contract for numeric observation providers."""

from dataclasses import dataclass

from urbanium.core.city import CityDefinition
from urbanium.core.provider import (
    Availability,
    ObservationProvider,
    validate_provider_descriptor,
    validate_provider_result,
)


@dataclass(frozen=True)
class ProviderContractCases:
    """Fixture-backed providers representing every required read outcome."""

    city: CityDefinition
    available: ObservationProvider
    degraded: ObservationProvider
    unavailable: ObservationProvider


def assert_provider_contract(cases: ProviderContractCases) -> None:
    """Apply the common binding, provenance and outcome checks to an adapter."""

    expected = (
        ("available", Availability.AVAILABLE, cases.available),
        ("degraded", Availability.DEGRADED, cases.degraded),
        ("unavailable", Availability.UNAVAILABLE, cases.unavailable),
    )
    descriptor = cases.available.descriptor

    for case_name, expected_availability, provider in expected:
        if provider.descriptor != descriptor:
            raise AssertionError(f"{case_name} case uses a different provider descriptor")

        validate_provider_descriptor(cases.city, provider.descriptor)
        result = provider.read()
        if result.availability is not expected_availability:
            raise AssertionError(f"{case_name} case returned {result.availability.value}")
        validate_provider_result(provider.descriptor, result)
