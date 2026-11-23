"""Checked handoff from canonical provider reads to deterministic component inputs."""

from collections.abc import Iterable
from datetime import UTC, datetime

from pydantic import JsonValue

from urbanium.core.city import CityDefinition
from urbanium.core.discovery import DiscoveredEntity
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
    reference: Iterable[DiscoveredEntity] | None = None,
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
    payload: dict[str, JsonValue] = {
        "prepared_at": prepared_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "provider": descriptor.model_dump(mode="json"),
        "read": result.model_dump(mode="json"),
    }
    if reference is not None:
        payload["reference_entities"] = _reference_context(city, reference, prepared_at)
    return CapabilityInput(
        capability_id=descriptor.capability_id,
        version=version,
        payload=payload,
    )


def _reference_context(
    city: CityDefinition, reference: Iterable[DiscoveredEntity], prepared_at: datetime
) -> list[JsonValue]:
    """Reference metadata of the read's entities (e.g. gauge characteristic values).

    This is sourced reference state, kept with its evidence, so components can
    relate measurements to it without calling any provider.
    """

    context: list[JsonValue] = []
    for item in reference:
        entity = item.location.entity
        if entity.city_id != city.id:
            raise ValueError("reference entity does not belong to the city")
        if any(evidence.retrieved_at > prepared_at for evidence in item.location.evidence):
            raise ValueError("reference evidence must not postdate prepared_at")
        context.append(
            {
                "entity": entity.canonical_id,
                "entity_type": entity.entity_type,
                "attributes": dict(item.attributes),
                "evidence": [
                    evidence.model_dump(mode="json") for evidence in item.location.evidence
                ],
            }
        )
    return context
