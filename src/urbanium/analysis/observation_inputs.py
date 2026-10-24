"""Checked handoff from canonical provider reads to deterministic component inputs."""

from datetime import UTC, datetime

from urbanium.core.city import CityDefinition
from urbanium.core.execution import CapabilityInput
from urbanium.core.provider import (
    ProviderDescriptor,
    ProviderResult,
    validate_provider_descriptor,
    validate_provider_result,
)


def observation_input(
    city: CityDefinition,
    descriptor: ProviderDescriptor,
    result: ProviderResult,
    *,
    prepared_at: datetime,
) -> CapabilityInput:
    """Preserve the complete read outcome under the city's capability contract version.

    An unavailable read is still an input *about* the source's failure, not a
    successful observation. Components must handle its availability explicitly.
    """
    validate_provider_descriptor(city, descriptor)
    validate_provider_result(descriptor, result)
    if prepared_at.tzinfo is None or prepared_at.utcoffset() is None:
        raise ValueError("prepared_at must be timezone-aware")
    if any(observation.received_at > prepared_at for observation in result.observations):
        raise ValueError("prepared_at must not precede observation received_at")

    version = next(
        capability.version
        for capability in city.capabilities
        if capability.id == descriptor.capability_id
    )
    return CapabilityInput(
        capability_id=descriptor.capability_id,
        version=version,
        payload={
            "prepared_at": prepared_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "provider": descriptor.model_dump(mode="json"),
            "read": result.model_dump(mode="json"),
        },
    )
