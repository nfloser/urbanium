"""The temperature spread compares stations only at one shared measurement time."""

from urbanium.agents.temperature_spread import TemperatureSpreadAgent
from urbanium.core.execution import RunStatus, execute_component

from .helpers import BERLIN, NOW, WEATHER, capability_input, observation, read


def run(*observations, degraded=None):  # type: ignore[no-untyped-def]
    return execute_component(
        BERLIN,
        TemperatureSpreadAgent(),
        inputs=(capability_input(WEATHER, read(*observations, degraded=degraded)),),
        executed_at=NOW,
    ).run


def test_spread_uses_the_latest_time_reported_by_enough_stations() -> None:
    run_result = run(
        observation(WEATHER, "dwd_station_00433", "4.0", 20),
        observation(WEATHER, "dwd_station_00403", "3.0", 20),
        observation(WEATHER, "dwd_station_00399", "5.5", 20),
        # Only one station reports the newest slot; it cannot form a comparison alone.
        observation(WEATHER, "dwd_station_00433", "4.2", 10),
    )

    assert run_result is not None and run_result.status is RunStatus.AVAILABLE
    payload = run_result.outputs[0].payload
    assert isinstance(payload, dict)
    assert payload["observed_at"] == "2026-11-23T08:40:00Z"
    assert payload["station_count"] == 3
    assert payload["min"] == {"entity": "berlin:weather_station:dwd_station_00403", "value": "3.0"}
    assert payload["max"] == {"entity": "berlin:weather_station:dwd_station_00399", "value": "5.5"}
    assert payload["spread"] == "2.5"
    assert payload["mean"] == "4.17"
    assert payload["unit"] == "Cel"
    assert payload["not_aligned"] == []


def test_stations_without_a_value_at_the_shared_time_are_listed_not_interpolated() -> None:
    run_result = run(
        observation(WEATHER, "a_station", "1.0", 10),
        observation(WEATHER, "b_station", "2.0", 10),
        observation(WEATHER, "c_station", "3.0", 10),
        observation(WEATHER, "d_station", "9.0", 30),
    )

    assert run_result is not None
    payload = run_result.outputs[0].payload
    assert isinstance(payload, dict)
    assert payload["station_count"] == 3
    assert payload["not_aligned"] == ["berlin:weather_station:d_station"]


def test_fewer_than_three_aligned_stations_make_the_question_unanswerable() -> None:
    run_result = run(
        observation(WEATHER, "a_station", "1.0", 10),
        observation(WEATHER, "b_station", "2.0", 10),
    )

    assert run_result is not None and run_result.status is RunStatus.UNAVAILABLE
    assert run_result.outputs == ()
    assert run_result.problems[0].code == "insufficient_aligned_stations"


def test_unavailable_weather_is_not_turned_into_a_spread() -> None:
    run_result = run()

    assert run_result is not None and run_result.status is RunStatus.UNAVAILABLE
    assert run_result.problems[0].code == "weather_unavailable"


def test_degraded_weather_yields_a_degraded_spread_with_the_source_reason() -> None:
    run_result = run(
        observation(WEATHER, "a_station", "1.0", 10),
        observation(WEATHER, "b_station", "2.0", 10),
        observation(WEATHER, "c_station", "3.0", 10),
        degraded="1 of 4 stations returned no air temperature",
    )

    assert run_result is not None and run_result.status is RunStatus.DEGRADED
    assert run_result.problems[0].code == "source_degraded"
    assert "1 of 4 stations" in run_result.problems[0].message
