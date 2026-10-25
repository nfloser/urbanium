"""Resolve explicit VBB Alert stop IDs from caller-supplied GTFS static evidence.

This module does not download a feed or interpret Alert route/trip selectors.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from io import StringIO
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from urbanium.core.city import Identifier
from urbanium.core.entity import EntityReference, EvidenceReference, StateCategory
from urbanium.core.spatial import EntityPointLocation, Wgs84Point

if TYPE_CHECKING:
    from urbanium.providers.vbb.gtfs_rt import VbbAlertStopReference

MAX_STOPS_TXT_BYTES = 20_000_000
_REQUIRED_COLUMNS = {"stop_id", "stop_lat", "stop_lon"}
_LOCATION_TYPES = {"", "0", "1", "2", "3", "4"}


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
        self._points = _parse_stops(stops_txt)

    def resolve(self, stop_id: str) -> EntityPointLocation | None:
        """Look up an exact ID; absence or missing coordinates remain unknown."""

        point = self._points.get(stop_id)
        if point is None:
            return None

        # GTFS IDs may contain punctuation not permitted in canonical entity IDs.
        # Hash the raw UTF-8 ID rather than stripping characters or conflating IDs.
        stop_hash = sha256(stop_id.encode("utf-8")).hexdigest()
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
                    record_id=f"stops.txt:{stop_hash}:{self._digest}",
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
                try:
                    point = Wgs84Point(latitude=float(latitude), longitude=float(longitude))
                except (ValueError, ValidationError) as exc:
                    raise VbbGtfsStaticStopError("invalid GTFS stop coordinates") from exc
            else:
                point = None
            points[stop_id] = point
        return points
    except (UnicodeDecodeError, csv.Error) as exc:
        raise VbbGtfsStaticStopError("malformed GTFS stops.txt encoding or CSV") from exc
