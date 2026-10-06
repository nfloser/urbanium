from datetime import UTC, datetime

import pytest

from urbanium.core.component import (
    CapabilityRequirement,
    ComponentDescriptor,
    ComponentKind,
    ComponentOutput,
    ComponentResolution,
    DerivedStateCategory,
)
from urbanium.core.execution import (
    CapabilityInputProvenance,
    ComponentRunProblem,
    ComponentRunProvenance,
    ComponentRunResult,
    DerivedOutput,
    RunStatus,
    validate_component_run,
)


def descriptor() -> ComponentDescriptor:
    return ComponentDescriptor(
        id="weather_summary",
        kind=ComponentKind.AGENT,
        version="2",
        inputs=(CapabilityRequirement(capability_id="weather", version="1"),),
        outputs=(
            ComponentOutput(
                id="summary",
                version="3",
                state_category=DerivedStateCategory.DERIVED,
            ),
        ),
    )


def resolution(*, available: bool = True) -> ComponentResolution:
    unavailable = ()
    if not available:
        from urbanium.core.component import ResolutionReasonCode, UnavailableCapability

        unavailable = (
            UnavailableCapability(
                capability_id="weather",
                reason=ResolutionReasonCode.MISSING_CAPABILITY,
                required_version="1",
            ),
        )
    return ComponentResolution(
        city_id="berlin",
        component_id="weather_summary",
        component_version="2",
        unavailable=unavailable,
    )


def provenance() -> ComponentRunProvenance:
    return ComponentRunProvenance(
        city_id="berlin",
        component_id="weather_summary",
        component_version="2",
        inputs=(CapabilityInputProvenance(capability_id="weather", version="1"),),
        executed_at=datetime(2026, 10, 6, 8, 30, tzinfo=UTC),
    )


def output(
    *,
    output_id: str = "summary",
    version: str = "3",
    state_category: DerivedStateCategory = DerivedStateCategory.DERIVED,
) -> DerivedOutput:
    return DerivedOutput(
        id=output_id,
        version=version,
        state_category=state_category,
    )


def problem() -> ComponentRunProblem:
    return ComponentRunProblem(code="execution_error", message="deterministic model failed")


def test_run_states_have_explicit_output_and_problem_invariants() -> None:
    with pytest.raises(ValueError, match="available run requires outputs and no problems"):
        ComponentRunResult(
            status=RunStatus.AVAILABLE,
            provenance=provenance(),
        )

    degraded = ComponentRunResult(
        status=RunStatus.DEGRADED,
        provenance=provenance(),
        outputs=(output(),),
        problems=(problem(),),
    )
    assert degraded.status is RunStatus.DEGRADED

    with pytest.raises(ValueError, match="unavailable run requires no outputs and problems"):
        ComponentRunResult(
            status=RunStatus.UNAVAILABLE,
            provenance=provenance(),
            outputs=(output(),),
            problems=(problem(),),
        )

    unavailable = ComponentRunResult(
        status=RunStatus.UNAVAILABLE,
        provenance=provenance(),
        problems=(problem(),),
    )
    assert unavailable.outputs == ()


def test_run_provenance_requires_timezone_aware_execution_time() -> None:
    with pytest.raises(ValueError, match="executed_at must be timezone-aware"):
        ComponentRunProvenance(
            city_id="berlin",
            component_id="weather_summary",
            component_version="2",
            inputs=(CapabilityInputProvenance(capability_id="weather", version="1"),),
            executed_at=datetime(2026, 10, 6, 8, 30),
        )


def test_run_result_rejects_duplicate_output_ids() -> None:
    with pytest.raises(ValueError, match="duplicate run output ids: summary"):
        ComponentRunResult(
            status=RunStatus.AVAILABLE,
            provenance=provenance(),
            outputs=(output(), output(version="4")),
        )


def test_declared_output_and_exact_provenance_validate() -> None:
    result = ComponentRunResult(
        status=RunStatus.AVAILABLE,
        provenance=provenance(),
        outputs=(output(),),
    )

    validate_component_run(descriptor(), resolution(), result)


@pytest.mark.parametrize(
    ("derived_output", "message"),
    [
        (output(output_id="not_declared"), "is not declared"),
        (output(version="4"), "version does not match"),
        (
            output(state_category=DerivedStateCategory.FORECAST),
            "state category does not match",
        ),
    ],
)
def test_undeclared_or_mismatched_outputs_are_rejected(
    derived_output: DerivedOutput,
    message: str,
) -> None:
    result = ComponentRunResult(
        status=RunStatus.AVAILABLE,
        provenance=provenance(),
        outputs=(derived_output,),
    )

    with pytest.raises(ValueError, match=message):
        validate_component_run(descriptor(), resolution(), result)


def test_component_and_input_provenance_must_match_the_resolved_descriptor() -> None:
    wrong_component = provenance().model_copy(update={"component_version": "9"})
    result = ComponentRunResult(
        status=RunStatus.AVAILABLE,
        provenance=wrong_component,
        outputs=(output(),),
    )

    with pytest.raises(ValueError, match="component identity"):
        validate_component_run(descriptor(), resolution(), result)

    wrong_inputs = provenance().model_copy(
        update={
            "inputs": (
                CapabilityInputProvenance(capability_id="weather", version="2"),
            )
        }
    )
    result = ComponentRunResult(
        status=RunStatus.AVAILABLE,
        provenance=wrong_inputs,
        outputs=(output(),),
    )

    with pytest.raises(ValueError, match="capability inputs"):
        validate_component_run(descriptor(), resolution(), result)


def test_unresolved_component_cannot_report_derived_outputs() -> None:
    result = ComponentRunResult(
        status=RunStatus.AVAILABLE,
        provenance=provenance(),
        outputs=(output(),),
    )

    with pytest.raises(ValueError, match="unresolved component cannot produce outputs"):
        validate_component_run(descriptor(), resolution(available=False), result)
