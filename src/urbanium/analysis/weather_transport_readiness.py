"""Evidence-only readiness assessment across independent weather and transport sources."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from pydantic import JsonValue

from urbanium.core.city import CityDefinition
from urbanium.core.component import (
    CapabilityRequirement,
    ComponentDescriptor,
    ComponentKind,
    ComponentOutput,
    DerivedStateCategory,
)
from urbanium.core.execution import (
    CapabilityInput,
    ComponentExecutionAttempt,
    ComponentExecutionOutcome,
    ComponentRunProblem,
    DerivedOutput,
    RunStatus,
    execute_component,
)
from urbanium.core.provider import (
    Availability,
    Freshness,
    Observation,
    ProviderDescriptor,
    ProviderResult,
    validate_provider_descriptor,
    validate_provider_result,
)

_DESCRIPTOR = ComponentDescriptor(
    id="weather_transport_readiness",
    kind=ComponentKind.AGENT,
    version="1",
    inputs=(
        CapabilityRequirement(capability_id="weather", version="1"),
        CapabilityRequirement(capability_id="realtime_transport", version="1"),
    ),
    outputs=(
        ComponentOutput(
            id="source_readiness",
            version="1",
            state_category=DerivedStateCategory.DERIVED,
        ),
    ),
)


@dataclass(frozen=True)
class _Evidence:
    snapshot: dict[str, JsonValue]
    has_measurements: bool
    usable: bool
    problems: tuple[ComponentRunProblem, ...]


class WeatherTransportReadiness:
    """Assess source readiness without claiming temporal, spatial or causal linkage."""

    def __init__(self, city: CityDefinition) -> None:
        self._city = city

    @property
    def descriptor(self) -> ComponentDescriptor:
        return _DESCRIPTOR

    def run(self, inputs: tuple[CapabilityInput, ...]) -> ComponentExecutionOutcome:
        by_capability = {item.capability_id: item for item in inputs}
        weather = self._inspect(by_capability["weather"], quantity="air_temperature", unit="Cel")
        transport = self._inspect(
            by_capability["realtime_transport"], quantity="active_service_alerts", unit="1"
        )
        problems = weather.problems + transport.problems

        if not weather.has_measurements and not transport.has_measurements:
            return ComponentExecutionOutcome(status=RunStatus.UNAVAILABLE, problems=problems)

        snapshot: dict[str, JsonValue] = {
            "independent_observations_only": True,
            "both_sources_usable": weather.usable and transport.usable,
            "weather": weather.snapshot,
            "realtime_transport": transport.snapshot,
        }
        output = DerivedOutput(
            id="source_readiness",
            version="1",
            state_category=DerivedStateCategory.DERIVED,
            payload=snapshot,
        )
        return ComponentExecutionOutcome(
            status=RunStatus.AVAILABLE if not problems else RunStatus.DEGRADED,
            outputs=(output,),
            problems=problems,
        )

    def _inspect(self, item: CapabilityInput, *, quantity: str, unit: str) -> _Evidence:
        raw = item.payload
        try:
            if not isinstance(raw, dict):
                raise ValueError("evidence payload must be an object")
            prepared_at = raw["prepared_at"]
            if not isinstance(prepared_at, str):
                raise ValueError("prepared_at must be a string")
            prepared_time = datetime.fromisoformat(prepared_at.replace("Z", "+00:00"))
            if prepared_time.tzinfo is None or prepared_time.utcoffset() is None:
                raise ValueError("prepared_at must be timezone-aware")

            provider = ProviderDescriptor.model_validate(raw["provider"])
            result = ProviderResult.model_validate(raw["read"])
            validate_provider_descriptor(self._city, provider)
            validate_provider_result(provider, result)
            if any(observation.received_at > prepared_time for observation in result.observations):
                raise ValueError("evidence was prepared before its observations were received")
            if provider.capability_id != item.capability_id or item.version != "1":
                raise ValueError("evidence capability contract mismatch")
        except (KeyError, TypeError, ValueError):
            return _Evidence(
                snapshot={"usable": False, "validated_observations": []},
                has_measurements=False,
                usable=False,
                problems=(
                    ComponentRunProblem(
                        code=f"{item.capability_id}_invalid_evidence",
                        message="Provider evidence envelope failed contract or city validation",
                    ),
                ),
            )

        problems: list[ComponentRunProblem] = []
        if result.availability is Availability.UNAVAILABLE:
            problems.append(
                ComponentRunProblem(
                    code=f"{item.capability_id}_unavailable",
                    message="Provider did not return observations",
                )
            )
        elif result.availability is Availability.DEGRADED:
            problems.append(
                ComponentRunProblem(
                    code=f"{item.capability_id}_degraded",
                    message="Provider returned observations with a reported error",
                )
            )

        if result.availability is not Availability.UNAVAILABLE:
            if result.freshness is Freshness.STALE:
                problems.append(
                    ComponentRunProblem(
                        code=f"{item.capability_id}_stale",
                        message="Provider observations are reported as stale",
                    )
                )
            elif result.freshness is Freshness.UNKNOWN:
                problems.append(
                    ComponentRunProblem(
                        code=f"{item.capability_id}_unknown_freshness",
                        message="Provider observation freshness is unknown",
                    )
                )

        validated: list[Observation] = []
        invalid_measurement = False
        for observation in result.observations:
            if observation.quantity_id != quantity:
                continue
            if observation.unit != unit:
                invalid_measurement = True
                problems.append(
                    ComponentRunProblem(
                        code=f"{item.capability_id}_invalid_unit",
                        message=f"Expected unit '{unit}' for '{quantity}'",
                    )
                )
                continue
            if not observation.value.is_finite() or (
                quantity == "active_service_alerts"
                and (
                    observation.value < Decimal(0)
                    or observation.value != observation.value.to_integral_value()
                )
            ):
                invalid_measurement = True
                problems.append(
                    ComponentRunProblem(
                        code=f"{item.capability_id}_invalid_value",
                        message=f"Invalid numeric value for '{quantity}'",
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
                    code=f"{item.capability_id}_missing_measurement",
                    message=f"No '{quantity}' observation is present",
                )
            )

        ordered = sorted(
            validated,
            key=lambda obs: (
                obs.entity.entity_type,
                obs.entity.entity_id,
                obs.observed_at,
                obs.received_at,
                str(obs.value),
            ),
        )
        usable = bool(ordered) and not problems
        return _Evidence(
            snapshot={
                "usable": usable,
                "prepared_at": prepared_time.isoformat(),
                "provider": provider.model_dump(mode="json"),
                "read": result.model_dump(mode="json"),
                "validated_observations": [obs.model_dump(mode="json") for obs in ordered],
            },
            has_measurements=bool(ordered),
            usable=usable,
            problems=tuple(problems),
        )


def assess_weather_transport_readiness(
    city: CityDefinition,
    *,
    weather: CapabilityInput,
    transport: CapabilityInput,
    executed_at: datetime,
) -> ComponentExecutionAttempt:
    """Run the versioned readiness component against one city deployment."""

    return execute_component(
        city,
        WeatherTransportReadiness(city),
        inputs=(weather, transport),
        executed_at=executed_at,
    )
