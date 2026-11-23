"""Stops named in alerts are located through static GTFS; misses are reported."""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from tests.twin_fixtures import NOW, gtfs_zip, vbb_feed
from urbanium.core.discovery import DiscoveryStatus, validate_discovery_result
from urbanium.core.provider import Availability
from urbanium.providers.vbb.alert_stops import (
    StaticGtfsLoader,
    VbbAlertStopDiscovery,
    VbbAlertStopProvider,
    load_vbb_alert_stops_config,
)
from urbanium.registry import load_city_definition

ROOT = Path(__file__).resolve().parents[1]
BERLIN = load_city_definition(ROOT / "cities" / "berlin" / "city.yaml")
CONFIG = load_vbb_alert_stops_config(
    ROOT / "cities" / "berlin" / "providers" / "vbb_alert_stops.yaml"
)


def fetcher(feed: bytes | Exception = b"", static: bytes | Exception = b""):  # type: ignore[no-untyped-def]
    calls: list[str] = []

    def fetch(url: str, timeout: float) -> bytes:
        calls.append(url)
        response = feed if "gtfsrt" in url else static
        if isinstance(response, Exception):
            raise response
        return response

    return fetch, calls


def discovery(feed=None, static=None, cache=None):  # type: ignore[no-untyped-def]
    fetch, calls = fetcher(
        vbb_feed() if feed is None else feed, gtfs_zip() if static is None else static
    )
    return VbbAlertStopDiscovery(CONFIG, fetcher=fetch, clock=lambda: NOW, cache_dir=cache), calls


def test_named_stops_are_located_and_carry_the_alert_text() -> None:
    subject, _ = discovery()

    result = subject.discover(BERLIN)

    validate_discovery_result(BERLIN, result)
    assert result.status is DiscoveryStatus.AVAILABLE
    labels = {item.label: item for item in result.entities}
    assert set(labels) == {"Beispielhaltestelle Spree", "Beispielhaltestelle Süd"}
    spree = labels["Beispielhaltestelle Spree"]
    assert spree.location.entity.entity_type == "transport_stop"
    assert spree.attributes["alert_count"] == 1
    assert spree.attributes["alert_text"] == "Ersatzverkehr Beispiellinie"
    assert spree.location.evidence[0].source_id == "vbb_gtfs_static"
    assert (subject.references, subject.unresolved) == (3, 1)


def test_unresolved_ids_degrade_the_read_and_counts_are_observations() -> None:
    subject, _ = discovery()
    stops = subject.discover(BERLIN).entities

    result = VbbAlertStopProvider(subject, stops).read()

    assert result.availability is Availability.DEGRADED
    assert result.error is not None and "1 of 3 alert stop ids" in result.error.message
    network = {
        o.quantity_id: o.value
        for o in result.observations
        if o.entity.entity_type == "transport_network"
    }
    assert network["named_stops_in_area"] == 2
    assert network["active_service_alerts"] == 2  # feed-wide counts are kept as read


def test_feed_or_static_outage_makes_discovery_unavailable() -> None:
    down, _ = discovery(feed=OSError("down"))
    assert down.discover(BERLIN).status is DiscoveryStatus.UNAVAILABLE

    no_static, _ = discovery(static=OSError("down"))
    result = no_static.discover(BERLIN)
    assert result.status is DiscoveryStatus.UNAVAILABLE
    assert result.error is not None and "static GTFS" in result.error.message


def test_static_archive_is_cached_for_its_maximum_age(tmp_path: Path) -> None:
    fetch, calls = fetcher(static=gtfs_zip())
    loader = StaticGtfsLoader(
        "https://unternehmen.vbb.de/x.zip",
        cache_dir=tmp_path,
        max_age=timedelta(days=7),
        fetcher=fetch,
        clock=lambda: NOW,
    )
    first = loader.load()
    second = loader.load()
    assert first == second and len(calls) == 1

    later = StaticGtfsLoader(
        "https://unternehmen.vbb.de/x.zip",
        cache_dir=tmp_path,
        max_age=timedelta(days=7),
        fetcher=fetch,
        clock=lambda: NOW + timedelta(days=8),
    )
    later.load()
    assert len(calls) == 2
    meta = json.loads((tmp_path / "gtfs-static.json").read_text(encoding="utf-8"))
    assert meta["retrieved_at"].startswith("2026-12-01")


def test_discovery_requires_its_city() -> None:
    subject, _ = discovery()
    mainz = load_city_definition(ROOT / "cities" / "mainz" / "city.yaml")
    with pytest.raises(ValueError):
        subject.discover(mainz)
