"""Read DWD's published station inventory without inferring measurement coverage."""

from collections.abc import Callable
from datetime import UTC, date, datetime
from hashlib import sha256
from re import fullmatch
from typing import cast
from urllib.request import urlopen

from pydantic import BaseModel, ConfigDict, ValidationError

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
        self._fetcher = fetcher or fetch_station_inventory
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

        records = inventory_records(payload)
        matches = [columns for columns in records if columns[0] == self.config.station_id]
        if not matches:
            return None
        if len(matches) != 1:
            raise DwdStationMetadataError("duplicate DWD station inventory records")
        point = parse_inventory_record(matches[0]).point

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


class DwdStationRecord(BaseModel):
    """One parsed row of the DWD station inventory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    station_id: str
    begin: date
    end: date
    elevation_m: int
    point: Wgs84Point
    name: str
    state: str | None


def inventory_records(payload: bytes) -> list[list[str]]:
    """Split the inventory into raw record columns after validating its header.

    Rows are split into at most seven columns; the last column keeps the
    free-text station name together with state and delivery fields.
    """

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
        line.split(maxsplit=6)
        for line in lines[1:]
        if line.strip() and not all(char in "- " for char in line.strip())
    ]
    if not records:
        raise DwdStationMetadataError("DWD station inventory has no station records")
    return records


def parse_inventory_record(columns: list[str]) -> DwdStationRecord:
    """Parse one inventory row; never guesses missing coordinates or dates."""

    if len(columns) != 7:
        raise DwdStationMetadataError("incomplete DWD station inventory record")
    try:
        if not fullmatch(r"\d{5}", columns[0]):
            raise ValueError("invalid station id")
        if not all(fullmatch(r"\d{8}", value) for value in columns[1:3]):
            raise ValueError("invalid station coverage dates")
        begin = datetime.strptime(columns[1], "%Y%m%d").date()
        end = datetime.strptime(columns[2], "%Y%m%d").date()
        if begin > end:
            raise ValueError("reversed station coverage dates")
        if not all(fullmatch(_COORDINATE_PATTERN, value) for value in columns[4:6]):
            raise ValueError("invalid station coordinate syntax")
        point = Wgs84Point(latitude=float(columns[4]), longitude=float(columns[5]))
        elevation = int(columns[3])
    except (ValueError, ValidationError) as exc:
        raise DwdStationMetadataError("invalid DWD station inventory record") from exc
    name, state = _split_name_and_state(columns[6])
    return DwdStationRecord(
        station_id=columns[0],
        begin=begin,
        end=end,
        elevation_m=elevation,
        point=point,
        name=name,
        state=state,
    )


_DELIVERY_FLAGS = {"frei", "gesperrt"}
_STATES = (
    "Baden-Württemberg",
    "Bayern",
    "Berlin",
    "Brandenburg",
    "Bremen",
    "Hamburg",
    "Hessen",
    "Mecklenburg-Vorpommern",
    "Niedersachsen",
    "Nordrhein-Westfalen",
    "Rheinland-Pfalz",
    "Saarland",
    "Sachsen-Anhalt",
    "Sachsen",
    "Schleswig-Holstein",
    "Thüringen",
)


def _split_name_and_state(text: str) -> tuple[str, str | None]:
    tokens = text.split()
    if tokens and tokens[-1].casefold() in _DELIVERY_FLAGS:
        tokens = tokens[:-1]
    if len(tokens) > 1 and tokens[-1] in _STATES:
        return " ".join(tokens[:-1]), tokens[-1]
    return " ".join(tokens), None


def fetch_station_inventory(url: str, timeout: float) -> bytes:
    # The URL is a fixed DWD endpoint, not caller-controlled input.
    with urlopen(url, timeout=timeout) as response:  # noqa: S310
        return cast(bytes, response.read(MAX_STATION_LIST_BYTES + 1))


def _utc_now() -> datetime:
    return datetime.now(UTC)
