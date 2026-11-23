"""Stops named in alerts near gauges above their mean high water are listed."""

from datetime import timedelta

from urbanium.agents.transit_near_high_water import TransitNearHighWaterAgent
from urbanium.analysis.observation_inputs import observation_input
from urbanium.core.discovery import DiscoveredEntity
from urbanium.core.entity import EntityReference, EvidenceReference, StateCategory
from urbanium.core.execution import RunStatus, execute_component
from urbanium.core.provider import ProviderDescriptor
from urbanium.core.spatial import EntityPointLocation, Wgs84Point

from .helpers import BERLIN, NOW, RIVER, observation, read

TRANSIT = ProviderDescriptor(
    city_id="berlin",
    source_id="vbb_gtfs_rt",
    capability_id="realtime_transport",
    adapter_version="1.0.0",
)


def entity(
    kind: str, entity_id: str, lat: float, lon: float, source: str, **attrs: float
) -> DiscoveredEntity:
    return DiscoveredEntity(
        location=EntityPointLocation(
            entity=EntityReference(city_id="berlin", entity_type=kind, entity_id=entity_id),
            point=Wgs84Point(latitude=lat, longitude=lon),
            state_category=StateCategory.REFERENCE,
            asserted_at=NOW,
            evidence=(
                EvidenceReference(
                    city_id="berlin",
                    source_id=source,
                    record_id=f"r:{entity_id}",
                    retrieved_at=NOW - timedelta(minutes=1),
                ),
            ),
        ),
        label=entity_id,
        attributes=dict(attrs),
    )


GAUGES = (
    entity(
        "river_gauge", "high_gauge", 52.50, 13.40, "pegelonline", mnw_cm=100, mw_cm=150, mhw_cm=200
    ),
    entity(
        "river_gauge", "calm_gauge", 52.45, 13.30, "pegelonline", mnw_cm=100, mw_cm=150, mhw_cm=200
    ),
)
STOPS = (
    entity("transport_stop", "near_stop", 52.505, 13.40, "vbb_gtfs_static"),
    entity("transport_stop", "far_stop", 52.55, 13.40, "vbb_gtfs_static"),
    entity("transport_stop", "calm_stop", 52.451, 13.30, "vbb_gtfs_static"),
)


def transit_observation(entity_id: str):  # type: ignore[no-untyped-def]
    from decimal import Decimal

    from urbanium.core.provider import Observation

    return Observation(
        city_id="berlin",
        source_id="vbb_gtfs_rt",
        capability_id="realtime_transport",
        entity=EntityReference(city_id="berlin", entity_type="transport_stop", entity_id=entity_id),
        quantity_id="alert_mentions",
        value=Decimal(1),
        unit="1",
        observed_at=NOW - timedelta(minutes=1),
        received_at=NOW,
    )


def run(river, transit, gauges=GAUGES):  # type: ignore[no-untyped-def]
    return execute_component(
        BERLIN,
        TransitNearHighWaterAgent(),
        inputs=(
            observation_input(BERLIN, RIVER, river, prepared_at=NOW, reference=gauges),
            observation_input(BERLIN, TRANSIT, transit, prepared_at=NOW, reference=STOPS),
        ),
        executed_at=NOW,
    ).run


def test_only_stops_within_one_km_of_a_gauge_above_mhw_are_paired() -> None:
    result = run(
        read(
            observation(RIVER, "high_gauge", "205", 0), observation(RIVER, "calm_gauge", "120", 0)
        ),
        read(*(transit_observation(s) for s in ("near_stop", "far_stop", "calm_stop"))),
    )

    assert result is not None and result.status is RunStatus.AVAILABLE
    payload = result.outputs[0].payload
    assert isinstance(payload, dict)
    assert payload["gauges_above_mhw"] == ["berlin:river_gauge:high_gauge"]
    pairs = payload["pairs"]
    assert isinstance(pairs, list) and len(pairs) == 1
    assert pairs[0]["stop"] == "berlin:transport_stop:near_stop"  # type: ignore[index]
    assert pairs[0]["mhw_cm"] == "200"  # type: ignore[index]
    assert float(pairs[0]["distance_km"]) < 1  # type: ignore[index, arg-type]


def test_no_gauge_above_mhw_gives_an_empty_answer_not_a_failure() -> None:
    result = run(
        read(observation(RIVER, "calm_gauge", "120", 0)),
        read(transit_observation("calm_stop")),
    )

    assert result is not None and result.status is RunStatus.AVAILABLE
    assert result.outputs[0].payload["pairs"] == []  # type: ignore[index]


def test_without_characteristic_values_or_feed_it_stays_unanswered() -> None:
    plain = (entity("river_gauge", "high_gauge", 52.5, 13.4, "pegelonline"),)
    no_values = run(
        read(observation(RIVER, "high_gauge", "205", 0)),
        read(transit_observation("near_stop")),
        plain,
    )
    assert no_values is not None and no_values.problems[0].code == "no_characteristic_values"

    no_feed = run(read(observation(RIVER, "high_gauge", "205", 0)), read())
    assert no_feed is not None and no_feed.problems[0].code == "realtime_transport_unavailable"
