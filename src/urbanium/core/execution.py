"""Contracts for deterministic component run outcomes and provenance."""

from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from urbanium.core.city import Identifier, VersionIdentifier
from urbanium.core.component import (
    ComponentDescriptor,
    ComponentResolution,
    DerivedStateCategory,
)


class RunStatus(StrEnum):
    """Outcome of one deterministic component run."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class CapabilityInputProvenance(BaseModel):
    """Exact capability contract consumed by a component run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: Identifier
    version: VersionIdentifier


class ComponentRunProvenance(BaseModel):
    """Reconstructable identity and input contract set for one run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    city_id: Identifier
    component_id: Identifier
    component_version: VersionIdentifier
    inputs: tuple[CapabilityInputProvenance, ...] = ()
    executed_at: datetime

    @field_validator("executed_at")
    @classmethod
    def validate_executed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("executed_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def reject_duplicate_inputs(self) -> Self:
        duplicate_ids = _duplicates(item.capability_id for item in self.inputs)
        if duplicate_ids:
            raise ValueError("duplicate provenance capability ids: " + ", ".join(duplicate_ids))
        return self


class DerivedOutput(BaseModel):
    """Contract identity of one derived output emitted by a component."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Identifier
    version: VersionIdentifier
    state_category: DerivedStateCategory


class ComponentRunProblem(BaseModel):
    """Stable problem code with human-readable diagnostics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: Identifier
    message: str = Field(min_length=1)


class ComponentRunResult(BaseModel):
    """Validated run envelope independent of domain-specific output payloads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: RunStatus
    provenance: ComponentRunProvenance
    outputs: tuple[DerivedOutput, ...] = ()
    problems: tuple[ComponentRunProblem, ...] = ()

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        duplicate_ids = _duplicates(item.id for item in self.outputs)
        if duplicate_ids:
            raise ValueError("duplicate run output ids: " + ", ".join(duplicate_ids))

        if self.status is RunStatus.AVAILABLE and (not self.outputs or self.problems):
            raise ValueError("available run requires outputs and no problems")
        if self.status is RunStatus.DEGRADED and (not self.outputs or not self.problems):
            raise ValueError("degraded run requires outputs and problems")
        if self.status is RunStatus.UNAVAILABLE and (self.outputs or not self.problems):
            raise ValueError("unavailable run requires no outputs and problems")
        return self


def validate_component_run(
    descriptor: ComponentDescriptor,
    resolution: ComponentResolution,
    result: ComponentRunResult,
) -> None:
    """Validate a run envelope against its descriptor and prior city resolution."""

    if (
        resolution.component_id != descriptor.id
        or resolution.component_version != descriptor.version
    ):
        raise ValueError("resolution component identity does not match descriptor")

    if resolution.unavailable:
        raise ValueError("unresolved component cannot produce a run result")

    provenance = result.provenance
    if (
        provenance.component_id != descriptor.id
        or provenance.component_version != descriptor.version
        or provenance.city_id != resolution.city_id
    ):
        raise ValueError("run provenance component identity or city does not match resolution")

    expected_inputs = sorted(
        (requirement.capability_id, requirement.version) for requirement in descriptor.inputs
    )
    actual_inputs = sorted((item.capability_id, item.version) for item in provenance.inputs)
    if actual_inputs != expected_inputs:
        raise ValueError("run provenance capability inputs do not match descriptor requirements")

    declared_outputs = {output.id: output for output in descriptor.outputs}
    for output in result.outputs:
        declared = declared_outputs.get(output.id)
        if declared is None:
            raise ValueError(f"run output '{output.id}' is not declared by component")
        if output.version != declared.version:
            raise ValueError(f"run output '{output.id}' version does not match descriptor")
        if output.state_category is not declared.state_category:
            raise ValueError(f"run output '{output.id}' state category does not match descriptor")


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)
