"""The twin snapshot composes discovery, reads, relations and agents for a city."""

import json
from datetime import timedelta
from pathlib import Path

from rdflib import Graph

from tests.twin_fixtures import NOW, upstream
from urbanium.registry import CityRegistry
from urbanium.twin.bindings import area_bindings
from urbanium.twin.cli import load_previous, main
from urbanium.twin.fetching import RecordingFetcher, ReplayFetcher
from urbanium.twin.snapshot import (
    SNAPSHOT_SCHEMA,
    DataMode,
    TwinSnapshot,
    build_city_snapshot,
    build_index,
    project_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = CityRegistry.from_directory(ROOT / "cities")


def snapshot(city_id: str, fetch=None) -> TwinSnapshot:  # type: ignore[no-untyped-def]
    city = REGISTRY.city(city_id)
    bindings = area_bindings(
        ROOT / "cities" / city_id, fetcher=fetch or upstream(), clock=lambda: NOW
    )
    return build_city_snapshot(city, bindings, clock=lambda: NOW, data_mode=DataMode.LIVE)


def test_berlin_snapshot_contains_located_entities_with_latest_values_and_series() -> None:
    twin = snapshot("berlin")

    assert twin.schema_id == SNAPSHOT_SCHEMA
    assert twin.city.id == "berlin"
    layers = {layer.capability_id: layer for layer in twin.layers}
    assert layers["weather"].availability == "available"
    assert layers["weather"].entity_count == 3
    assert layers["river_level"].availability == "available"

    station = next(e for e in twin.entities if e.entity_id == "dwd_station_10001")
    assert station.label == "Beispielstation Mitte"
    assert (station.latitude, station.longitude) == (52.52, 13.40)
    assert station.latest is not None
    assert station.latest.value == "3.4"
    assert station.latest.unit == "Cel"
    assert station.freshness == "fresh"
    assert [point[1] for point in station.series] == ["3.0", "3.2", "3.4"]
    assert station.evidence[0].source_id == "dwd_open_data"


def test_agents_run_on_the_snapshot_and_keep_provenance() -> None:
    twin = snapshot("berlin")
    runs = {item.component_id: item for item in twin.agents}

    spread = runs["temperature_spread"]
    assert spread.resolved is True
    assert spread.run is not None and spread.run.status.value == "available"
    payload = spread.run.outputs[0].payload
    assert isinstance(payload, dict) and payload["station_count"] == 3
    assert spread.run.provenance.inputs[0].capability_id == "weather"

    trend = runs["water_level_trend"].run
    assert trend is not None
    gauges = {item["entity"]: item for item in trend.outputs[0].payload["gauges"]}  # type: ignore[index]
    assert gauges["berlin:river_gauge:pegelonline_580001"]["trend"] == "rising"
    assert gauges["berlin:river_gauge:pegelonline_580002"]["trend"] == "steady"


def test_relations_link_gauges_to_waters_and_nearest_stations() -> None:
    twin = snapshot("berlin")
    predicates = {(r.assertion.subject.entity_id, r.assertion.predicate) for r in twin.relations}

    assert ("pegelonline_580001", "on_water_body") in predicates
    assert ("pegelonline_580001", "nearest_weather_station") in predicates
    assert ("dwd_station_10001", "located_in") in predicates


def test_a_city_with_one_station_explains_why_the_spread_is_unanswerable() -> None:
    twin = snapshot("mainz")
    runs = {item.component_id: item for item in twin.agents}

    run = runs["temperature_spread"].run
    assert run is not None and run.status.value == "unavailable"
    assert run.problems[0].code == "insufficient_aligned_stations"
    # Mainz' area has no synthetic gauge: an empty discovery stays empty.
    layers = {layer.capability_id: layer for layer in twin.layers}
    assert layers["river_level"].entity_count == 0
    assert layers["river_level"].availability == "unavailable"


def test_source_outage_is_reported_and_never_filled_in() -> None:
    twin = snapshot("berlin", upstream(broken={"stations.json"}))

    layers = {layer.capability_id: layer for layer in twin.layers}
    assert layers["river_level"].availability == "unavailable"
    assert layers["river_level"].discovery_status == "unavailable"
    assert layers["river_level"].error is not None
    assert not [e for e in twin.entities if e.entity_type == "river_gauge"]
    trend = next(item for item in twin.agents if item.component_id == "water_level_trend")
    assert trend.run is None
    assert trend.skipped_reason == "no runtime read for capability 'river_level'"


def test_station_without_data_is_kept_as_entity_without_value() -> None:
    twin = snapshot("berlin", upstream(broken={"_TU_10003_"}))

    station = next(e for e in twin.entities if e.entity_id == "dwd_station_10003")
    assert station.latest is None
    assert station.series == []
    assert station.freshness == "no_data"
    weather = next(layer for layer in twin.layers if layer.capability_id == "weather")
    assert weather.availability == "degraded"


def test_snapshot_round_trips_and_projects_to_rdf_with_geometry() -> None:
    twin = snapshot("berlin")
    restored = TwinSnapshot.model_validate_json(twin.model_dump_json())
    assert restored == twin

    graph = project_snapshot(twin)
    turtle = graph.serialize(format="turtle")
    reparsed = Graph().parse(data=turtle, format="turtle")
    assert len(reparsed) == len(graph)
    assert "POINT(13.4 52.52)" in turtle
    assert "Beispielstation Mitte" in turtle


def test_index_summarises_every_city() -> None:
    twins = [snapshot("berlin"), snapshot("mainz")]

    index = build_index(twins, generated_at=NOW, data_mode=DataMode.LIVE)

    assert [item.id for item in index.cities] == ["berlin", "mainz"]
    assert index.cities[0].entity_count == len(twins[0].entities)


def test_recording_replays_to_an_identical_snapshot(tmp_path: Path) -> None:
    recorder = RecordingFetcher(upstream(), tmp_path)
    live = snapshot("berlin", recorder)
    recorder.write_manifest(NOW)

    replayed = snapshot("berlin", ReplayFetcher(tmp_path))

    assert replayed.entities == live.entities
    assert replayed.agents == live.agents


def test_replay_of_an_unrecorded_url_behaves_like_an_outage(tmp_path: Path) -> None:
    recorder = RecordingFetcher(upstream(), tmp_path)
    recorder.write_manifest(NOW)  # nothing recorded

    twin = snapshot("berlin", ReplayFetcher(tmp_path))

    assert {layer.availability for layer in twin.layers} == {"unavailable"}
    assert twin.entities == []


def test_cli_builds_index_city_json_and_turtle_from_a_replay(tmp_path: Path) -> None:
    recording = tmp_path / "recording"
    recorder = RecordingFetcher(upstream(), recording)
    for city_id in ("berlin", "mainz"):
        snapshot(city_id, recorder)
    manifest = recorder.write_manifest(NOW)
    (recording / "manifest.json").write_text(
        manifest.model_copy(update={"synthetic": True}).model_dump_json(), encoding="utf-8"
    )
    out = tmp_path / "data"

    exit_code = main(
        [
            "build",
            "--cities",
            str(ROOT / "cities"),
            "--out",
            str(out),
            "--replay",
            str(recording),
            "--only",
            "berlin",
            "--only",
            "mainz",
        ]
    )

    assert exit_code == 0
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert index["data_mode"] == "synthetic"
    assert [city["id"] for city in index["cities"]] == ["berlin", "mainz"]
    berlin = json.loads((out / "berlin.json").read_text(encoding="utf-8"))
    assert berlin["data_mode"] == "synthetic"
    assert berlin["generated_at"] == "2026-11-23T09:00:00Z"
    assert (out / "berlin.ttl").read_text(encoding="utf-8").startswith("@prefix")


# --- last known good ------------------------------------------------------

LATER = NOW + timedelta(hours=1)


def later_snapshot(city_id: str, fetch, previous):  # type: ignore[no-untyped-def]
    city = REGISTRY.city(city_id)
    bindings = area_bindings(ROOT / "cities" / city_id, fetcher=fetch, clock=lambda: LATER)
    return build_city_snapshot(
        city, bindings, clock=lambda: LATER, data_mode=DataMode.LIVE, previous=previous
    )


def test_layer_outage_keeps_the_last_known_values_marked_as_such() -> None:
    before = snapshot("berlin")

    twin = later_snapshot("berlin", upstream(broken={"stations.json"}), before)

    gauges = [e for e in twin.entities if e.entity_type == "river_gauge"]
    assert len(gauges) == 2
    assert {e.freshness for e in gauges} == {"last_known"}
    assert all(e.carried_over_from == before.generated_at for e in gauges)
    assert gauges[0].latest == next(e for e in before.entities if e.id == gauges[0].id).latest
    layer = next(item for item in twin.layers if item.capability_id == "river_level")
    assert layer.availability == "unavailable"
    assert layer.carried_over == 2
    assert layer.carried_over_from == before.generated_at
    # Agents never compute on carried values.
    trend = next(item for item in twin.agents if item.component_id == "water_level_trend")
    assert trend.run is None
    # Relations of carried entities come along with them.
    assert any(
        r.assertion.subject.entity_id == "pegelonline_580001"
        and r.assertion.predicate == "on_water_body"
        for r in twin.relations
    )


def test_single_station_without_data_takes_its_previous_value() -> None:
    before = snapshot("berlin")

    twin = later_snapshot("berlin", upstream(broken={"_TU_10003_"}), before)

    station = next(e for e in twin.entities if e.entity_id == "dwd_station_10003")
    assert station.freshness == "last_known"
    assert station.latest is not None and station.latest.value == "2.9"
    fresh = next(e for e in twin.entities if e.entity_id == "dwd_station_10001")
    assert fresh.carried_over_from is None


def test_values_older_than_the_carry_window_are_not_kept() -> None:
    before = snapshot("berlin")
    city = REGISTRY.city("berlin")
    much_later = NOW + timedelta(hours=49)
    bindings = area_bindings(
        ROOT / "cities" / "berlin",
        fetcher=upstream(broken={"stations.json"}),
        clock=lambda: much_later,
    )

    twin = build_city_snapshot(
        city, bindings, clock=lambda: much_later, data_mode=DataMode.LIVE, previous=before
    )

    assert not [e for e in twin.entities if e.entity_type == "river_gauge"]


def test_synthetic_or_replayed_values_never_carry_into_live() -> None:
    before = snapshot("berlin").model_copy(update={"data_mode": DataMode.SYNTHETIC})

    twin = later_snapshot("berlin", upstream(broken={"stations.json"}), before)

    assert not [e for e in twin.entities if e.entity_type == "river_gauge"]


def test_cli_reads_previous_snapshots(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    previous.mkdir()
    (previous / "berlin.json").write_text(snapshot("berlin").model_dump_json(), encoding="utf-8")
    (previous / "mainz.json").write_text("not json", encoding="utf-8")

    loaded = load_previous(previous, "berlin")
    assert loaded is not None and loaded.city.id == "berlin"
    assert load_previous(previous, "mainz") is None
    assert load_previous(previous, "koeln") is None


def test_entities_in_the_surroundings_are_flagged() -> None:
    twin = snapshot("berlin")

    assert all(entity.in_surroundings is False for entity in twin.entities)


def test_layers_keep_network_level_figures_as_a_summary() -> None:
    twin = snapshot("berlin")

    transit = next(layer for layer in twin.layers if layer.capability_id == "realtime_transport")
    assert transit.summary["active_service_alerts"] == "2"
    assert transit.summary["named_stops_in_area"] == "2"
    weather = next(layer for layer in twin.layers if layer.capability_id == "weather")
    assert weather.summary == {}
