"""Evidence-only readiness assessment across independent weather and transport sources."""

from datetime import UTC, datetime

from pydantic import JsonValue

from urbanium.analysis.evidence import (
    AnswerabilityStatus,
    EvidenceRequirement,
    NumericConstraint,
    assess_answerability,
    assess_evidence,
)
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
    DerivedOutput,
    RunStatus,
    execute_component,
)
from urbanium.core.provider import Observation

_WEATHER_EVIDENCE = EvidenceRequirement(
    capability_id="weather",
    quantity_id="air_temperature",
    unit="Cel",
)
_TRANSPORT_EVIDENCE = EvidenceRequirement(
    capability_id="realtime_transport",
    quantity_id="active_service_alerts",
    unit="1",
    numeric_constraint=NumericConstraint.NON_NEGATIVE_INTEGER,
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


def _closest_observation_pair(
    weather: tuple[Observation, ...], transport: tuple[Observation, ...]
) -> tuple[float | None, dict[str, JsonValue] | None]:
    """Trace the nearest observed instants without implying shared coverage."""
    if not weather or not transport:
        return None, None

    def order_key(item: Observation) -> tuple[datetime, str, str, datetime, str]:
        return (
            item.observed_at.astimezone(UTC),
            item.entity.entity_type,
            item.entity.entity_id,
            item.received_at.astimezone(UTC),
            str(item.value),
        )

    weather_ordered = sorted(weather, key=order_key)
    transport_ordered = sorted(transport, key=order_key)
    weather_index = transport_index = 0
    best: tuple[Observation, Observation] | None = None
    best_key: tuple[float, datetime, datetime, str, str, str, str] | None = None

    while weather_index < len(weather_ordered) and transport_index < len(transport_ordered):
        left = weather_ordered[weather_index]
        right = transport_ordered[transport_index]
        left_time = left.observed_at.astimezone(UTC)
        right_time = right.observed_at.astimezone(UTC)
        candidate = (
            abs((left_time - right_time).total_seconds()),
            left_time,
            right_time,
            left.entity.entity_type,
            left.entity.entity_id,
            right.entity.entity_type,
            right.entity.entity_id,
        )
        if best_key is None or candidate < best_key:
            best_key = candidate
            best = (left, right)
        if left_time <= right_time:
            weather_index += 1
        else:
            transport_index += 1

    assert best is not None and best_key is not None
    weather_match, transport_match = best
    return best_key[0], {
        "weather": {
            "entity": weather_match.entity.model_dump(mode="json"),
            "observed_at": weather_match.observed_at.astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z"),
        },
        "realtime_transport": {
            "entity": transport_match.entity.model_dump(mode="json"),
            "observed_at": transport_match.observed_at.astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z"),
        },
    }


class WeatherTransportReadiness:
    """Assess source readiness without claiming temporal, spatial or causal linkage."""

    def __init__(self, city: CityDefinition, *, executed_at: datetime) -> None:
        self._city = city
        self._executed_at = executed_at

    @property
    def descriptor(self) -> ComponentDescriptor:
        return _DESCRIPTOR

    def run(self, inputs: tuple[CapabilityInput, ...]) -> ComponentExecutionOutcome:
        by_capability = {item.capability_id: item for item in inputs}
        weather = assess_evidence(
            self._city,
            by_capability["weather"],
            _WEATHER_EVIDENCE,
            executed_at=self._executed_at,
        )
        transport = assess_evidence(
            self._city,
            by_capability["realtime_transport"],
            _TRANSPORT_EVIDENCE,
            executed_at=self._executed_at,
        )
        answerability = assess_answerability(
            (_WEATHER_EVIDENCE, _TRANSPORT_EVIDENCE),
            (weather, transport),
        )
        problems = weather.problems + transport.problems

        if answerability.status is AnswerabilityStatus.UNAVAILABLE:
            return ComponentExecutionOutcome(status=RunStatus.UNAVAILABLE, problems=problems)

        gap_seconds, closest_pair = _closest_observation_pair(
            weather.observations, transport.observations
        )
        snapshot: dict[str, JsonValue] = {
            "independent_observations_only": True,
            "both_sources_usable": answerability.answerable,
            "closest_observation_gap_seconds": gap_seconds,
            "closest_observation_pair": closest_pair,
            "weather": weather.snapshot,
            "realtime_transport": transport.snapshot,
        }
        output = DerivedOutput(
            id="source_readiness",
            version="1",
            state_category=DerivedStateCategory.DERIVED,
            payload=snapshot,
        )
        status = (
            RunStatus.AVAILABLE
            if answerability.status is AnswerabilityStatus.AVAILABLE
            else RunStatus.DEGRADED
        )
        return ComponentExecutionOutcome(
            status=status,
            outputs=(output,),
            problems=problems,
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
        WeatherTransportReadiness(city, executed_at=executed_at),
        inputs=(weather, transport),
        executed_at=executed_at,
    )
