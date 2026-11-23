"""Water-level change per gauge against a measured reference value."""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from pydantic import JsonValue

from urbanium.agents._inputs import decimal_text, iso, provider_read, source_problems
from urbanium.core.component import (
    CapabilityRequirement,
    ComponentDescriptor,
    ComponentKind,
    ComponentOutput,
    DerivedStateCategory,
)
from urbanium.core.execution import (
    CapabilityInput,
    ComponentExecutionOutcome,
    ComponentRunProblem,
    DerivedOutput,
    RunStatus,
)
from urbanium.core.provider import Availability, Observation

WINDOW = timedelta(hours=6)
TOLERANCE = timedelta(minutes=45)
THRESHOLD_CM = Decimal(5)


class WaterLevelTrendAgent:
    """Classify each gauge as rising, falling or steady over six hours.

    The reference is the measured value closest to six hours before the latest
    value, accepted only within ±45 minutes. Without such a value the trend is
    `unknown`; it is never extrapolated from shorter series.
    """

    descriptor = ComponentDescriptor(
        id="water_level_trend",
        kind=ComponentKind.AGENT,
        version="1",
        inputs=(CapabilityRequirement(capability_id="river_level", version="1"),),
        outputs=(
            ComponentOutput(
                id="water_level_trend", version="1", state_category=DerivedStateCategory.DERIVED
            ),
        ),
    )

    def run(self, inputs: tuple[CapabilityInput, ...]) -> ComponentExecutionOutcome:
        result = provider_read(inputs[0])
        if result.availability is Availability.UNAVAILABLE:
            return ComponentExecutionOutcome(
                status=RunStatus.UNAVAILABLE,
                problems=(
                    ComponentRunProblem(
                        code="river_level_unavailable", message="no usable water levels"
                    ),
                ),
            )

        series: dict[str, list[Observation]] = defaultdict(list)
        for observation in result.observations:
            if observation.quantity_id == "water_level":
                series[observation.entity.canonical_id].append(observation)

        gauges: list[JsonValue] = []
        unknown: list[str] = []
        for entity in sorted(series):
            item = _trend(entity, sorted(series[entity], key=lambda obs: obs.observed_at))
            if item["trend"] == "unknown":
                unknown.append(entity)
            gauges.append(item)

        determinable = len(gauges) - len(unknown)
        problems = []
        if unknown:
            problems.append(
                ComponentRunProblem(
                    code="trend_not_determinable",
                    message="no reference value about 6 h earlier for: " + ", ".join(unknown),
                )
            )
        if determinable == 0:
            return ComponentExecutionOutcome(status=RunStatus.UNAVAILABLE, problems=tuple(problems))
        problems.extend(source_problems(result))
        payload: dict[str, JsonValue] = {
            "window_hours": int(WINDOW.total_seconds() // 3600),
            "tolerance_minutes": int(TOLERANCE.total_seconds() // 60),
            "threshold_cm": decimal_text(THRESHOLD_CM),
            "gauges": gauges,
        }
        return ComponentExecutionOutcome(
            status=RunStatus.DEGRADED if problems else RunStatus.AVAILABLE,
            outputs=(
                DerivedOutput(
                    id="water_level_trend",
                    version="1",
                    state_category=DerivedStateCategory.DERIVED,
                    payload=payload,
                ),
            ),
            problems=tuple(problems),
        )


def _trend(entity: str, ordered: list[Observation]) -> dict[str, JsonValue]:
    latest = ordered[-1]
    target = latest.observed_at - WINDOW
    candidates = [obs for obs in ordered[:-1] if abs(obs.observed_at - target) <= TOLERANCE]
    item: dict[str, JsonValue] = {
        "entity": entity,
        "unit": latest.unit,
        "latest": {"value": decimal_text(latest.value), "observed_at": iso(latest.observed_at)},
        "reference_at": None,
        "reference_value": None,
        "change": None,
        "trend": "unknown",
    }
    if not candidates:
        return item
    reference = min(candidates, key=lambda obs: (abs(obs.observed_at - target), obs.observed_at))
    change = latest.value - reference.value
    item["reference_at"] = iso(reference.observed_at)
    item["reference_value"] = decimal_text(reference.value)
    item["change"] = decimal_text(change)
    if change >= THRESHOLD_CM:
        item["trend"] = "rising"
    elif change <= -THRESHOLD_CM:
        item["trend"] = "falling"
    else:
        item["trend"] = "steady"
    return item


__all__ = ["WaterLevelTrendAgent"]
