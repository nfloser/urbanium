"""Static GTFS stop points are sourced lookups, not affected-stop assertions."""

from datetime import UTC, datetime
from hashlib import sha256

import pytest

from urbanium.core.entity import StateCategory
from urbanium.providers.vbb.gtfs_rt import VbbAlertStopReference
from urbanium.providers.vbb.static_stops import (
    MAX_STOPS_TXT_BYTES,
    VbbGtfsStaticStopConfig,
    VbbGtfsStaticStopError,
    VbbGtfsStaticStopInventory,
)

NOW = datetime(2026, 10, 25, 13, tzinfo=UTC)
HEADER = "stop_id,stop_name,stop_lat,stop_lon,location_type\n"
STOPS = (
    HEADER
    + '"de:stop/1","Stop, with comma",52.5001,13.4002,0\n'
    + "de:stop/2,Other stop,,,1\n"
)


def inventory(
    payload: bytes | None = None,
    *,
    city_id: str = "berlin",
    retrieved_at: datetime = NOW,
) -> VbbGtfsStaticStopInventory:
    return VbbGtfsStaticStopInventory(
        VbbGtfsStaticStopConfig(city_id=city_id, source_id="vbb_gtfs_static"),
        stops_txt=STOPS.encode() if payload is None else payload,
        retrieved_at=retrieved_at,
    )


def test_exact_stop_id_yields_sourced_reference_point() -> None:
    payload = ("\ufeff" + STOPS).encode("utf-8")
    location = inventory(payload).resolve("de:stop/1")

    assert location is not None
    assert location.entity.canonical_id == (
        "berlin:transport_stop:gtfs_stop_"
        + sha256(b"de:stop/1").hexdigest()
    )
    assert location.point.latitude == 52.5001
    assert location.point.longitude == 13.4002
    assert location.state_category is StateCategory.REFERENCE
    assert location.asserted_at == NOW
    assert location.evidence[0].source_id == "vbb_gtfs_static"
    assert location.evidence[0].retrieved_at == NOW
    assert location.evidence[0].record_id == (
        f"stops.txt:{sha256(b'de:stop/1').hexdigest()}:{sha256(payload).hexdigest()}"
    )


def test_alert_lookup_preserves_order_duplicates_and_missing_ids() -> None:
    refs = (
        VbbAlertStopReference(alert_id="a", selector_index=1, stop_id="de:stop/1"),
        VbbAlertStopReference(alert_id="a", selector_index=2, stop_id="absent"),
        VbbAlertStopReference(alert_id="b", selector_index=0, stop_id="de:stop/1"),
        VbbAlertStopReference(alert_id="b", selector_index=1, stop_id="de:stop/2"),
    )

    matches = inventory().resolve_alert_stop_references(refs)

    assert tuple(match.reference for match in matches) == refs
    assert matches[0].location is not None
    assert matches[1].location is None
    assert matches[2].location == matches[0].location
    assert matches[3].location is None


def test_absent_ids_and_stops_without_coordinates_stay_unresolved() -> None:
    source = inventory()
    assert source.resolve("de:stop/2") is None
    assert source.resolve("de:stop/unknown") is None
    assert source.resolve("DE:STOP/1") is None


def test_city_identity_is_scoped_without_changing_source_coordinates() -> None:
    berlin = inventory().resolve("de:stop/1")
    mainz = inventory(city_id="mainz").resolve("de:stop/1")

    assert berlin is not None and mainz is not None
    assert berlin.entity.city_id == "berlin"
    assert mainz.entity.city_id == "mainz"
    assert berlin.point == mainz.point


@pytest.mark.parametrize(
    "payload",
    [
        b"stop_id,stop_lat\n1,52.5\n",
        b"stop_id,stop_id,stop_lat,stop_lon\n1,1,52.5,13.4\n",
        (HEADER + "same,A,52.5,13.4,0\nsame,B,52.6,13.5,0\n").encode(),
        (HEADER + ",Unnamed,52.5,13.4,0\n").encode(),
        (HEADER + "id,Bad,91,13.4,0\n").encode(),
        (HEADER + "id,Bad,nan,13.4,0\n").encode(),
        (HEADER + "id,Bad,52.5,,0\n").encode(),
        (HEADER + "id,Bad,52.5,13.4,99\n").encode(),
        (HEADER + "id,Bad,52.5,13.4,0,extra\n").encode(),
        (HEADER + '"id,"unclosed,52.5,13.4,0\n').encode(),
        b"\xff\xfe",
    ],
)
def test_malformed_inventory_is_rejected_without_partial_results(payload: bytes) -> None:
    with pytest.raises(VbbGtfsStaticStopError):
        inventory(payload)


def test_oversized_inventory_is_rejected_before_csv_parsing() -> None:
    with pytest.raises(VbbGtfsStaticStopError, match="size"):
        inventory(b"x" * (MAX_STOPS_TXT_BYTES + 1))


def test_naive_retrieval_time_is_rejected() -> None:
    with pytest.raises(VbbGtfsStaticStopError, match="timezone-aware"):
        inventory(retrieved_at=NOW.replace(tzinfo=None))


def test_inventory_digest_changes_with_source_bytes() -> None:
    first = inventory().resolve("de:stop/1")
    second = inventory((STOPS + "third,Third,52.6,13.5,0\n").encode()).resolve(
        "de:stop/1"
    )

    assert first is not None and second is not None
    assert first.entity == second.entity
    assert first.evidence[0].record_id != second.evidence[0].record_id
