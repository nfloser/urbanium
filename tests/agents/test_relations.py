"""Spatial and source-stated relationships carry the evidence they rest on."""

from datetime import UTC, datetime

import pytest

from urbanium.agents.relations import derive_relations
from urbanium.core.discovery import DiscoveredEntity, DiscoveryResult, DiscoveryStatus
from urbanium.core.entity import EntityReference, EvidenceReference, StateCategory
from urbanium.core.spatial import EntityPointLocation, Wgs84Point
from urbanium.semantics.rdf import project_relationships

from .helpers import BERLIN

NOW = datetime(2026, 11, 23, 9, tzinfo=UTC)


def item(
    entity_type: str,
    entity_id: str,
    latitude: float,
    longitude: float,
    source_id: str,
    **attributes: str | float,
) -> DiscoveredEntity:
    return DiscoveredEntity(
        location=EntityPointLocation(
            entity=EntityReference(city_id="berlin", entity_type=entity_type, entity_id=entity_id),
            point=Wgs84Point(latitude=latitude, longitude=longitude),
            state_category=StateCategory.REFERENCE,
            asserted_at=NOW,
            evidence=(
                EvidenceReference(
                    city_id="berlin",
                    source_id=source_id,
                    record_id=f"record:{entity_id}",
                    retrieved_at=NOW,
                ),
            ),
        ),
        label=entity_id,
        attributes=dict(attributes),
    )


def discovery(source_id: str, *entities: DiscoveredEntity) -> DiscoveryResult:
    return DiscoveryResult(
        city_id="berlin",
        source_id=source_id,
        status=DiscoveryStatus.AVAILABLE,
        discovered_at=NOW,
        entities=entities,
    )


STATIONS = discovery(
    "dwd_open_data",
    item("weather_station", "dwd_station_00433", 52.4675, 13.4021, "dwd_open_data"),
    item("weather_station", "dwd_station_00403", 52.4537, 13.3017, "dwd_open_data"),
)
GAUGES = discovery(
    "pegelonline",
    item(
        "river_gauge",
        "pegelonline_5803200",
        52.5133,
        13.4085,
        "pegelonline",
        water="SPREE-ODER-WASSERSTRASSE",
    ),
    item("river_gauge", "pegelonline_5865000", 52.5386, 13.2120, "pegelonline", water="HAVEL"),
)


def by_predicate(relations, predicate):  # type: ignore[no-untyped-def]
    return {
        relation.assertion.subject.entity_id: relation
        for relation in relations
        if relation.assertion.predicate == predicate
    }


def test_every_discovered_entity_is_located_in_the_city_discovery_area() -> None:
    relations = derive_relations(BERLIN, (STATIONS, GAUGES), asserted_at=NOW)

    located = by_predicate(relations, "located_in")
    assert set(located) == {
        "dwd_station_00433",
        "dwd_station_00403",
        "pegelonline_5803200",
        "pegelonline_5865000",
    }
    relation = located["dwd_station_00433"]
    assert relation.assertion.object.canonical_id == "berlin:discovery_area:berlin"
    assert relation.assertion.state_category is StateCategory.DERIVED
    assert relation.assertion.evidence[0].record_id == "record:dwd_station_00433"
    assert relation.method == "point_in_area"


def test_gauges_are_linked_to_the_water_body_stated_by_the_source() -> None:
    relations = derive_relations(BERLIN, (STATIONS, GAUGES), asserted_at=NOW)

    on_water = by_predicate(relations, "on_water_body")
    assert on_water["pegelonline_5803200"].assertion.object.entity_id == (
        "water_spree_oder_wasserstrasse"
    )
    assert on_water["pegelonline_5865000"].assertion.object.entity_id == "water_havel"
    assert on_water["pegelonline_5865000"].assertion.state_category is StateCategory.REFERENCE
    assert on_water["pegelonline_5865000"].object_label == "HAVEL"


def test_each_gauge_gets_its_nearest_weather_station_with_distance() -> None:
    relations = derive_relations(BERLIN, (STATIONS, GAUGES), asserted_at=NOW)

    nearest = by_predicate(relations, "nearest_weather_station")
    muehlendamm = nearest["pegelonline_5803200"]
    assert muehlendamm.assertion.object.entity_id == "dwd_station_00433"
    assert muehlendamm.distance_km == pytest.approx(5.1, abs=0.2)
    assert [item.source_id for item in muehlendamm.assertion.evidence] == [
        "pegelonline",
        "dwd_open_data",
    ]
    assert nearest["pegelonline_5865000"].assertion.object.entity_id == "dwd_station_00403"


def test_relations_are_deterministic_and_project_to_valid_rdf() -> None:
    first = derive_relations(BERLIN, (STATIONS, GAUGES), asserted_at=NOW)
    second = derive_relations(BERLIN, (GAUGES, STATIONS), asserted_at=NOW)

    assert [item.assertion.canonical_id for item in first] == [
        item.assertion.canonical_id for item in second
    ]
    graph = project_relationships(item.assertion for item in first)
    assert len(graph) > 0


def test_without_stations_no_nearest_station_is_invented() -> None:
    relations = derive_relations(BERLIN, (GAUGES,), asserted_at=NOW)

    assert by_predicate(relations, "nearest_weather_station") == {}


def test_unavailable_discoveries_contribute_nothing() -> None:
    from urbanium.core.provider import ProviderError, ProviderErrorCode

    down = DiscoveryResult(
        city_id="berlin",
        source_id="pegelonline",
        status=DiscoveryStatus.UNAVAILABLE,
        discovered_at=NOW,
        error=ProviderError(code=ProviderErrorCode.UPSTREAM, message="down"),
    )
    relations = derive_relations(BERLIN, (STATIONS, down), asserted_at=NOW)

    assert {item.assertion.predicate for item in relations} == {"located_in"}


def test_entities_in_the_surroundings_are_near_the_area_not_in_it() -> None:
    raw = BERLIN.model_dump(mode="json")
    raw["area"]["surroundings_km"] = 15
    with_ring = BERLIN.model_validate(raw)
    outside = discovery(
        "dwd_open_data",
        item("weather_station", "dwd_station_05825", 52.25, 13.40, "dwd_open_data"),
    )

    relations = derive_relations(with_ring, (outside,), asserted_at=NOW)

    assert [r.assertion.predicate for r in relations] == ["located_near"]
    assert relations[0].method == "point_in_surroundings"
