"""Reusable provider-evidence assessment and deterministic answerability reports."""

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from urbanium.core.city import CityDefinition, Identifier, VersionIdentifier
from urbanium.core.execution import CapabilityInput, ComponentRunProblem
from urbanium.core.provider import (
    Availability,
    Freshness,
    Observation,
    ProviderDescriptor,
    ProviderResult,
    validate_provider_descriptor,
    validate_provider_result,
)


class NumericConstraint(StrEnum):
    """Portable numeric rules that evidence requirements may impose."""

    FINITE = "finite"
    NON_NEGATIVE_INTEGER = "non_negative_integer"


class EvidenceRequirement(BaseModel):
    """One capability measurement required for a deterministic analysis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: Identifier
    version: VersionIdentifier = "1"
    quantity_id: Identifier
    unit: str = Field(min_length=1)
    numeric_constraint: NumericConstraint = NumericConstraint.FINITE


class EvidenceAssessment(BaseModel):
    """Validated evidence for one requirement, including diagnostics."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    capability_id: Identifier
    usable: bool
    has_measurements: bool
    snapshot: dict[str, JsonValue]
    observations: tuple[Observation, ...] = ()
    problems: tuple[ComponentRunProblem, ...] = ()


class AnswerabilityStatus(StrEnum):
    """Coverage state for a set of evidence requirements."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class AnswerabilityItem(BaseModel):
    """Coverage of one required capability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: Identifier
    usable: bool
    has_measurements: bool
    problem_codes: tuple[Identifier, ...] = ()


class AnswerabilityReport(BaseModel):
    """Deterministic pre-flight report for evidence-backed analysis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AnswerabilityStatus
    items: tuple[AnswerabilityItem, ...] = ()

    @property
    def answerable(self) -> bool:
        return self.status is AnswerabilityStatus.AVAILABLE


def assess_evidence(
    city: CityDefinition,
    item: CapabilityInput,
    requirement: EvidenceRequirement,
    *,
    executed_at: datetime,
) -> EvidenceAssessment:
    """Validate one provider-evidence input against an analysis requirement."""

    capability_id = requirement.capability_id
    try:
        if item.capability_id != capability_id or item.version != requirement.version:
            raise ValueError("evidence capability contract mismatch")
        raw = item.payload
        if not isinstance(raw, dict):
            raise ValueError("evidence payload must be an object")
        prepared_at = raw["prepared_at"]
        if not isinstance(prepared_at, str):
            raise ValueError("prepared_at must be a string")
        prepared_time = datetime.fromisoformat(prepared_at.replace("Z", "+00:00"))
        if prepared_time.tzinfo is None or prepared_time.utcoffset() is None:
            raise ValueError("prepared_at must be timezone-aware")
        if executed_at.tzinfo is None or executed_at.utcoffset() is None:
            raise ValueError("executed_at must be timezone-aware")
        if prepared_time > executed_at:
            raise ValueError("evidence was prepared after analysis execution")

        provider = ProviderDescriptor.model_validate(raw["provider"])
        result = ProviderResult.model_validate(raw["read"])
        validate_provider_descriptor(city, provider)
        validate_provider_result(provider, result)
        if provider.capability_id != capability_id:
            raise ValueError("provider capability does not match requirement")
        if any(observation.received_at > prepared_time for observation in result.observations):
            raise ValueError("evidence was prepared before its observations were received")
    except (KeyError, TypeError, ValueError):
        return EvidenceAssessment(
            capability_id=capability_id,
            usable=False,
            has_measurements=False,
            snapshot={"usable": False, "validated_observations": []},
            problems=(
                ComponentRunProblem(
                    code=f"{capability_id}_invalid_evidence",
                    message="Provider evidence envelope failed contract or city validation",
                ),
            ),
        )

    problems: list[ComponentRunProblem] = []
    if result.availability is Availability.UNAVAILABLE:
        problems.append(
            ComponentRunProblem(
                code=f"{capability_id}_unavailable",
                message="Provider did not return observations",
            )
        )
    elif result.availability is Availability.DEGRADED:
        problems.append(
            ComponentRunProblem(
                code=f"{capability_id}_degraded",
                message="Provider returned observations with a reported error",
            )
        )

    if result.availability is not Availability.UNAVAILABLE:
        if result.freshness is Freshness.STALE:
            problems.append(
                ComponentRunProblem(
                    code=f"{capability_id}_stale",
                    message="Provider observations are reported as stale",
                )
            )
        elif result.freshness is Freshness.UNKNOWN:
            problems.append(
                ComponentRunProblem(
                    code=f"{capability_id}_unknown_freshness",
                    message="Provider observation freshness is unknown",
                )
            )

    validated: list[Observation] = []
    invalid_measurement = False
    for observation in result.observations:
        if observation.quantity_id != requirement.quantity_id:
            continue
        if observation.unit != requirement.unit:
            invalid_measurement = True
            problems.append(
                ComponentRunProblem(
                    code=f"{capability_id}_invalid_unit",
                    message=(f"Expected unit '{requirement.unit}' for '{requirement.quantity_id}'"),
                )
            )
            continue
        if not _numeric_value_allowed(observation.value, requirement.numeric_constraint):
            invalid_measurement = True
            problems.append(
                ComponentRunProblem(
                    code=f"{capability_id}_invalid_value",
                    message=f"Invalid numeric value for '{requirement.quantity_id}'",
                )
            )
            continue
        validated.append(observation)

    if (
        not validated
        and not invalid_measurement
        and result.availability is not Availability.UNAVAILABLE
    ):
        problems.append(
            ComponentRunProblem(
                code=f"{capability_id}_missing_measurement",
                message=f"No '{requirement.quantity_id}' observation is present",
            )
        )

    ordered = tuple(
        sorted(
            validated,
            key=lambda obs: (
                obs.entity.entity_type,
                obs.entity.entity_id,
                obs.observed_at,
                obs.received_at,
                str(obs.value),
            ),
        )
    )
    usable = bool(ordered) and not problems
    return EvidenceAssessment(
        capability_id=capability_id,
        usable=usable,
        has_measurements=bool(ordered),
        snapshot={
            "usable": usable,
            "prepared_at": prepared_time.isoformat(),
            "provider": provider.model_dump(mode="json"),
            "read": result.model_dump(mode="json"),
            "validated_observations": [obs.model_dump(mode="json") for obs in ordered],
        },
        observations=ordered,
        problems=tuple(problems),
    )


def assess_answerability(
    requirements: Iterable[EvidenceRequirement],
    assessments: Iterable[EvidenceAssessment],
) -> AnswerabilityReport:
    """Report whether all required evidence is usable before domain analysis."""

    ordered_requirements = sorted(
        requirements,
        key=lambda item: (item.capability_id, item.version, item.quantity_id, item.unit),
    )
    duplicate_requirements = _duplicates(item.capability_id for item in ordered_requirements)
    if duplicate_requirements:
        names = ", ".join(duplicate_requirements)
        raise ValueError(f"duplicate evidence requirement capabilities: {names}")

    by_capability: dict[str, EvidenceAssessment] = {}
    for candidate in assessments:
        if candidate.capability_id in by_capability:
            raise ValueError(f"duplicate evidence assessment '{candidate.capability_id}'")
        by_capability[candidate.capability_id] = candidate

    items: list[AnswerabilityItem] = []
    for requirement in ordered_requirements:
        selected = by_capability.get(requirement.capability_id)
        if selected is None:
            items.append(
                AnswerabilityItem(
                    capability_id=requirement.capability_id,
                    usable=False,
                    has_measurements=False,
                    problem_codes=(f"{requirement.capability_id}_missing_evidence",),
                )
            )
            continue
        items.append(
            AnswerabilityItem(
                capability_id=requirement.capability_id,
                usable=selected.usable,
                has_measurements=selected.has_measurements,
                problem_codes=tuple(problem.code for problem in selected.problems),
            )
        )

    if items and all(item.usable for item in items):
        status = AnswerabilityStatus.AVAILABLE
    elif any(item.has_measurements for item in items):
        status = AnswerabilityStatus.DEGRADED
    else:
        status = AnswerabilityStatus.UNAVAILABLE
    return AnswerabilityReport(status=status, items=tuple(items))


def _numeric_value_allowed(value: Decimal, constraint: NumericConstraint) -> bool:
    if not value.is_finite():
        return False
    if constraint is NumericConstraint.NON_NEGATIVE_INTEGER:
        return value >= Decimal(0) and value == value.to_integral_value()
    return True


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)
