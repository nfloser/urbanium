"""Read DWD's published station inventory without inferring measurement coverage."""

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from re import fullmatch
from typing import cast
from urllib.request import urlopen

from pydantic import ValidationError

from urbanium.core.entity import EntityReference, EvidenceReference, StateCategory
from urbanium.core.spatial import EntityPointLocation, Wgs84Point
from urbanium.providers.dwd.air_temperature import DwdAirTemperatureConfig

DWD_STATION_LIST_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/observations_germany/"
    "climate/10_minutes/air_temperature/historical/"
    "zehn_min_tu_Beschreibung_Stationen.txt"
)
STATION_LIST_FILENAME = "zehn_min_tu_Beschreibung_Stationen.txt"
MAX_STATION_LIST_BYTES = 1_000_000
_COORDINATE_PATTERN = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
FetchBytes = Callable[[str, float], bytes]
Clock = Callable[[], datetime]


class DwdStationMetadataError(ValueError):
    """The DWD inventory could not be retrieved or interpreted safely."""


class DwdCdcStationLocationProvider:
    """Resolve the latest published station point for one configured DWD station.

    An absent station returns None. Transport, format and coordinate errors
    raise DwdStationMetadataError; none of these paths invent a location.
    """

    def __init__(
        self,
        config: DwdAirTemperatureConfig,
        *,
        fetcher: FetchBytes | None = None,
        clock: Clock | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.config = config
        self._fetcher = fetcher or _fetch_station_list
        self._clock = clock or _utc_now
        self._timeout = timeout

    def read(self) -> EntityPointLocation | None:
        try:
            payload = self._fetcher(DWD_STATION_LIST_URL, self._timeout)
        except (OSError, TimeoutError) as exc:
            raise DwdStationMetadataError("DWD station inventory request failed") from exc

        if len(payload) > MAX_STATION_LIST_BYTES:
            raise DwdStationMetadataError("DWD station inventory exceeds size limit")

        retrieved_at = self._clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise DwdStationMetadataError("inventory clock must be timezone-aware")

        lines = payload.decode("latin-1").splitlines()
        header_fields = lines[0].casefold().split() if lines else []
        if header_fields[:6] != [
            "stations_id",
            "von_datum",
            "bis_datum",
            "stationshoehe",
            "geobreite",
            "geolaenge",
        ]:
            raise DwdStationMetadataError("unexpected DWD station inventory header")

        records = [
            line
            for line in lines[1:]
            if line.strip() and not all(char in "- " for char in line.strip())
        ]
        if not records:
            raise DwdStationMetadataError("DWD station inventory has no station records")

        matches = [
            line.split(maxsplit=6)
            for line in records
            if line.split(maxsplit=1)[:1] == [self.config.station_id]
        ]
        if not matches:
            return None
        if len(matches) != 1:
            raise DwdStationMetadataError("duplicate DWD station inventory records")

        columns = matches[0]
        if len(columns) != 7:
            raise DwdStationMetadataError("incomplete DWD station inventory record")
        try:
            if not all(fullmatch(r"\d{8}", value) for value in columns[1:3]):
                raise ValueError("invalid station coverage dates")
            begin = datetime.strptime(columns[1], "%Y%m%d")
            end = datetime.strptime(columns[2], "%Y%m%d")
            if begin > end:
                raise ValueError("reversed station coverage dates")
            if not all(fullmatch(_COORDINATE_PATTERN, value) for value in columns[4:6]):
                raise ValueError("invalid station coordinate syntax")
            point = Wgs84Point(latitude=float(columns[4]), longitude=float(columns[5]))
        except (ValueError, ValidationError) as exc:
            raise DwdStationMetadataError("invalid DWD station inventory record") from exc

        record_id = (
            f"{STATION_LIST_FILENAME}:{self.config.station_id}:{sha256(payload).hexdigest()}"
        )
        return EntityPointLocation(
            entity=EntityReference(
                city_id=self.config.city_id,
                entity_type="weather_station",
                entity_id=f"dwd_station_{self.config.station_id}",
            ),
            point=point,
            state_category=StateCategory.REFERENCE,
            asserted_at=retrieved_at,
            evidence=(
                EvidenceReference(
                    city_id=self.config.city_id,
                    source_id=self.config.source_id,
                    record_id=record_id,
                    retrieved_at=retrieved_at,
                ),
            ),
        )


def _fetch_station_list(url: str, timeout: float) -> bytes:
    # The URL is a fixed DWD endpoint, not caller-controlled input.
    with urlopen(url, timeout=timeout) as response:  # noqa: S310
        return cast(bytes, response.read(MAX_STATION_LIST_BYTES + 1))


def _utc_now() -> datetime:
    return datetime.now(UTC)
