"""Offline GTFS ZIP ingestion must not weaken the existing stop-point evidence boundary."""

from datetime import UTC, date, datetime
from hashlib import sha256
from io import BytesIO
from warnings import catch_warnings, filterwarnings
from zipfile import ZIP_BZIP2, ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest

from urbanium.providers.vbb.gtfs_rt import VbbAlertStopReference
from urbanium.providers.vbb.static_stops import (
    VbbGtfsStaticStopConfig,
    VbbGtfsStaticStopError,
    VbbGtfsStaticStopInventory,
)

NOW = datetime(2026, 10, 25, 14, tzinfo=UTC)
STOPS = b"stop_id,stop_lat,stop_lon\nde:1,52.5,13.4\nde:2,,\n"
CONFIG = VbbGtfsStaticStopConfig(city_id="berlin", source_id="vbb_gtfs_static")


def archive(
    entries: tuple[tuple[str, bytes], ...] = (("stops.txt", STOPS),),
    *,
    compression: int = ZIP_DEFLATED,
) -> bytes:
    buffer = BytesIO()
    with catch_warnings():
        filterwarnings("ignore", message="Duplicate name:.*", category=UserWarning)
        with ZipFile(buffer, "w", compression=compression) as zip_file:
            for name, payload in entries:
                zip_file.writestr(name, payload)
    return buffer.getvalue()


def load(payload: bytes) -> VbbGtfsStaticStopInventory:
    return VbbGtfsStaticStopInventory.from_gtfs_zip(CONFIG, archive_bytes=payload, retrieved_at=NOW)


def test_archive_lookup_preserves_source_and_archive_fingerprints() -> None:
    payload = archive(
        (("trips.txt", b"trip_id\nt1\n"), ("stops.txt", STOPS), ("notes/readme.txt", b"x"))
    )
    source = load(payload)
    location = source.resolve("de:1")

    assert source.archive_sha256 == sha256(payload).hexdigest()
    assert location is not None
    assert location.point.latitude == 52.5
    assert location.point.longitude == 13.4
    assert location.evidence[0].record_id.endswith(
        f":{sha256(STOPS).hexdigest()}:gtfs.zip:{sha256(payload).hexdigest()}"
    )
    assert source.resolve("de:2") is None
    assert source.resolve("unknown") is None


def test_identical_stops_in_different_releases_retain_distinct_provenance() -> None:
    first = load(archive((("stops.txt", STOPS),)))
    second = load(archive((("stops.txt", STOPS), ("calendar.txt", b"service_id\nx\n"))))
    first_point = first.resolve("de:1")
    second_point = second.resolve("de:1")

    assert first_point is not None and second_point is not None
    assert first_point.entity == second_point.entity
    assert first_point.point == second_point.point
    assert first_point.evidence != second_point.evidence


def test_archive_resolves_alert_stop_references_without_claiming_impact() -> None:
    references = (
        VbbAlertStopReference(alert_id="a", selector_index=0, stop_id="de:1"),
        VbbAlertStopReference(alert_id="a", selector_index=1, stop_id="missing"),
        VbbAlertStopReference(alert_id="b", selector_index=0, stop_id="de:1"),
    )
    matches = load(archive()).resolve_alert_stop_references(references)

    assert tuple(match.reference for match in matches) == references
    assert matches[0].location is not None
    assert matches[1].location is None
    assert matches[2].location == matches[0].location


def test_stored_zip_is_supported_without_filesystem_extraction() -> None:
    assert load(archive(compression=ZIP_STORED)).resolve("de:1") is not None


def test_direct_stops_input_retains_its_original_provenance_shape() -> None:
    direct = VbbGtfsStaticStopInventory(CONFIG, stops_txt=STOPS, retrieved_at=NOW)
    assert direct.archive_sha256 is None
    point = direct.resolve("de:1")
    assert point is not None
    assert point.evidence[0].record_id.endswith(sha256(STOPS).hexdigest())


def test_header_only_stops_are_rejected_from_direct_and_zip_inputs() -> None:
    header_only = b"stop_id,stop_lat,stop_lon\n"
    with pytest.raises(VbbGtfsStaticStopError, match="no stop records"):
        VbbGtfsStaticStopInventory(CONFIG, stops_txt=header_only, retrieved_at=NOW)
    with pytest.raises(VbbGtfsStaticStopError, match="no stop records"):
        load(archive((("stops.txt", header_only),)))


def test_inventory_with_only_missing_coordinates_is_still_valid() -> None:
    without_points = b"stop_id,stop_lat,stop_lon\nde:1,,\nde:2,,\n"
    direct = VbbGtfsStaticStopInventory(CONFIG, stops_txt=without_points, retrieved_at=NOW)
    zipped = load(archive((("stops.txt", without_points),)))
    assert direct.resolve("de:1") is None
    assert zipped.resolve("de:2") is None


def test_unsupported_member_compression_is_rejected() -> None:
    with pytest.raises(VbbGtfsStaticStopError, match="compression"):
        load(archive(compression=ZIP_BZIP2))


@pytest.mark.parametrize(
    "payload",
    [
        b"not a ZIP",
        archive(()),
        archive((("nested/stops.txt", STOPS),)),
        archive((("stops.txt", STOPS), ("stops.txt", STOPS))),
        archive((("stops.txt", b"stop_id,stop_lat\nx,1\n"),)),
    ],
)
def test_missing_ambiguous_or_invalid_stops_are_rejected(payload: bytes) -> None:
    with pytest.raises(VbbGtfsStaticStopError):
        load(payload)


def test_zip_archive_size_is_bounded_before_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urbanium.providers.vbb.static_stops.MAX_GTFS_ZIP_BYTES", 16)
    with pytest.raises(VbbGtfsStaticStopError, match="archive.*size"):
        load(archive())


def test_zip_member_count_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urbanium.providers.vbb.static_stops.MAX_GTFS_ZIP_MEMBERS", 2)
    with pytest.raises(VbbGtfsStaticStopError, match="members"):
        load(archive((("stops.txt", STOPS), ("a.txt", b"a"), ("b.txt", b"b"))))


def test_decompression_bomb_is_rejected_before_parsing() -> None:
    oversized = b"stop_id,stop_lat,stop_lon\n" + b"x" * 20_000_001
    with pytest.raises(VbbGtfsStaticStopError, match="stops.txt.*size"):
        load(archive((("stops.txt", oversized),)))


def test_corrupted_member_checksum_is_rejected() -> None:
    payload = archive(compression=ZIP_STORED)
    assert b"52.5" in payload
    corrupted = payload.replace(b"52.5", b"52.6", 1)
    with pytest.raises(VbbGtfsStaticStopError, match="ZIP"):
        load(corrupted)


def test_encrypted_member_is_rejected_even_if_unrelated_to_stops() -> None:
    payload = bytearray(archive((("stops.txt", STOPS), ("other.txt", b"x"))))
    # Set the encrypted flag in the second central-directory entry.
    first = payload.index(b"PK\x01\x02")
    second = payload.index(b"PK\x01\x02", first + 4)
    payload[second + 8] |= 1
    with pytest.raises(VbbGtfsStaticStopError, match="encrypted"):
        load(bytes(payload))


FEED_INFO = (
    b"feed_publisher_name,feed_publisher_url,feed_lang,feed_version\n"
    b"Example,https://example.test,de,2026-10-29\n"
)


def test_zip_exposes_declared_feed_version_without_changing_stop_identity() -> None:
    plain = load(archive())
    versioned_bytes = archive((("stops.txt", STOPS), ("feed_info.txt", FEED_INFO)))
    versioned = load(versioned_bytes)

    assert plain.feed_version is None
    assert versioned.feed_version == "2026-10-29"
    plain_point = plain.resolve("de:1")
    versioned_point = versioned.resolve("de:1")
    assert plain_point is not None and versioned_point is not None
    assert plain_point.entity == versioned_point.entity
    assert plain_point.point == versioned_point.point
    assert versioned_point.evidence[0].record_id.endswith(
        f":gtfs.zip:{sha256(versioned_bytes).hexdigest()}"
    )


def test_feed_version_is_optional_for_direct_and_zip_inputs() -> None:
    direct = VbbGtfsStaticStopInventory(CONFIG, stops_txt=STOPS, retrieved_at=NOW)
    without_version = b"feed_publisher_name,feed_lang\nExample,de\n"
    blank_version = b"feed_version\n  \n"

    assert direct.feed_version is None
    assert load(archive((("stops.txt", STOPS),))).feed_version is None
    no_label = load(archive((("stops.txt", STOPS), ("feed_info.txt", without_version))))
    assert no_label.feed_version is None
    blank_label = load(archive((("stops.txt", STOPS), ("feed_info.txt", blank_version))))
    assert blank_label.feed_version is None


def test_printable_unicode_feed_version_is_preserved() -> None:
    metadata = "feed_version\nrelease-Ä\n".encode()
    source = load(archive((("stops.txt", STOPS), ("feed_info.txt", metadata))))

    assert source.feed_version == "release-Ä"


def test_feed_info_exposes_declared_coverage_without_changing_stop_identity() -> None:
    metadata = (
        b"feed_version,feed_start_date,feed_end_date\n"
        b"release-1,20261001,20261031\n"
    )
    source = load(archive((("stops.txt", STOPS), ("feed_info.txt", metadata))))
    plain = load(archive())

    assert source.feed_version == "release-1"
    assert source.feed_start_date == date(2026, 10, 1)
    assert source.feed_end_date == date(2026, 10, 31)
    assert plain.feed_start_date is None
    assert plain.feed_end_date is None
    source_point = source.resolve("de:1")
    plain_point = plain.resolve("de:1")
    assert source_point is not None and plain_point is not None
    assert source_point.entity == plain_point.entity


def test_optional_feed_dates_allow_open_ended_or_blank_coverage() -> None:
    start_only = b"feed_start_date,feed_end_date\n20261001,\n"
    end_only = b"feed_start_date,feed_end_date\n,20261031\n"
    blank = b"feed_start_date,feed_end_date\n , \n"

    start = load(archive((("stops.txt", STOPS), ("feed_info.txt", start_only))))
    end = load(archive((("stops.txt", STOPS), ("feed_info.txt", end_only))))
    unknown = load(archive((("stops.txt", STOPS), ("feed_info.txt", blank))))

    assert (start.feed_start_date, start.feed_end_date) == (date(2026, 10, 1), None)
    assert (end.feed_start_date, end.feed_end_date) == (None, date(2026, 10, 31))
    assert (unknown.feed_start_date, unknown.feed_end_date) == (None, None)


@pytest.mark.parametrize(
    "metadata",
    [
        b"feed_start_date\n2026-10-01\n",
        b"feed_start_date\n2026101\n",
        b"feed_start_date\n20260230\n",
        b"feed_end_date\n20261301\n",
        "feed_start_date\n２０２６１００１\n".encode(),
        b"feed_start_date,feed_end_date\n20261101,20261031\n",
    ],
)
def test_invalid_declared_coverage_is_rejected(metadata: bytes) -> None:
    with pytest.raises(VbbGtfsStaticStopError, match="feed_start_date|feed_end_date|range"):
        load(archive((("stops.txt", STOPS), ("feed_info.txt", metadata))))


def test_duplicate_root_feed_info_is_rejected() -> None:
    with pytest.raises(VbbGtfsStaticStopError, match="feed_info"):
        load(
            archive(
                (("stops.txt", STOPS), ("feed_info.txt", FEED_INFO), ("feed_info.txt", FEED_INFO))
            )
        )


@pytest.mark.parametrize(
    "feed_info",
    [
        b"feed_version\n",
        b"feed_version,feed_version\nv1,v2\n",
        b"feed_version\nv1\nv2\n",
        b"feed_version\n\xff\n",
        b'feed_version\n"unterminated\n',
        b"feed_version\nv1,extra\n",
        b'feed_version\n"v1\nbad"\n',
        b"feed_version\nv1\x01\n",
        b"feed_version\nv1\x7f\n",
        b"feed_version\nv1\xc2\x85\n",
    ],
)
def test_malformed_feed_info_cannot_claim_a_release_version(feed_info: bytes) -> None:
    with pytest.raises(VbbGtfsStaticStopError, match="feed_info|feed_version"):
        load(archive((("stops.txt", STOPS), ("feed_info.txt", feed_info))))


def test_feed_info_decompression_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urbanium.providers.vbb.static_stops.MAX_FEED_INFO_BYTES", 32)
    with pytest.raises(VbbGtfsStaticStopError, match="feed_info.*size"):
        load(archive((("stops.txt", STOPS), ("feed_info.txt", FEED_INFO))))
