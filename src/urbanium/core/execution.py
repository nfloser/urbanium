"""Contracts and invocation for deterministic component execution."""

from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from urbanium.core.city import CityDefinition, Identifier, VersionIdentifier
from urbanium.core.component import (
    ComponentDescriptor,
    ComponentResolution,
    DerivedStateCategory,
    resolve_component,
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


class CapabilityInput(BaseModel):
    """JSON-safe canonical input passed to a deterministic component."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: Identifier
    version: VersionIdentifier
    payload: JsonValue


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
        return _validate_execution_time(value)

    @model_validator(mode="after")
    def reject_duplicate_inputs(self) -> Self:
        duplicate_ids = _duplicates(item.capability_id for item in self.inputs)
        if duplicate_ids:
            raise ValueError("duplicate provenance capability ids: " + ", ".join(duplicate_ids))
        return self


class DerivedOutput(BaseModel):
    """Declared derived output identity with a JSON-safe domain payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Identifier
    version: VersionIdentifier
    state_category: DerivedStateCategory
    payload: JsonValue = None


class ComponentRunProblem(BaseModel):
    """Stable problem code with human-readable diagnostics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: Identifier
    message: str = Field(min_length=1)


class ComponentExecutionOutcome(BaseModel):
    """Implementation-owned outcome before framework provenance is attached."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: RunStatus
    outputs: tuple[DerivedOutput, ...] = ()
    problems: tuple[ComponentRunProblem, ...] = ()

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        _validate_run_state(self.status, self.outputs, self.problems)
        return self


class ComponentRunResult(BaseModel):
    """Validated run envelope independent of domain-specific output schemas."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: RunStatus
    provenance: ComponentRunProvenance
    outputs: tuple[DerivedOutput, ...] = ()
    problems: tuple[ComponentRunProblem, ...] = ()

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        _validate_run_state(self.status, self.outputs, self.problems)
        return self


class DeterministicComponent(Protocol):
    """Minimal implementation boundary for reusable deterministic components."""

    @property
    def descriptor(self) -> ComponentDescriptor: ...

    def run(self, inputs: tuple[CapabilityInput, ...]) -> ComponentExecutionOutcome: ...


class ComponentExecutionAttempt(BaseModel):
    """Capability resolution plus an optional authorized execution result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resolution: ComponentResolution
    run: ComponentRunResult | None = None

    @model_validator(mode="after")
    def validate_boundary(self) -> Self:
        if self.resolution.available and self.run is None:
            raise ValueError("resolved execution attempt requires a run result")
        if not self.resolution.available and self.run is not None:
            raise ValueError("unresolved execution attempt must not contain a run result")
        return self


def execute_component(
    city: CityDefinition,
    component: DeterministicComponent,
    *,
    inputs: tuple[CapabilityInput, ...],
    executed_at: datetime,
) -> ComponentExecutionAttempt:
    """Resolve, validate and invoke one deterministic component exactly once."""

    descriptor = component.descriptor
    resolution = resolve_component(city, descriptor)
    if not resolution.available:
        return ComponentExecutionAttempt(resolution=resolution)

    _validate_execution_time(executed_at)

    duplicate_inputs = _duplicates(item.capability_id for item in inputs)
    if duplicate_inputs:
        raise ValueError("duplicate capability input ids: " + ", ".join(duplicate_inputs))

    ordered_inputs = tuple(sorted(inputs, key=lambda item: (item.capability_id, item.version)))
    expected = sorted(
        (requirement.capability_id, requirement.version) for requirement in descriptor.inputs
    )
    actual = [(item.capability_id, item.version) for item in ordered_inputs]
    if actual != expected:
        raise ValueError("capability inputs do not match descriptor requirements")

    outcome = component.run(ordered_inputs)
    provenance = ComponentRunProvenance(
        city_id=city.id,
        component_id=descriptor.id,
        component_version=descriptor.version,
        inputs=tuple(
            CapabilityInputProvenance(
                capability_id=item.capability_id,
                version=item.version,
            )
            for item in ordered_inputs
        ),
        executed_at=executed_at,
    )
    run = ComponentRunResult(
        status=outcome.status,
        provenance=provenance,
        outputs=outcome.outputs,
        problems=outcome.problems,
    )
    validate_component_run(descriptor, resolution, run)
    return ComponentExecutionAttempt(resolution=resolution, run=run)


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


def _validate_run_state(
    status: RunStatus,
    outputs: tuple[DerivedOutput, ...],
    problems: tuple[ComponentRunProblem, ...],
) -> None:
    duplicate_ids = _duplicates(item.id for item in outputs)
    if duplicate_ids:
        raise ValueError("duplicate run output ids: " + ", ".join(duplicate_ids))

    if status is RunStatus.AVAILABLE and (not outputs or problems):
        raise ValueError("available run requires outputs and no problems")
    if status is RunStatus.DEGRADED and (not outputs or not problems):
        raise ValueError("degraded run requires outputs and problems")
    if status is RunStatus.UNAVAILABLE and (outputs or not problems):
        raise ValueError("unavailable run requires no outputs and problems")


def _validate_execution_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("executed_at must be timezone-aware")
    return value


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)
