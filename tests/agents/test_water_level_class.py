"""Gauges are placed against their own long-term characteristic values."""

from datetime import timedelta

from urbanium.agents.water_level_class import WaterLevelClassAgent
from urbanium.analysis.observation_inputs import observation_input
from urbanium.core.discovery import DiscoveredEntity
from urbanium.core.entity import EntityReference, EvidenceReference, StateCategory
from urbanium.core.execution import RunStatus, execute_component
from urbanium.core.spatial import EntityPointLocation, Wgs84Point

from .helpers import BERLIN, NOW, RIVER, observation, read


def gauge(entity_id: str, **values: float) -> DiscoveredEntity:
    return DiscoveredEntity(
        location=EntityPointLocation(
            entity=EntityReference(
                city_id="berlin", entity_type="river_gauge", entity_id=entity_id
            ),
            point=Wgs84Point(latitude=52.5, longitude=13.4),
            state_category=StateCategory.REFERENCE,
            asserted_at=NOW,
            evidence=(
                EvidenceReference(
                    city_id="berlin",
                    source_id="pegelonline",
                    record_id=f"stations.json:{entity_id}",
                    retrieved_at=NOW - timedelta(minutes=1),
                ),
            ),
        ),
        label=entity_id,
        attributes={"uuid": "x", **values},
    )


REFERENCE = (
    gauge("high_gauge", mnw_cm=100, mw_cm=150, mhw_cm=200),
    gauge("mid_gauge", mnw_cm=100, mw_cm=150, mhw_cm=200),
    gauge("low_gauge", mnw_cm=100, mw_cm=150, mhw_cm=200),
    gauge("plain_gauge"),
)


def run(*observations, reference=REFERENCE):  # type: ignore[no-untyped-def]
    item = observation_input(
        BERLIN, RIVER, read(*observations), prepared_at=NOW, reference=reference
    )
    return execute_component(BERLIN, WaterLevelClassAgent(), inputs=(item,), executed_at=NOW).run


def classes(run_result):  # type: ignore[no-untyped-def]
    payload = run_result.outputs[0].payload
    return {g["entity"].rsplit(":", 1)[1]: g for g in payload["gauges"]}


def test_latest_level_is_placed_between_the_gauges_own_values() -> None:
    result = run(
        observation(RIVER, "high_gauge", "180", 60),
        observation(RIVER, "high_gauge", "205", 0),
        observation(RIVER, "mid_gauge", "160", 0),
        observation(RIVER, "low_gauge", "95", 0),
        observation(RIVER, "plain_gauge", "300", 0),
    )

    assert result is not None and result.status is RunStatus.AVAILABLE
    found = classes(result)
    assert found["high_gauge"]["class"] == "above_mhw"
    assert found["high_gauge"]["latest"]["value"] == "205"
    assert found["high_gauge"]["reference"] == {"mnw_cm": "100", "mw_cm": "150", "mhw_cm": "200"}
    assert found["mid_gauge"]["class"] == "mw_to_mhw"
    assert found["low_gauge"]["class"] == "below_mnw"
    assert found["plain_gauge"]["class"] == "no_reference"
    assert found["high_gauge"]["reference_evidence"] == ["pegelonline:stations.json:high_gauge"]


def test_without_any_characteristic_values_the_question_is_unanswerable() -> None:
    result = run(observation(RIVER, "plain_gauge", "300", 0), reference=(gauge("plain_gauge"),))

    assert result is not None and result.status is RunStatus.UNAVAILABLE
    assert result.problems[0].code == "no_characteristic_values"


def test_without_reference_context_the_agent_does_not_guess() -> None:
    result = run(observation(RIVER, "high_gauge", "205", 0), reference=None)

    assert result is not None and result.status is RunStatus.UNAVAILABLE
    assert result.problems[0].code == "no_characteristic_values"


def test_unavailable_river_level_stays_unavailable() -> None:
    result = run()

    assert result is not None and result.status is RunStatus.UNAVAILABLE
    assert result.problems[0].code == "river_level_unavailable"
