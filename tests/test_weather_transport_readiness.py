"""Readiness snapshots never turn independent source evidence into an impact claim."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from urbanium.analysis.observation_inputs import observation_input
from urbanium.analysis.weather_transport_readiness import assess_weather_transport_readiness
from urbanium.core.entity import EntityReference
from urbanium.core.execution import RunStatus
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
OBSERVED = datetime(2026, 10, 24, 9, 10, tzinfo=UTC)
RECEIVED = datetime(2026, 10, 24, 9, 12, tzinfo=UTC)
EXECUTED = datetime(2026, 10, 24, 9, 15, tzinfo=UTC)


def descriptor(capability: str) -> ProviderDescriptor:
    return ProviderDescriptor(
        city_id="berlin",
        source_id="dwd_open_data" if capability == "weather" else "vbb_gtfs_rt",
        capability_id=capability,
        adapter_version="1.0.0",
    )


def observation(
    capability: str,
    *,
    value: str = "0",
    unit: str | None = None,
    quantity: str | None = None,
    entity_id: str | None = None,
) -> Observation:
    weather = capability == "weather"
    return Observation(
        city_id="berlin",
        source_id=descriptor(capability).source_id,
        capability_id=capability,
        entity=EntityReference(
            city_id="berlin",
            entity_type="weather_station" if weather else "transport_network",
            entity_id=entity_id or ("berlin_tempelhof" if weather else "vbb_network"),
        ),
        quantity_id=quantity or ("air_temperature" if weather else "active_service_alerts"),
        value=Decimal(value),
        unit=unit or ("Cel" if weather else "1"),
        observed_at=OBSERVED,
        received_at=RECEIVED,
        quality_scheme="synthetic_quality",
        quality_code="ok",
    )


def evidence(
    capability: str,
    *,
    availability: Availability = Availability.AVAILABLE,
    freshness: Freshness = Freshness.FRESH,
    observations: tuple[Observation, ...] | None = None,
):
    city = CityRegistry.from_directory(CITIES).city("berlin")
    if observations is None:
        observations = (observation(capability),)
    error = None
    if availability is not Availability.AVAILABLE:
        error = ProviderError(code=ProviderErrorCode.UPSTREAM, message="synthetic upstream issue")
    if availability is Availability.UNAVAILABLE:
        observations = ()
        freshness = Freshness.UNKNOWN
    result = ProviderResult(
        availability=availability,
        freshness=freshness,
        observations=observations,
        error=error,
    )
    return observation_input(city, descriptor(capability), result, prepared_at=RECEIVED)


def assess(weather, transport, *, city_id: str = "berlin"):
    city = CityRegistry.from_directory(CITIES).city(city_id)
    return assess_weather_transport_readiness(
        city, weather=weather, transport=transport, executed_at=EXECUTED
    )


def test_fresh_sources_report_independent_evidence_without_causal_claims() -> None:
    attempt = assess(
        evidence("weather", observations=(observation("weather", value="0.00"),)),
        evidence("realtime_transport", observations=(observation("realtime_transport"),)),
    )

    assert attempt.resolution.available
    assert attempt.run is not None
    assert attempt.run.status is RunStatus.AVAILABLE
    assert attempt.run.provenance.city_id == "berlin"
    assert [(item.capability_id, item.version) for item in attempt.run.provenance.inputs] == [
        ("realtime_transport", "1"),
        ("weather", "1"),
    ]
    output = attempt.run.outputs[0]
    assert (output.id, output.version, output.state_category.value) == (
        "source_readiness",
        "1",
        "derived",
    )
    snapshot = output.payload
    assert snapshot["independent_observations_only"] is True
    assert snapshot["both_sources_usable"] is True
    assert "caused" not in str(snapshot).lower()
    weather = snapshot["weather"]
    assert weather["provider"]["source_id"] == "dwd_open_data"
    assert weather["read"]["availability"] == "available"
    assert weather["read"]["freshness"] == "fresh"
    assert weather["validated_observations"][0]["value"] == "0.00"
    assert weather["validated_observations"][0]["quality_code"] == "ok"
    assert weather["validated_observations"][0]["observed_at"] == OBSERVED.isoformat().replace(
        "+00:00", "Z"
    )
    transport = snapshot["realtime_transport"]
    assert transport["provider"]["source_id"] == "vbb_gtfs_rt"
    assert transport["validated_observations"][0]["value"] == "0"


def test_output_is_stable_when_provider_observations_arrive_in_different_order() -> None:
    first = observation("weather", value="1", entity_id="station_a")
    second = observation("weather", value="2", entity_id="station_b")
    forward = assess(
        evidence("weather", observations=(first, second)), evidence("realtime_transport")
    )
    backward = assess(
        evidence("weather", observations=(second, first)), evidence("realtime_transport")
    )

    assert forward.run is not None and backward.run is not None
    a = forward.run.outputs[0].payload["weather"]["validated_observations"]
    b = backward.run.outputs[0].payload["weather"]["validated_observations"]
    assert a == b
    assert [item["entity"]["entity_id"] for item in a] == ["station_a", "station_b"]


def test_stale_weather_keeps_observations_but_degrades_readiness() -> None:
    attempt = assess(evidence("weather", freshness=Freshness.STALE), evidence("realtime_transport"))

    assert attempt.run is not None
    assert attempt.run.status is RunStatus.DEGRADED
    assert [problem.code for problem in attempt.run.problems] == ["weather_stale"]
    snapshot = attempt.run.outputs[0].payload
    assert snapshot["both_sources_usable"] is False
    assert snapshot["weather"]["read"]["freshness"] == "stale"
    assert snapshot["weather"]["validated_observations"][0]["value"] == "0"


def test_degraded_provider_retains_error_and_evidence() -> None:
    attempt = assess(
        evidence("weather", availability=Availability.DEGRADED),
        evidence("realtime_transport"),
    )

    assert attempt.run is not None
    assert attempt.run.status is RunStatus.DEGRADED
    assert [problem.code for problem in attempt.run.problems] == ["weather_degraded"]
    weather = attempt.run.outputs[0].payload["weather"]
    assert weather["read"]["error"]["code"] == "upstream"
    assert len(weather["validated_observations"]) == 1


def test_one_unavailable_provider_does_not_fabricate_an_observation() -> None:
    attempt = assess(
        evidence("weather"),
        evidence("realtime_transport", availability=Availability.UNAVAILABLE),
    )

    assert attempt.run is not None
    assert attempt.run.status is RunStatus.DEGRADED
    assert [problem.code for problem in attempt.run.problems] == ["realtime_transport_unavailable"]
    transport = attempt.run.outputs[0].payload["realtime_transport"]
    assert transport["validated_observations"] == []
    assert transport["read"]["observations"] == []
    assert transport["read"]["error"]["code"] == "upstream"


def test_both_unavailable_sources_produce_no_derived_output() -> None:
    attempt = assess(
        evidence("weather", availability=Availability.UNAVAILABLE),
        evidence("realtime_transport", availability=Availability.UNAVAILABLE),
    )

    assert attempt.run is not None
    assert attempt.run.status is RunStatus.UNAVAILABLE
    assert attempt.run.outputs == ()
    assert [problem.code for problem in attempt.run.problems] == [
        "weather_unavailable",
        "realtime_transport_unavailable",
    ]


def test_wrong_unit_and_nonintegral_alert_count_are_not_usable_measurements() -> None:
    attempt = assess(
        evidence("weather", observations=(observation("weather", unit="K"),)),
        evidence(
            "realtime_transport",
            observations=(observation("realtime_transport", value="1.5"),),
        ),
    )

    assert attempt.run is not None
    assert attempt.run.status is RunStatus.UNAVAILABLE
    assert attempt.run.outputs == ()
    assert [problem.code for problem in attempt.run.problems] == [
        "weather_invalid_unit",
        "realtime_transport_invalid_value",
    ]


def test_unrelated_quantities_cannot_satisfy_required_measurement() -> None:
    attempt = assess(
        evidence("weather", observations=(observation("weather", quantity="humidity"),)),
        evidence("realtime_transport"),
    )

    assert attempt.run is not None
    assert attempt.run.status is RunStatus.DEGRADED
    assert [problem.code for problem in attempt.run.problems] == ["weather_missing_measurement"]
    assert attempt.run.outputs[0].payload["weather"]["validated_observations"] == []


def test_forged_city_binding_is_rejected_without_leaking_unvalidated_readings() -> None:
    weather = evidence("weather")
    forged = weather.model_copy(
        update={
            "payload": {
                **weather.payload,
                "provider": {**weather.payload["provider"], "city_id": "mainz"},
            }
        }
    )
    attempt = assess(forged, evidence("realtime_transport"))

    assert attempt.run is not None
    assert attempt.run.status is RunStatus.DEGRADED
    assert [problem.code for problem in attempt.run.problems] == ["weather_invalid_evidence"]
    weather_result = attempt.run.outputs[0].payload["weather"]
    assert weather_result["validated_observations"] == []
    assert "read" not in weather_result


def test_preparation_before_observation_receipt_is_not_reported_as_usable() -> None:
    weather = evidence("weather")
    premature = weather.model_copy(
        update={
            "payload": {
                **weather.payload,
                "prepared_at": OBSERVED.isoformat().replace("+00:00", "Z"),
            }
        }
    )
    attempt = assess(premature, evidence("realtime_transport"))

    assert attempt.run is not None
    assert attempt.run.status is RunStatus.DEGRADED
    assert [problem.code for problem in attempt.run.problems] == ["weather_invalid_evidence"]
    assert attempt.run.outputs[0].payload["both_sources_usable"] is False



def test_evidence_prepared_after_execution_is_rejected_without_echoing_readings() -> None:
    weather = evidence("weather")
    future = weather.model_copy(
        update={
            "payload": {
                **weather.payload,
                "prepared_at": "2026-10-24T09:16:00Z",
            }
        }
    )
    attempt = assess(future, evidence("realtime_transport"))

    assert attempt.run is not None
    assert attempt.run.status is RunStatus.DEGRADED
    assert [problem.code for problem in attempt.run.problems] == ["weather_invalid_evidence"]
    snapshot = attempt.run.outputs[0].payload
    assert snapshot["both_sources_usable"] is False
    assert snapshot["weather"]["validated_observations"] == []
    assert "read" not in snapshot["weather"]
    assert snapshot["realtime_transport"]["usable"] is True


def test_evidence_prepared_at_execution_with_different_offset_is_valid() -> None:
    weather = evidence("weather")
    on_time = weather.model_copy(
        update={
            "payload": {
                **weather.payload,
                "prepared_at": "2026-10-24T11:15:00+02:00",
            }
        }
    )
    attempt = assess(on_time, evidence("realtime_transport"))

    assert attempt.run is not None
    assert attempt.run.status is RunStatus.AVAILABLE
    assert attempt.run.outputs[0].payload["both_sources_usable"] is True


def test_mainz_does_not_execute_without_verified_transport_capability() -> None:
    attempt = assess(evidence("weather"), evidence("realtime_transport"), city_id="mainz")

    assert not attempt.resolution.available
    assert attempt.run is None
    assert [item.capability_id for item in attempt.resolution.unavailable] == ["realtime_transport"]
