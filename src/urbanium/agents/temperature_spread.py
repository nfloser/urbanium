"""Temperature spread across a city's stations at one shared measurement time."""

from collections import defaultdict
from datetime import datetime
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
from urbanium.core.provider import Availability

MIN_STATIONS = 3


class TemperatureSpreadAgent:
    """Compare air temperature between stations that report the same timestamp.

    Only values sharing one measurement time are compared; stations without a
    value at that time are listed, never interpolated. The spread describes
    station differences, which also reflect elevation and surroundings. It is
    not by itself evidence of an urban heat island.
    """

    descriptor = ComponentDescriptor(
        id="temperature_spread",
        kind=ComponentKind.AGENT,
        version="1",
        inputs=(CapabilityRequirement(capability_id="weather", version="1"),),
        outputs=(
            ComponentOutput(
                id="temperature_spread", version="1", state_category=DerivedStateCategory.DERIVED
            ),
        ),
    )

    def run(self, inputs: tuple[CapabilityInput, ...]) -> ComponentExecutionOutcome:
        result = provider_read(inputs[0])
        if result.availability is Availability.UNAVAILABLE:
            return _unavailable("weather_unavailable", "no usable weather observations")

        slots: dict[datetime, dict[str, Decimal]] = defaultdict(dict)
        units: set[str] = set()
        for observation in result.observations:
            if observation.quantity_id != "air_temperature":
                continue
            slots[observation.observed_at][observation.entity.canonical_id] = observation.value
            units.add(observation.unit)
        if len(units) > 1:
            return _unavailable("mixed_units", "air temperature arrives in mixed units")

        chosen = next(
            (
                moment
                for moment in sorted(slots, reverse=True)
                if len(slots[moment]) >= MIN_STATIONS
            ),
            None,
        )
        if chosen is None:
            best = max((len(values) for values in slots.values()), default=0)
            return _unavailable(
                "insufficient_aligned_stations",
                f"at most {best} station(s) share a measurement time; {MIN_STATIONS} required",
            )

        values = slots[chosen]
        reporting = {entity for slot in slots.values() for entity in slot}
        ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
        low, high = ordered[0], ordered[-1]
        mean = sum(values.values(), Decimal(0)) / len(values)
        not_aligned: list[JsonValue] = [*sorted(reporting - set(values))]
        payload: dict[str, JsonValue] = {
            "observed_at": iso(chosen),
            "unit": units.pop(),
            "station_count": len(values),
            "min": {"entity": low[0], "value": decimal_text(low[1])},
            "max": {"entity": high[0], "value": decimal_text(high[1])},
            "spread": decimal_text(high[1] - low[1]),
            "mean": decimal_text(mean, "0.01"),
            "values": [
                {"entity": entity, "value": decimal_text(value)}
                for entity, value in sorted(values.items())
            ],
            "not_aligned": not_aligned,
        }
        problems = source_problems(result)
        return ComponentExecutionOutcome(
            status=RunStatus.DEGRADED if problems else RunStatus.AVAILABLE,
            outputs=(
                DerivedOutput(
                    id="temperature_spread",
                    version="1",
                    state_category=DerivedStateCategory.DERIVED,
                    payload=payload,
                ),
            ),
            problems=tuple(problems),
        )


def _unavailable(code: str, message: str) -> ComponentExecutionOutcome:
    return ComponentExecutionOutcome(
        status=RunStatus.UNAVAILABLE,
        problems=(ComponentRunProblem(code=code, message=message),),
    )
