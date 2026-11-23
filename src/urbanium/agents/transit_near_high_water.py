"""First cross-domain agent: gauges above mean high water near stops named in alerts.

The rule flags spatial co-occurrence for a human to check. It does not claim
that high water caused an alert or that a stop is affected: an alert selector
naming a stop is a source reference, and nearness is not dependency.
"""

from decimal import Decimal

from pydantic import JsonValue

from urbanium.agents._inputs import decimal_text, iso, provider_read
from urbanium.agents.water_level_class import KEYS, _classify, _reference
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
from urbanium.core.geometry import Wgs84Point, distance_km
from urbanium.core.provider import Availability, Observation

RADIUS_KM = Decimal("1.0")


class TransitNearHighWaterAgent:
    """List stops named in current alerts within 1 km of a gauge above its MHW."""

    descriptor = ComponentDescriptor(
        id="transit_near_high_water",
        kind=ComponentKind.AGENT,
        version="1",
        inputs=(
            CapabilityRequirement(capability_id="realtime_transport", version="1"),
            CapabilityRequirement(capability_id="river_level", version="1"),
        ),
        outputs=(
            ComponentOutput(
                id="transit_near_high_water",
                version="1",
                state_category=DerivedStateCategory.DERIVED,
            ),
        ),
    )

    def run(self, inputs: tuple[CapabilityInput, ...]) -> ComponentExecutionOutcome:
        by_capability = {item.capability_id: item for item in inputs}
        river_input = by_capability["river_level"]
        transport_input = by_capability["realtime_transport"]
        river = provider_read(river_input)
        transport = provider_read(transport_input)
        if river.availability is Availability.UNAVAILABLE:
            return _unavailable("river_level_unavailable", "no usable water levels")
        if transport.availability is Availability.UNAVAILABLE:
            return _unavailable("realtime_transport_unavailable", "no usable alert feed")

        gauge_reference = _reference(river_input.payload)
        gauge_points = _points(river_input.payload)
        stop_points = _points(transport_input.payload)

        latest: dict[str, Observation] = {}
        for obs in river.observations:
            if obs.quantity_id == "water_level" and obs.unit == "cm":
                current = latest.get(obs.entity.canonical_id)
                if current is None or obs.observed_at > current.observed_at:
                    latest[obs.entity.canonical_id] = obs

        assessed = 0
        high: list[tuple[str, Observation, Decimal]] = []
        for entity, obs in sorted(latest.items()):
            values, _ = gauge_reference.get(entity, ({}, []))
            if len(values) != len(KEYS):
                continue
            assessed += 1
            if _classify(obs.value, *(values[key] for key in KEYS)) == "above_mhw":
                high.append((entity, obs, values["mhw_cm"]))
        if assessed == 0:
            return _unavailable(
                "no_characteristic_values", "no gauge has published MNW, MW and MHW values"
            )

        alert_counts = {
            obs.entity.canonical_id: obs.value
            for obs in transport.observations
            if obs.quantity_id == "alert_mentions"
        }
        pairs: list[JsonValue] = []
        for entity, obs, mhw in high:
            gauge_point = gauge_points.get(entity)
            if gauge_point is None:
                continue
            for stop, count in sorted(alert_counts.items()):
                stop_point = stop_points.get(stop)
                if stop_point is None:
                    continue
                distance = Decimal(str(round(distance_km(gauge_point, stop_point), 3)))
                if distance <= RADIUS_KM:
                    pairs.append(
                        {
                            "gauge": entity,
                            "stop": stop,
                            "distance_km": decimal_text(distance),
                            "level_cm": decimal_text(obs.value),
                            "mhw_cm": decimal_text(mhw),
                            "observed_at": iso(obs.observed_at),
                            "alert_count": decimal_text(count),
                        }
                    )
        payload: dict[str, JsonValue] = {
            "radius_km": decimal_text(RADIUS_KM),
            "gauges_assessed": assessed,
            "gauges_above_mhw": [entity for entity, _, _ in high],
            "stops_in_alerts": len(alert_counts),
            "pairs": pairs,
        }
        problems = [
            ComponentRunProblem(code="source_degraded", message=item.error.message)
            for item in (river, transport)
            if item.availability is Availability.DEGRADED and item.error is not None
        ]
        return ComponentExecutionOutcome(
            status=RunStatus.DEGRADED if problems else RunStatus.AVAILABLE,
            outputs=(
                DerivedOutput(
                    id="transit_near_high_water",
                    version="1",
                    state_category=DerivedStateCategory.DERIVED,
                    payload=payload,
                ),
            ),
            problems=tuple(problems),
        )


def _points(payload: JsonValue) -> dict[str, Wgs84Point]:
    found: dict[str, Wgs84Point] = {}
    context = payload.get("reference_entities") if isinstance(payload, dict) else None
    if not isinstance(context, list):
        return found
    for item in context:
        point = item.get("point") if isinstance(item, dict) else None
        if not isinstance(item, dict) or not isinstance(point, dict):
            continue
        latitude, longitude = point.get("latitude"), point.get("longitude")
        if not isinstance(latitude, int | float) or not isinstance(longitude, int | float):
            continue
        try:
            found[str(item.get("entity"))] = Wgs84Point(
                latitude=float(latitude), longitude=float(longitude)
            )
        except ValueError:
            continue
    return found


def _unavailable(code: str, message: str) -> ComponentExecutionOutcome:
    return ComponentExecutionOutcome(
        status=RunStatus.UNAVAILABLE,
        problems=(ComponentRunProblem(code=code, message=message),),
    )
