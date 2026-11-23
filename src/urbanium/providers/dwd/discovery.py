"""Discover DWD air-temperature stations inside a city's area from the inventory."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from yaml import YAMLError, safe_load

from urbanium.core.city import CityDefinition, Identifier
from urbanium.core.discovery import DiscoveredEntity, DiscoveryResult, DiscoveryStatus
from urbanium.core.entity import EntityReference, EvidenceReference, StateCategory
from urbanium.core.provider import ProviderError, ProviderErrorCode
from urbanium.core.spatial import EntityPointLocation, distance_km
from urbanium.providers.dwd.air_temperature import DWD_NOW_BASE_URL
from urbanium.providers.dwd.station_location import (
    MAX_STATION_LIST_BYTES,
    DwdStationMetadataError,
    DwdStationRecord,
    fetch_station_inventory,
    inventory_records,
    parse_inventory_record,
)

NOW_STATION_LIST_FILENAME = "zehn_now_tu_Beschreibung_Stationen.txt"
# The `now` inventory lists the stations of the current `now` archives and its
# end dates are current, unlike the historical inventory.
DWD_NOW_STATION_LIST_URL = f"{DWD_NOW_BASE_URL}/{NOW_STATION_LIST_FILENAME}"
FetchBytes = Callable[[str, float], bytes]
Clock = Callable[[], datetime]


class DwdAreaConfigurationError(ValueError):
    """Raised when an area-based DWD binding cannot be loaded."""


class DwdAreaConfig(BaseModel):
    """Bind DWD air temperature to every recently active station in the city area."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    city_id: Identifier
    source_id: Identifier
    freshness_minutes: int = Field(default=90, ge=10, le=1440)
    # Stations whose inventory end date is older than this are treated as closed.
    active_within_days: int = Field(default=7, ge=1, le=3650)
    max_stations: int = Field(default=30, ge=1, le=200)


def load_dwd_area_config(path: Path) -> DwdAreaConfig:
    try:
        raw = safe_load(path.read_text(encoding="utf-8"))
    except (OSError, YAMLError) as exc:
        raise DwdAreaConfigurationError(f"failed to read DWD area config {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise DwdAreaConfigurationError(f"DWD area config {path} must contain a mapping")
    try:
        return DwdAreaConfig.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(error["msg"] for error in exc.errors())
        raise DwdAreaConfigurationError(f"invalid DWD area config {path}: {details}") from exc


class DwdStationDiscovery:
    """Find DWD 10-minute temperature stations published inside a city area.

    Inventory presence means the station *existed recently*; whether it
    currently delivers values is decided later by the measurement read.
    """

    def __init__(
        self,
        config: DwdAreaConfig,
        *,
        fetcher: FetchBytes | None = None,
        clock: Clock | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.config = config
        self._fetcher = fetcher or fetch_station_inventory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._timeout = timeout

    @property
    def city_id(self) -> str:
        return self.config.city_id

    @property
    def source_id(self) -> str:
        return self.config.source_id

    def discover(self, city: CityDefinition) -> DiscoveryResult:
        if city.id != self.config.city_id or city.area is None:
            raise ValueError("DWD discovery requires its own city with a declared area")
        area = city.area
        envelope = area.search_envelope

        try:
            payload = self._fetcher(DWD_NOW_STATION_LIST_URL, self._timeout)
        except TimeoutError:
            return self._unavailable(ProviderErrorCode.TIMEOUT, "DWD inventory request timed out")
        except (OSError, ValueError):
            return self._unavailable(ProviderErrorCode.UPSTREAM, "DWD inventory request failed")
        discovered_at = self._clock()

        try:
            if len(payload) > MAX_STATION_LIST_BYTES:
                raise DwdStationMetadataError("DWD station inventory exceeds size limit")
            rows = inventory_records(payload)
        except (DwdStationMetadataError, UnicodeError):
            return self._unavailable(ProviderErrorCode.INVALID_RESPONSE, "invalid DWD inventory")

        active_since = (discovered_at - timedelta(days=self.config.active_within_days)).date()
        candidates: dict[str, DwdStationRecord] = {}
        ambiguous: set[str] = set()
        for columns in rows:
            try:
                record = parse_inventory_record(columns)
            except DwdStationMetadataError:
                continue
            if record.end < active_since or not envelope.contains(record.point):
                continue
            if record.station_id in candidates:
                ambiguous.add(record.station_id)  # duplicate rows: trust neither
            candidates[record.station_id] = record

        center = area.center
        selected = sorted(
            (record for key, record in candidates.items() if key not in ambiguous),
            key=lambda item: (round(distance_km(center, item.point), 6), item.station_id),
        )[: self.config.max_stations]

        digest = sha256(payload).hexdigest()
        return DiscoveryResult(
            city_id=self.city_id,
            source_id=self.source_id,
            status=DiscoveryStatus.AVAILABLE,
            discovered_at=discovered_at,
            entities=tuple(self._entity(record, digest, discovered_at) for record in selected),
        )

    def _entity(
        self, record: DwdStationRecord, digest: str, discovered_at: datetime
    ) -> DiscoveredEntity:
        attributes: dict[str, str | int | float | bool] = {
            "station_id": record.station_id,
            "elevation_m": record.elevation_m,
        }
        if record.state:
            attributes["state"] = record.state
        attributes["inventory_until"] = record.end.isoformat()
        return DiscoveredEntity(
            location=EntityPointLocation(
                entity=EntityReference(
                    city_id=self.city_id,
                    entity_type="weather_station",
                    entity_id=f"dwd_station_{record.station_id}",
                ),
                point=record.point,
                state_category=StateCategory.REFERENCE,
                asserted_at=discovered_at,
                evidence=(
                    EvidenceReference(
                        city_id=self.city_id,
                        source_id=self.source_id,
                        record_id=f"{NOW_STATION_LIST_FILENAME}:{record.station_id}:{digest}",
                        retrieved_at=discovered_at,
                    ),
                ),
            ),
            label=record.name,
            attributes=attributes,
        )

    def _unavailable(self, code: ProviderErrorCode, message: str) -> DiscoveryResult:
        return DiscoveryResult(
            city_id=self.city_id,
            source_id=self.source_id,
            status=DiscoveryStatus.UNAVAILABLE,
            discovered_at=self._clock(),
            error=ProviderError(code=code, message=message),
        )
