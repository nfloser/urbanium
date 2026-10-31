"""Resolve explicit VBB Alert stop IDs from caller-supplied GTFS static evidence.

This module does not download a feed or interpret Alert route/trip selectors.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from io import BytesIO, StringIO
from re import fullmatch
from typing import TYPE_CHECKING, cast
from unicodedata import category
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, LargeZipFile, ZipFile
from zlib import error as ZlibError

from pydantic import BaseModel, ConfigDict, ValidationError

from urbanium.core.city import Identifier
from urbanium.core.entity import EntityReference, EvidenceReference, StateCategory
from urbanium.core.spatial import EntityPointLocation, Wgs84Point

if TYPE_CHECKING:
    from urbanium.providers.vbb.gtfs_rt import VbbAlertStopReference

MAX_STOPS_TXT_BYTES = 20_000_000
MAX_FEED_INFO_BYTES = 64_000
MAX_GTFS_ZIP_BYTES = 100_000_000
MAX_GTFS_ZIP_MEMBERS = 128
_REQUIRED_COLUMNS = {"stop_id", "stop_lat", "stop_lon"}
_LOCATION_TYPES = {"", "0", "1", "2", "3", "4"}
_COORDINATE_PATTERN = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"


class VbbGtfsStaticStopError(ValueError):
    """A supplied GTFS stops.txt cannot be trusted as a complete inventory."""


class VbbGtfsStaticStopConfig(BaseModel):
    """Explicit city and source binding for a supplied static GTFS inventory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    city_id: Identifier
    source_id: Identifier


@dataclass(frozen=True, slots=True)
class VbbResolvedStopReference:
    """A selector reference and an optional sourced stop point, not an impact."""

    reference: VbbAlertStopReference
    location: EntityPointLocation | None


class VbbGtfsStaticStopInventory:
    """Parse a bounded stops.txt once and resolve exact source stop IDs.

    The caller is responsible for obtaining, licensing and retaining the
    original static feed and for checking its compatibility with GTFS-RT.
    """

    def __init__(
        self,
        config: VbbGtfsStaticStopConfig,
        *,
        stops_txt: bytes,
        retrieved_at: datetime,
    ) -> None:
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise VbbGtfsStaticStopError("retrieved_at must be timezone-aware")
        if len(stops_txt) > MAX_STOPS_TXT_BYTES:
            raise VbbGtfsStaticStopError("GTFS stops.txt exceeds size limit")

        self.config = config
        self.retrieved_at = retrieved_at
        self._digest = sha256(stops_txt).hexdigest()
        self._archive_digest: str | None = None
        self._feed_version: str | None = None
        self._feed_start_date: date | None = None
        self._feed_end_date: date | None = None
        self._points = _parse_stops(stops_txt)

    @classmethod
    def from_gtfs_zip(
        cls,
        config: VbbGtfsStaticStopConfig,
        *,
        archive_bytes: bytes,
        retrieved_at: datetime,
    ) -> VbbGtfsStaticStopInventory:
        """Read bounded stop and optional feed metadata from a supplied ZIP in memory."""

        if len(archive_bytes) > MAX_GTFS_ZIP_BYTES:
            raise VbbGtfsStaticStopError("GTFS ZIP archive exceeds size limit")

        try:
            with ZipFile(BytesIO(archive_bytes)) as archive:
                members = archive.infolist()
                if len(members) > MAX_GTFS_ZIP_MEMBERS:
                    raise VbbGtfsStaticStopError("GTFS ZIP has too many members")

                for member in members:
                    if member.flag_bits & 1:
                        raise VbbGtfsStaticStopError("encrypted GTFS ZIP member")
                    if member.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
                        raise VbbGtfsStaticStopError("unsupported GTFS ZIP compression")

                matches = [
                    member
                    for member in members
                    if member.filename == "stops.txt" and not member.is_dir()
                ]
                if len(matches) != 1:
                    raise VbbGtfsStaticStopError("GTFS ZIP requires one root stops.txt")

                if matches[0].file_size > MAX_STOPS_TXT_BYTES:
                    raise VbbGtfsStaticStopError("GTFS stops.txt exceeds size limit")
                with archive.open(matches[0]) as stop_stream:
                    stops_txt = stop_stream.read(MAX_STOPS_TXT_BYTES + 1)
                if len(stops_txt) > MAX_STOPS_TXT_BYTES:
                    raise VbbGtfsStaticStopError("GTFS stops.txt exceeds size limit")

                feed_info_matches = [
                    member
                    for member in members
                    if member.filename == "feed_info.txt" and not member.is_dir()
                ]
                if len(feed_info_matches) > 1:
                    raise VbbGtfsStaticStopError("duplicate GTFS feed_info.txt")
                feed_info: bytes | None = None
                if feed_info_matches:
                    if feed_info_matches[0].file_size > MAX_FEED_INFO_BYTES:
                        raise VbbGtfsStaticStopError("GTFS feed_info.txt exceeds size limit")
                    with archive.open(feed_info_matches[0]) as feed_info_stream:
                        feed_info = feed_info_stream.read(MAX_FEED_INFO_BYTES + 1)
                    if len(feed_info) > MAX_FEED_INFO_BYTES:
                        raise VbbGtfsStaticStopError("GTFS feed_info.txt exceeds size limit")
        except VbbGtfsStaticStopError:
            raise
        except (
            BadZipFile,
            LargeZipFile,
            EOFError,
            OSError,
            RuntimeError,
            ZlibError,
            ValueError,
            UnicodeError,
            OverflowError,
            NotImplementedError,
        ) as exc:
            raise VbbGtfsStaticStopError("invalid GTFS ZIP archive") from exc

        inventory = cls(config, stops_txt=stops_txt, retrieved_at=retrieved_at)
        inventory._archive_digest = sha256(archive_bytes).hexdigest()
        if feed_info is not None:
            (
                inventory._feed_version,
                inventory._feed_start_date,
                inventory._feed_end_date,
            ) = _parse_feed_info(feed_info)
        return inventory

    @property
    def feed_version(self) -> str | None:
        """Unverified feed_info.txt version label, not proof of feed compatibility."""

        return self._feed_version

    @property
    def feed_start_date(self) -> date | None:
        """Publisher-declared first service date, not independently verified."""

        return self._feed_start_date

    @property
    def feed_end_date(self) -> date | None:
        """Publisher-declared last service date, not independently verified."""

        return self._feed_end_date

    @property
    def archive_sha256(self) -> str | None:
        """Fingerprint of the supplied release, absent for direct stops.txt input."""

        return self._archive_digest

    def resolve(self, stop_id: str) -> EntityPointLocation | None:
        """Look up an exact ID; absence or missing coordinates remain unknown."""

        point = self._points.get(stop_id)
        if point is None:
            return None

        # GTFS IDs may contain punctuation not permitted in canonical entity IDs.
        # Hash the raw UTF-8 ID rather than stripping characters or conflating IDs.
        stop_hash = sha256(stop_id.encode("utf-8")).hexdigest()
        record_id = f"stops.txt:{stop_hash}:{self._digest}"
        if self._archive_digest is not None:
            record_id += f":gtfs.zip:{self._archive_digest}"
        return EntityPointLocation(
            entity=EntityReference(
                city_id=self.config.city_id,
                entity_type="transport_stop",
                entity_id=f"gtfs_stop_{stop_hash}",
            ),
            point=point,
            state_category=StateCategory.REFERENCE,
            asserted_at=self.retrieved_at,
            evidence=(
                EvidenceReference(
                    city_id=self.config.city_id,
                    source_id=self.config.source_id,
                    record_id=record_id,
                    retrieved_at=self.retrieved_at,
                ),
            ),
        )

    def resolve_alert_stop_references(
        self,
        references: Iterable[VbbAlertStopReference],
    ) -> tuple[VbbResolvedStopReference, ...]:
        """Preserve each Alert selector, including repeats and unresolved IDs."""

        return tuple(
            VbbResolvedStopReference(reference=ref, location=self.resolve(ref.stop_id))
            for ref in references
        )


def _parse_stops(payload: bytes) -> dict[str, Wgs84Point | None]:
    try:
        reader = csv.DictReader(StringIO(payload.decode("utf-8-sig"), newline=""), strict=True)
        header = reader.fieldnames
        if (
            header is None
            or len(set(header)) != len(header)
            or not _REQUIRED_COLUMNS <= set(header)
        ):
            raise VbbGtfsStaticStopError("invalid GTFS stops.txt header")

        points: dict[str, Wgs84Point | None] = {}
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise VbbGtfsStaticStopError("malformed GTFS stops.txt row")

            stop_id = cast(str, row["stop_id"])
            if not stop_id.strip() or "\x00" in stop_id:
                raise VbbGtfsStaticStopError("invalid GTFS stop_id")
            if stop_id in points:
                raise VbbGtfsStaticStopError("duplicate GTFS stop_id")

            if "location_type" in row and row["location_type"] not in _LOCATION_TYPES:
                raise VbbGtfsStaticStopError("invalid GTFS location_type")

            latitude = cast(str, row["stop_lat"]).strip()
            longitude = cast(str, row["stop_lon"]).strip()
            if bool(latitude) != bool(longitude):
                raise VbbGtfsStaticStopError("incomplete GTFS stop coordinates")

            if latitude:
                if not (
                    fullmatch(_COORDINATE_PATTERN, latitude)
                    and fullmatch(_COORDINATE_PATTERN, longitude)
                ):
                    raise VbbGtfsStaticStopError("invalid GTFS stop coordinate syntax")
                try:
                    point = Wgs84Point(latitude=float(latitude), longitude=float(longitude))
                except (ValueError, ValidationError) as exc:
                    raise VbbGtfsStaticStopError("invalid GTFS stop coordinates") from exc
            else:
                point = None
            points[stop_id] = point
        if not points:
            raise VbbGtfsStaticStopError("GTFS stops.txt has no stop records")
        return points
    except (UnicodeDecodeError, csv.Error) as exc:
        raise VbbGtfsStaticStopError("malformed GTFS stops.txt encoding or CSV") from exc


def _parse_feed_info(payload: bytes) -> tuple[str | None, date | None, date | None]:
    """Read optional publisher labels and service dates, not full GTFS feed_info."""

    try:
        reader = csv.DictReader(StringIO(payload.decode("utf-8-sig"), newline=""), strict=True)
        fields = reader.fieldnames
        if fields is None or not all(fields) or len(fields) != len(set(fields)):
            raise VbbGtfsStaticStopError("invalid GTFS feed_info.txt header")

        rows = list(reader)
        if len(rows) != 1 or any(
            None in row or any(value is None for value in row.values()) for row in rows
        ):
            raise VbbGtfsStaticStopError("invalid GTFS feed_info.txt row")

        row = rows[0]
        version = cast(str | None, row.get("feed_version"))
        if version is not None and not version.strip():
            version = None
        if version is not None and any(category(char) == "Cc" for char in version):
            raise VbbGtfsStaticStopError("invalid GTFS feed_version")

        start = _parse_feed_date(cast(str | None, row.get("feed_start_date")), "feed_start_date")
        end = _parse_feed_date(cast(str | None, row.get("feed_end_date")), "feed_end_date")
        if start is not None and end is not None and start > end:
            raise VbbGtfsStaticStopError("invalid GTFS feed date range")
        return version, start, end
    except (UnicodeDecodeError, csv.Error) as exc:
        raise VbbGtfsStaticStopError("malformed GTFS feed_info.txt encoding or CSV") from exc


def _parse_feed_date(raw: str | None, field: str) -> date | None:
    if raw is None or not raw.strip():
        return None
    if fullmatch(r"[0-9]{8}", raw) is None:
        raise VbbGtfsStaticStopError(f"invalid GTFS {field}")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise VbbGtfsStaticStopError(f"invalid GTFS {field}") from exc
