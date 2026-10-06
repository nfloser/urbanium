from pathlib import Path

import pytest

from urbanium.core.component import (
    CapabilityRequirement,
    ComponentDescriptor,
    ComponentKind,
    ComponentOutput,
    ComponentRegistry,
    DerivedStateCategory,
    ResolutionReasonCode,
    resolve_component,
)
from urbanium.core.city import CapabilitySupport
from urbanium.registry import CityRegistry

ROOT = Path(__file__).resolve().parents[1]
CITIES = ROOT / "cities"


def descriptor(
    *,
    component_id: str = "weather_summary",
    kind: ComponentKind = ComponentKind.AGENT,
    version: str = "1",
    inputs: tuple[CapabilityRequirement, ...] = (),
) -> ComponentDescriptor:
    return ComponentDescriptor(
        id=component_id,
        kind=kind,
        version=version,
        inputs=inputs,
        outputs=(
            ComponentOutput(
                id="summary",
                version="1",
                state_category=DerivedStateCategory.DERIVED,
            ),
        ),
    )


def test_descriptor_rejects_duplicate_requirements_and_outputs() -> None:
    weather_v1 = CapabilityRequirement(capability_id="weather", version="1")

    with pytest.raises(ValueError, match="duplicate capability requirements: weather"):
        ComponentDescriptor(
            id="duplicate_inputs",
            kind=ComponentKind.AGENT,
            version="1",
            inputs=(weather_v1, CapabilityRequirement(capability_id="weather", version="2")),
            outputs=(),
        )

    with pytest.raises(ValueError, match="duplicate output ids: result"):
        ComponentDescriptor(
            id="duplicate_outputs",
            kind=ComponentKind.MODEL,
            version="1",
            inputs=(),
            outputs=(
                ComponentOutput(
                    id="result",
                    version="1",
                    state_category=DerivedStateCategory.FORECAST,
                ),
                ComponentOutput(
                    id="result",
                    version="2",
                    state_category=DerivedStateCategory.SCENARIO,
                ),
            ),
        )


def test_outputs_are_restricted_to_derived_state_categories() -> None:
    with pytest.raises(ValueError):
        ComponentOutput(id="result", version="1", state_category="live")


def test_component_registry_order_and_lookup_are_deterministic() -> None:
    model = descriptor(component_id="water_model", kind=ComponentKind.MODEL, version="2")
    agent = descriptor(component_id="weather_agent", kind=ComponentKind.AGENT, version="1")

    registry = ComponentRegistry([model, agent])

    assert [(item.kind, item.id, item.version) for item in registry.descriptors] == [
        (ComponentKind.AGENT, "weather_agent", "1"),
        (ComponentKind.MODEL, "water_model", "2"),
    ]
    assert registry.descriptor(ComponentKind.MODEL, "water_model", "2") is model

    with pytest.raises(ValueError, match="duplicate component descriptor"):
        ComponentRegistry([agent, agent])


def test_resolution_differs_by_city_without_city_specific_logic() -> None:
    cities = CityRegistry.from_directory(CITIES)
    component = descriptor(
        inputs=(
            CapabilityRequirement(capability_id="weather", version="1"),
            CapabilityRequirement(capability_id="realtime_transport", version="1"),
        )
    )

    berlin = resolve_component(cities.city("berlin"), component)
    mainz = resolve_component(cities.city("mainz"), component)

    assert berlin.available
    assert berlin.unavailable == ()

    assert not mainz.available
    assert len(mainz.unavailable) == 1
    unavailable = mainz.unavailable[0]
    assert unavailable.capability_id == "realtime_transport"
    assert unavailable.reason is ResolutionReasonCode.NOT_CONFIGURED
    assert unavailable.support is CapabilitySupport.CANDIDATE
    assert unavailable.required_version == "1"
    assert unavailable.available_version == "1"


def test_resolution_reports_missing_and_version_mismatched_contracts() -> None:
    berlin = CityRegistry.from_directory(CITIES).city("berlin")
    component = descriptor(
        inputs=(
            CapabilityRequirement(capability_id="noise", version="1"),
            CapabilityRequirement(capability_id="weather", version="2"),
        )
    )

    resolution = resolve_component(berlin, component)

    assert not resolution.available
    assert [item.capability_id for item in resolution.unavailable] == ["noise", "weather"]

    missing, mismatch = resolution.unavailable
    assert missing.reason is ResolutionReasonCode.MISSING_CAPABILITY
    assert missing.available_version is None
    assert missing.support is None

    assert mismatch.reason is ResolutionReasonCode.VERSION_MISMATCH
    assert mismatch.required_version == "2"
    assert mismatch.available_version == "1"
    assert mismatch.support is CapabilitySupport.CONFIGURED
