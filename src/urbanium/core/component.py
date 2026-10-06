"""Deterministic component descriptors and city capability resolution."""

from collections.abc import Iterable
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from urbanium.core.city import (
    CapabilitySupport,
    CityDefinition,
    Identifier,
    VersionIdentifier,
)


class ComponentKind(StrEnum):
    """Kinds of deterministic reusable computation components."""

    AGENT = "agent"
    MODEL = "model"


class DerivedStateCategory(StrEnum):
    """State categories that a deterministic component may declare as output."""

    DERIVED = "derived"
    FORECAST = "forecast"
    SCENARIO = "scenario"
    SIMULATED = "simulated"


class CapabilityRequirement(BaseModel):
    """Exact capability contract required by a component."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: Identifier
    version: VersionIdentifier


class ComponentOutput(BaseModel):
    """Versioned output contract declared by a component."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Identifier
    version: VersionIdentifier
    state_category: DerivedStateCategory


class ComponentDescriptor(BaseModel):
    """Static descriptor for a deterministic agent or model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Identifier
    kind: ComponentKind
    version: VersionIdentifier
    inputs: tuple[CapabilityRequirement, ...] = ()
    outputs: tuple[ComponentOutput, ...] = ()

    @model_validator(mode="after")
    def validate_unique_contracts(self) -> Self:
        duplicate_inputs = _duplicates(item.capability_id for item in self.inputs)
        if duplicate_inputs:
            raise ValueError("duplicate capability requirements: " + ", ".join(duplicate_inputs))

        duplicate_outputs = _duplicates(item.id for item in self.outputs)
        if duplicate_outputs:
            raise ValueError("duplicate output ids: " + ", ".join(duplicate_outputs))
        return self


class ComponentRegistry:
    """Immutable deterministic lookup over component descriptors."""

    def __init__(self, descriptors: Iterable[ComponentDescriptor]) -> None:
        by_key: dict[tuple[ComponentKind, str, str], ComponentDescriptor] = {}
        for descriptor in descriptors:
            key = (descriptor.kind, descriptor.id, descriptor.version)
            if key in by_key:
                raise ValueError(
                    "duplicate component descriptor "
                    f"'{descriptor.kind.value}:{descriptor.id}:{descriptor.version}'"
                )
            by_key[key] = descriptor
        self._descriptors = by_key

    @property
    def descriptors(self) -> tuple[ComponentDescriptor, ...]:
        return tuple(
            sorted(
                self._descriptors.values(),
                key=lambda item: (item.kind.value, item.id, item.version),
            )
        )

    def descriptor(
        self,
        kind: ComponentKind,
        component_id: str,
        version: str,
    ) -> ComponentDescriptor:
        key = (kind, component_id, version)
        try:
            return self._descriptors[key]
        except KeyError as exc:
            raise KeyError(f"unknown component '{kind.value}:{component_id}:{version}'") from exc


class ResolutionReasonCode(StrEnum):
    """Stable reasons why a capability requirement cannot be satisfied."""

    MISSING_CAPABILITY = "missing_capability"
    NOT_CONFIGURED = "not_configured"
    VERSION_MISMATCH = "version_mismatch"


class UnavailableCapability(BaseModel):
    """One unsatisfied requirement with enough detail for deterministic handling."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: Identifier
    reason: ResolutionReasonCode
    required_version: VersionIdentifier
    available_version: VersionIdentifier | None = None
    support: CapabilitySupport | None = None


class ComponentResolution(BaseModel):
    """Resolution result for one component against one city deployment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    city_id: Identifier
    component_id: Identifier
    component_version: VersionIdentifier
    unavailable: tuple[UnavailableCapability, ...] = ()

    @property
    def available(self) -> bool:
        return not self.unavailable


def resolve_component(
    city: CityDefinition,
    descriptor: ComponentDescriptor,
) -> ComponentResolution:
    """Resolve exact component requirements against configured city contracts."""

    capabilities = {capability.id: capability for capability in city.capabilities}
    unavailable: list[UnavailableCapability] = []

    for requirement in sorted(
        descriptor.inputs,
        key=lambda item: (item.capability_id, item.version),
    ):
        capability = capabilities.get(requirement.capability_id)
        if capability is None:
            unavailable.append(
                UnavailableCapability(
                    capability_id=requirement.capability_id,
                    reason=ResolutionReasonCode.MISSING_CAPABILITY,
                    required_version=requirement.version,
                )
            )
            continue

        if capability.support is not CapabilitySupport.CONFIGURED:
            unavailable.append(
                UnavailableCapability(
                    capability_id=requirement.capability_id,
                    reason=ResolutionReasonCode.NOT_CONFIGURED,
                    required_version=requirement.version,
                    available_version=capability.version,
                    support=capability.support,
                )
            )
            continue

        if capability.version != requirement.version:
            unavailable.append(
                UnavailableCapability(
                    capability_id=requirement.capability_id,
                    reason=ResolutionReasonCode.VERSION_MISMATCH,
                    required_version=requirement.version,
                    available_version=capability.version,
                    support=capability.support,
                )
            )

    return ComponentResolution(
        city_id=city.id,
        component_id=descriptor.id,
        component_version=descriptor.version,
        unavailable=tuple(unavailable),
    )


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)
