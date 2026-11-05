"""Generic evidence assessment keeps answerability separate from domain analysis."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from urbanium.analysis.evidence import (
    AnswerabilityStatus,
    EvidenceRequirement,
    NumericConstraint,
    assess_answerability,
    assess_evidence,
)
from urbanium.analysis.observation_inputs import observation_input
from urbanium.core.entity import EntityReference
from urbanium.core.provider import (
    Availability,
    Freshness,
    Observation,
    ProviderDescriptor,
    ProviderError,
    ProviderErrorCode,
    ProviderResult,
)
from urbanium.registry import CityRegistry

CITIES = Path(__file__).resolve().parents[1] / "cities"
RECEIVED = datetime(2026, 11, 5, 18, 2, tzinfo=UTC)
EXECUTED = datetime(2026, 11, 5, 18, 5, tzinfo=UTC)


def _city():
    return CityRegistry.from_directory(CITIES).city("berlin")


def _descriptor(capability: str) -> ProviderDescriptor:
    return ProviderDescriptor(
        city_id="berlin",
        source_id="dwd_open_data" if capability == "weather" else "vbb_gtfs_rt",
        capability_id=capability,
        adapter_version="1",
    )


def _observation(
    capability: str,
    *,
    quantity: str,
    unit: str,
    value: str,
) -> Observation:
    return Observation(
        city_id="berlin",
        source_id=_descriptor(capability).source_id,
        capability_id=capability,
        entity=EntityReference(
            city_id="berlin",
            entity_type=("weather_station" if capability == "weather" else "transport_network"),
            entity_id="synthetic",
        ),
        quantity_id=quantity,
        value=Decimal(value),
        unit=unit,
        observed_at=RECEIVED,
        received_at=RECEIVED,
    )


def _input(
    capability: str,
    *,
    quantity: str,
    unit: str,
    value: str,
    availability: Availability = Availability.AVAILABLE,
    freshness: Freshness = Freshness.FRESH,
):
    observations = ()
    error = None
    if availability is not Availability.UNAVAILABLE:
        observations = (
            _observation(
                capability,
                quantity=quantity,
                unit=unit,
                value=value,
            ),
        )
    else:
        freshness = Freshness.UNKNOWN
        error = ProviderError(code=ProviderErrorCode.UPSTREAM, message="synthetic outage")
    result = ProviderResult(
        availability=availability,
        freshness=freshness,
        observations=observations,
        error=error,
    )
    return observation_input(_city(), _descriptor(capability), result, prepared_at=RECEIVED)


def test_assessment_accepts_fresh_matching_measurement() -> None:
    requirement = EvidenceRequirement(
        capability_id="weather",
        quantity_id="air_temperature",
        unit="Cel",
    )

    assessment = assess_evidence(
        _city(),
        _input("weather", quantity="air_temperature", unit="Cel", value="4.2"),
        requirement,
        executed_at=EXECUTED,
    )

    assert assessment.usable is True
    assert assessment.has_measurements is True
    assert assessment.problems == ()
    assert assessment.snapshot["provider"]["source_id"] == "dwd_open_data"
    assert assessment.snapshot["validated_observations"][0]["value"] == "4.2"


def test_stale_evidence_remains_visible_but_is_not_answerable() -> None:
    requirement = EvidenceRequirement(
        capability_id="weather",
        quantity_id="air_temperature",
        unit="Cel",
    )

    assessment = assess_evidence(
        _city(),
        _input(
            "weather",
            quantity="air_temperature",
            unit="Cel",
            value="4.2",
            freshness=Freshness.STALE,
        ),
        requirement,
        executed_at=EXECUTED,
    )
    report = assess_answerability((requirement,), (assessment,))

    assert assessment.has_measurements is True
    assert assessment.usable is False
    assert [problem.code for problem in assessment.problems] == ["weather_stale"]
    assert report.status is AnswerabilityStatus.DEGRADED
    assert report.answerable is False


def test_non_negative_integer_constraint_rejects_fractional_measurement() -> None:
    requirement = EvidenceRequirement(
        capability_id="realtime_transport",
        quantity_id="active_service_alerts",
        unit="1",
        numeric_constraint=NumericConstraint.NON_NEGATIVE_INTEGER,
    )

    assessment = assess_evidence(
        _city(),
        _input(
            "realtime_transport",
            quantity="active_service_alerts",
            unit="1",
            value="1.5",
        ),
        requirement,
        executed_at=EXECUTED,
    )

    assert assessment.has_measurements is False
    assert [problem.code for problem in assessment.problems] == ["realtime_transport_invalid_value"]


def test_malformed_evidence_does_not_echo_unvalidated_provider_data() -> None:
    requirement = EvidenceRequirement(
        capability_id="weather",
        quantity_id="air_temperature",
        unit="Cel",
    )
    item = _input("weather", quantity="air_temperature", unit="Cel", value="4.2")
    malformed = item.model_copy(
        update={
            "payload": {
                **item.payload,
                "provider": {**item.payload["provider"], "city_id": "mainz"},
            }
        }
    )

    assessment = assess_evidence(
        _city(),
        malformed,
        requirement,
        executed_at=EXECUTED,
    )

    assert assessment.usable is False
    assert assessment.has_measurements is False
    assert assessment.snapshot == {"usable": False, "validated_observations": []}
    assert [problem.code for problem in assessment.problems] == ["weather_invalid_evidence"]


def test_answerability_reports_missing_required_evidence_explicitly() -> None:
    weather = EvidenceRequirement(
        capability_id="weather",
        quantity_id="air_temperature",
        unit="Cel",
    )
    transport = EvidenceRequirement(
        capability_id="realtime_transport",
        quantity_id="active_service_alerts",
        unit="1",
        numeric_constraint=NumericConstraint.NON_NEGATIVE_INTEGER,
    )
    weather_assessment = assess_evidence(
        _city(),
        _input("weather", quantity="air_temperature", unit="Cel", value="4.2"),
        weather,
        executed_at=EXECUTED,
    )

    report = assess_answerability((transport, weather), (weather_assessment,))

    assert report.status is AnswerabilityStatus.DEGRADED
    assert report.answerable is False
    assert [item.capability_id for item in report.items] == [
        "realtime_transport",
        "weather",
    ]
    assert report.items[0].problem_codes == ("realtime_transport_missing_evidence",)
    assert report.items[1].usable is True


def test_answerability_is_available_only_when_every_requirement_is_usable() -> None:
    weather = EvidenceRequirement(
        capability_id="weather",
        quantity_id="air_temperature",
        unit="Cel",
    )
    transport = EvidenceRequirement(
        capability_id="realtime_transport",
        quantity_id="active_service_alerts",
        unit="1",
        numeric_constraint=NumericConstraint.NON_NEGATIVE_INTEGER,
    )
    assessments = (
        assess_evidence(
            _city(),
            _input("weather", quantity="air_temperature", unit="Cel", value="4.2"),
            weather,
            executed_at=EXECUTED,
        ),
        assess_evidence(
            _city(),
            _input(
                "realtime_transport",
                quantity="active_service_alerts",
                unit="1",
                value="0",
            ),
            transport,
            executed_at=EXECUTED,
        ),
    )

    report = assess_answerability((weather, transport), assessments)

    assert report.status is AnswerabilityStatus.AVAILABLE
    assert report.answerable is True
    assert all(item.usable for item in report.items)


def test_duplicate_requirement_capabilities_are_rejected() -> None:
    requirement = EvidenceRequirement(
        capability_id="weather",
        quantity_id="air_temperature",
        unit="Cel",
    )

    with pytest.raises(ValueError, match="duplicate evidence requirement"):
        assess_answerability((requirement, requirement), ())


def test_requirement_rejects_empty_unit() -> None:
    with pytest.raises(ValidationError):
        EvidenceRequirement(
            capability_id="weather",
            quantity_id="air_temperature",
            unit="",
        )
