"""Place each gauge's latest level against its own long-term characteristic values."""

from collections import defaultdict
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

KEYS = ("mnw_cm", "mw_cm", "mhw_cm")


class WaterLevelClassAgent:
    """Classify the latest level as below MNW, MNW to MW, MW to MHW or above MHW.

    The thresholds are the gauge's own long-term means (mean low, mean and mean
    high water) as published by the source, so gauges on different waters
    become comparable. Gauges without all three values are `no_reference`;
    nothing is estimated.
    """

    descriptor = ComponentDescriptor(
        id="water_level_class",
        kind=ComponentKind.AGENT,
        version="1",
        inputs=(CapabilityRequirement(capability_id="river_level", version="1"),),
        outputs=(
            ComponentOutput(
                id="water_level_class", version="1", state_category=DerivedStateCategory.DERIVED
            ),
        ),
    )

    def run(self, inputs: tuple[CapabilityInput, ...]) -> ComponentExecutionOutcome:
        item = inputs[0]
        result = provider_read(item)
        if result.availability is Availability.UNAVAILABLE:
            return _unavailable("river_level_unavailable", "no usable water levels")

        reference = _reference(item.payload)
        latest: dict[str, Observation] = {}
        for observation in result.observations:
            if observation.quantity_id != "water_level" or observation.unit != "cm":
                continue
            key = observation.entity.canonical_id
            if key not in latest or observation.observed_at > latest[key].observed_at:
                latest[key] = observation

        gauges: list[JsonValue] = []
        classified = 0
        for entity in sorted(latest):
            obs = latest[entity]
            values, evidence = reference.get(entity, ({}, []))
            entry: dict[str, JsonValue] = {
                "entity": entity,
                "latest": {"value": decimal_text(obs.value), "observed_at": iso(obs.observed_at)},
                "class": "no_reference",
                "reference": None,
                "reference_evidence": list(evidence),
            }
            if len(values) == len(KEYS):
                mnw, mw, mhw = (values[key] for key in KEYS)
                entry["reference"] = {key: decimal_text(values[key]) for key in KEYS}
                entry["class"] = _classify(obs.value, mnw, mw, mhw)
                classified += 1
            gauges.append(entry)

        if classified == 0:
            return _unavailable(
                "no_characteristic_values",
                "no gauge in this read has published MNW, MW and MHW values",
            )
        problems = source_problems(result)
        return ComponentExecutionOutcome(
            status=RunStatus.DEGRADED if problems else RunStatus.AVAILABLE,
            outputs=(
                DerivedOutput(
                    id="water_level_class",
                    version="1",
                    state_category=DerivedStateCategory.DERIVED,
                    payload={"gauges": gauges, "classified": classified},
                ),
            ),
            problems=tuple(problems),
        )


def _classify(value: Decimal, mnw: Decimal, mw: Decimal, mhw: Decimal) -> str:
    if value >= mhw:
        return "above_mhw"
    if value >= mw:
        return "mw_to_mhw"
    if value >= mnw:
        return "mnw_to_mw"
    return "below_mnw"


def _reference(payload: JsonValue) -> dict[str, tuple[dict[str, Decimal], list[str]]]:
    """Characteristic values per entity from the input's reference context."""

    found: dict[str, tuple[dict[str, Decimal], list[str]]] = defaultdict(lambda: ({}, []))
    if not isinstance(payload, dict):
        return {}
    context = payload.get("reference_entities")
    if not isinstance(context, list):
        return {}
    for item in context:
        if not isinstance(item, dict) or not isinstance(item.get("entity"), str):
            continue
        attributes = item.get("attributes")
        values: dict[str, Decimal] = {}
        if isinstance(attributes, dict):
            for key in KEYS:
                raw = attributes.get(key)
                if isinstance(raw, int | float) and not isinstance(raw, bool):
                    number = Decimal(str(raw))
                    # 200.0 -> 200 (normalize() would give 2E+2)
                    values[key] = (
                        number.quantize(Decimal(1))
                        if number == number.to_integral_value()
                        else number
                    )
        evidence = [
            f"{ev['source_id']}:{ev['record_id']}"
            for ev in item.get("evidence", [])  # type: ignore[union-attr]
            if isinstance(ev, dict)
        ]
        found[str(item["entity"])] = (values, evidence)
    return dict(found)


def _unavailable(code: str, message: str) -> ComponentExecutionOutcome:
    return ComponentExecutionOutcome(
        status=RunStatus.UNAVAILABLE,
        problems=(ComponentRunProblem(code=code, message=message),),
    )
