"""Checked handoff from canonical provider reads to deterministic component inputs."""

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
) -> CapabilityInput:
    """Preserve the complete read outcome under the city's capability contract version.

    An unavailable read is still an input *about* the source's failure, not a
    successful observation. Components must handle its availability explicitly.
    """
    validate_provider_descriptor(city, descriptor)
    validate_provider_result(descriptor, result)

    version = next(
        capability.version
        for capability in city.capabilities
        if capability.id == descriptor.capability_id
    )
    return CapabilityInput(
        capability_id=descriptor.capability_id,
        version=version,
        payload={
            "provider": descriptor.model_dump(mode="json"),
            "read": result.model_dump(mode="json"),
        },
    )
