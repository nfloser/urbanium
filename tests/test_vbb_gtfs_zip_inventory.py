"""Offline GTFS ZIP ingestion must not weaken the existing stop-point evidence boundary."""

from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest

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
    with ZipFile(buffer, "w", compression=compression) as zip_file:
        for name, payload in entries:
            zip_file.writestr(name, payload)
    return buffer.getvalue()


def load(payload: bytes) -> VbbGtfsStaticStopInventory:
    return VbbGtfsStaticStopInventory.from_gtfs_zip(
        CONFIG, archive_bytes=payload, retrieved_at=NOW
    )


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


def test_stored_zip_is_supported_without_filesystem_extraction() -> None:
    assert load(archive(compression=ZIP_STORED)).resolve("de:1") is not None


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
