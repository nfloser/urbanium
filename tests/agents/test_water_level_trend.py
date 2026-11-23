"""Water-level trends need a real reference value; none is ever extrapolated."""

from urbanium.agents.water_level_trend import WaterLevelTrendAgent
from urbanium.core.execution import RunStatus, execute_component

from .helpers import BERLIN, NOW, RIVER, capability_input, observation, read


def run(*observations, degraded=None):  # type: ignore[no-untyped-def]
    return execute_component(
        BERLIN,
        WaterLevelTrendAgent(),
        inputs=(capability_input(RIVER, read(*observations, degraded=degraded)),),
        executed_at=NOW,
    ).run


def gauges(run_result):  # type: ignore[no-untyped-def]
    payload = run_result.outputs[0].payload
    return {item["entity"].rsplit(":", 1)[1]: item for item in payload["gauges"]}


def test_trend_compares_latest_value_with_the_value_six_hours_earlier() -> None:
    run_result = run(
        observation(RIVER, "rising_gauge", "300", 6 * 60 + 15),
        observation(RIVER, "rising_gauge", "312", 15),
        observation(RIVER, "falling_gauge", "220", 6 * 60),
        observation(RIVER, "falling_gauge", "205", 0),
        observation(RIVER, "steady_gauge", "150", 6 * 60 + 30),
        observation(RIVER, "steady_gauge", "152", 0),
    )

    assert run_result is not None and run_result.status is RunStatus.AVAILABLE
    result = gauges(run_result)
    assert result["rising_gauge"]["trend"] == "rising"
    assert result["rising_gauge"]["change"] == "12"
    assert result["rising_gauge"]["reference_at"] == "2026-11-23T02:45:00Z"
    assert result["rising_gauge"]["latest"] == {
        "value": "312",
        "observed_at": "2026-11-23T08:45:00Z",
    }
    assert result["falling_gauge"]["trend"] == "falling"
    assert result["falling_gauge"]["change"] == "-15"
    assert result["steady_gauge"]["trend"] == "steady"
    assert run_result.outputs[0].payload["window_hours"] == 6  # type: ignore[index]


def test_gauge_without_a_reference_inside_the_tolerance_is_not_guessed() -> None:
    run_result = run(
        observation(RIVER, "known_gauge", "300", 6 * 60),
        observation(RIVER, "known_gauge", "301", 0),
        observation(RIVER, "short_gauge", "200", 3 * 60),
        observation(RIVER, "short_gauge", "260", 0),
    )

    assert run_result is not None and run_result.status is RunStatus.DEGRADED
    result = gauges(run_result)
    assert result["short_gauge"]["trend"] == "unknown"
    assert result["short_gauge"]["change"] is None
    assert run_result.problems[0].code == "trend_not_determinable"
    assert "short_gauge" in run_result.problems[0].message


def test_no_determinable_trend_at_all_is_unavailable() -> None:
    run_result = run(observation(RIVER, "short_gauge", "200", 0))

    assert run_result is not None and run_result.status is RunStatus.UNAVAILABLE
    assert run_result.problems[0].code == "trend_not_determinable"


def test_unavailable_river_level_stays_unavailable() -> None:
    run_result = run()

    assert run_result is not None and run_result.status is RunStatus.UNAVAILABLE
    assert run_result.problems[0].code == "river_level_unavailable"
