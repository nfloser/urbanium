from datetime import UTC, datetime
from pathlib import Path

import pytest

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
    execute_component,
)
from urbanium.registry import CityRegistry

ROOT = Path(__file__).resolve().parents[1]
CITIES = ROOT / "cities"
EXECUTED_AT = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def descriptor(
    *requirements: CapabilityRequirement,
) -> ComponentDescriptor:
    return ComponentDescriptor(
        id="mobility_weather_signal",
        kind=ComponentKind.AGENT,
        version="1",
        inputs=requirements,
        outputs=(
            ComponentOutput(
                id="signal",
                version="1",
                state_category=DerivedStateCategory.DERIVED,
            ),
        ),
    )


def available_outcome() -> ComponentExecutionOutcome:
    return ComponentExecutionOutcome(
        status=RunStatus.AVAILABLE,
        outputs=(
            DerivedOutput(
                id="signal",
                version="1",
                state_category=DerivedStateCategory.DERIVED,
                payload={"score": 0.75},
            ),
        ),
    )


class RecordingComponent:
    def __init__(
        self,
        component_descriptor: ComponentDescriptor,
        outcome: ComponentExecutionOutcome,
    ) -> None:
        self._descriptor = component_descriptor
        self._outcome = outcome
        self.calls = 0
        self.received_inputs: tuple[CapabilityInput, ...] | None = None

    @property
    def descriptor(self) -> ComponentDescriptor:
        return self._descriptor

    def run(self, inputs: tuple[CapabilityInput, ...]) -> ComponentExecutionOutcome:
        self.calls += 1
        self.received_inputs = inputs
        return self._outcome


class FailingComponent(RecordingComponent):
    def run(self, inputs: tuple[CapabilityInput, ...]) -> ComponentExecutionOutcome:
        self.calls += 1
        raise RuntimeError("implementation defect")


def test_executor_runs_only_where_city_capabilities_resolve() -> None:
    cities = CityRegistry.from_directory(CITIES)
    component_descriptor = descriptor(
        CapabilityRequirement(capability_id="weather", version="1"),
        CapabilityRequirement(capability_id="realtime_transport", version="1"),
    )
    inputs = (
        CapabilityInput(
            capability_id="weather",
            version="1",
            payload={"air_temperature_c": 12.5},
        ),
        CapabilityInput(
            capability_id="realtime_transport",
            version="1",
            payload={"active": True},
        ),
    )

    berlin_component = RecordingComponent(component_descriptor, available_outcome())
    berlin = execute_component(
        cities.city("berlin"),
        berlin_component,
        inputs=inputs,
        executed_at=EXECUTED_AT,
    )

    assert berlin.resolution.available
    assert berlin.run is not None
    assert berlin_component.calls == 1
    assert berlin.run.provenance.city_id == "berlin"
    assert berlin.run.provenance.executed_at == EXECUTED_AT
    assert [(item.capability_id, item.version) for item in berlin.run.provenance.inputs] == [
        ("realtime_transport", "1"),
        ("weather", "1"),
    ]
    assert berlin.run.outputs[0].payload == {"score": 0.75}

    mainz_component = RecordingComponent(component_descriptor, available_outcome())
    mainz = execute_component(
        cities.city("mainz"),
        mainz_component,
        inputs=inputs,
        executed_at=EXECUTED_AT,
    )

    assert not mainz.resolution.available
    assert mainz.run is None
    assert mainz_component.calls == 0


@pytest.mark.parametrize(
    "inputs",
    [
        (),
        (
            CapabilityInput(
                capability_id="weather",
                version="2",
                payload={"air_temperature_c": 12.5},
            ),
        ),
        (
            CapabilityInput(
                capability_id="weather",
                version="1",
                payload={"air_temperature_c": 12.5},
            ),
            CapabilityInput(capability_id="noise", version="1", payload={"db": 70}),
        ),
    ],
)
def test_executor_rejects_missing_extra_or_version_mismatched_inputs(
    inputs: tuple[CapabilityInput, ...],
) -> None:
    city = CityRegistry.from_directory(CITIES).city("berlin")
    component = RecordingComponent(
        descriptor(CapabilityRequirement(capability_id="weather", version="1")),
        available_outcome(),
    )

    with pytest.raises(ValueError, match="capability inputs do not match"):
        execute_component(city, component, inputs=inputs, executed_at=EXECUTED_AT)

    assert component.calls == 0


def test_executor_rejects_duplicate_capability_inputs() -> None:
    city = CityRegistry.from_directory(CITIES).city("berlin")
    component = RecordingComponent(
        descriptor(CapabilityRequirement(capability_id="weather", version="1")),
        available_outcome(),
    )
    inputs = (
        CapabilityInput(capability_id="weather", version="1", payload={"value": 1}),
        CapabilityInput(capability_id="weather", version="1", payload={"value": 2}),
    )

    with pytest.raises(ValueError, match="duplicate capability input ids: weather"):
        execute_component(city, component, inputs=inputs, executed_at=EXECUTED_AT)

    assert component.calls == 0


def test_runtime_unavailable_is_distinct_from_failed_resolution() -> None:
    city = CityRegistry.from_directory(CITIES).city("berlin")
    component = RecordingComponent(
        descriptor(CapabilityRequirement(capability_id="weather", version="1")),
        ComponentExecutionOutcome(
            status=RunStatus.UNAVAILABLE,
            problems=(
                ComponentRunProblem(
                    code="model_unavailable",
                    message="model dependency unavailable",
                ),
            ),
        ),
    )

    attempt = execute_component(
        city,
        component,
        inputs=(
            CapabilityInput(
                capability_id="weather",
                version="1",
                payload={"air_temperature_c": 12.5},
            ),
        ),
        executed_at=EXECUTED_AT,
    )

    assert attempt.resolution.available
    assert attempt.run is not None
    assert attempt.run.status is RunStatus.UNAVAILABLE
    assert attempt.run.outputs == ()
    assert component.calls == 1


def test_invalid_execution_time_is_rejected_before_invocation() -> None:
    city = CityRegistry.from_directory(CITIES).city("berlin")
    component = RecordingComponent(
        descriptor(CapabilityRequirement(capability_id="weather", version="1")),
        available_outcome(),
    )

    with pytest.raises(ValueError, match="executed_at must be timezone-aware"):
        execute_component(
            city,
            component,
            inputs=(
                CapabilityInput(
                    capability_id="weather",
                    version="1",
                    payload={"air_temperature_c": 12.5},
                ),
            ),
            executed_at=datetime(2026, 10, 6, 9, 0),
        )

    assert component.calls == 0


def test_unexpected_component_exceptions_propagate() -> None:
    city = CityRegistry.from_directory(CITIES).city("berlin")
    component = FailingComponent(
        descriptor(CapabilityRequirement(capability_id="weather", version="1")),
        available_outcome(),
    )

    with pytest.raises(RuntimeError, match="implementation defect"):
        execute_component(
            city,
            component,
            inputs=(
                CapabilityInput(
                    capability_id="weather",
                    version="1",
                    payload={"air_temperature_c": 12.5},
                ),
            ),
            executed_at=EXECUTED_AT,
        )


def test_payloads_are_json_safe() -> None:
    with pytest.raises(ValueError):
        CapabilityInput(
            capability_id="weather",
            version="1",
            payload=object(),
        )

    with pytest.raises(ValueError):
        DerivedOutput(
            id="signal",
            version="1",
            state_category=DerivedStateCategory.DERIVED,
            payload=object(),
        )
