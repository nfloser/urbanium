"""DWD CDC 10-minute air-temperature adapter."""

from collections.abc import Callable
from csv import DictReader
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
from pathlib import Path
from re import compile
from typing import Literal, cast
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from yaml import YAMLError, safe_load

from urbanium.core.city import Identifier
from urbanium.core.entity import EntityReference
from urbanium.core.provider import (
    Availability,
    Freshness,
    Observation,
    ProviderDescriptor,
    ProviderError,
    ProviderErrorCode,
    ProviderResult,
)

DWD_NOW_BASE_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/observations_germany/"
    "climate/10_minutes/air_temperature/now"
)
MAX_ARCHIVE_BYTES = 2_000_000
MAX_MEMBER_BYTES = 2_000_000
FetchBytes = Callable[[str, float], bytes]
Clock = Callable[[], datetime]
PRODUCT_MEMBER = compile(r"^produkt_zehn_now_tu_\d{8}_\d{8}_(\d{5})\.txt$")


class DwdAirTemperatureConfigurationError(ValueError):
    """Raised when deployment-specific DWD configuration is invalid."""


class DwdAirTemperatureConfig(BaseModel):
    """City deployment binding for one DWD air-temperature station."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    city_id: Identifier
    source_id: Identifier
    station_id: str = Field(pattern=r"^\d{5}$")
    station_name: str = Field(min_length=1)
    freshness_minutes: int = Field(default=90, ge=10, le=1440)


def load_dwd_air_temperature_config(path: Path) -> DwdAirTemperatureConfig:
    """Load a provider-specific city binding without extending core schemas."""

    try:
        raw = safe_load(path.read_text(encoding="utf-8"))
    except (OSError, YAMLError) as exc:
        raise DwdAirTemperatureConfigurationError(
            f"failed to read DWD config {path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise DwdAirTemperatureConfigurationError(f"DWD config {path} must contain a mapping")
    try:
        return DwdAirTemperatureConfig.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(error["msg"] for error in exc.errors())
        raise DwdAirTemperatureConfigurationError(f"invalid DWD config {path}: {details}") from exc


class DwdCdcAirTemperatureProvider:
    """Normalize the latest valid DWD CDC `TT_10` observation."""

    def __init__(
        self,
        config: DwdAirTemperatureConfig,
        *,
        fetcher: FetchBytes | None = None,
        clock: Clock | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.config = config
        self._fetcher = fetcher or _fetch_bytes
        self._clock = clock or _utc_now
        self._timeout = timeout

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            city_id=self.config.city_id,
            source_id=self.config.source_id,
            capability_id="weather",
            adapter_version="1.0.0",
        )

    @property
    def url(self) -> str:
        return f"{DWD_NOW_BASE_URL}/10minutenwerte_TU_{self.config.station_id}_now.zip"

    def read(self) -> ProviderResult:
        received_at = self._clock()
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            return _unavailable(ProviderErrorCode.UNKNOWN, "provider clock is not timezone-aware")
        try:
            archive = self._fetcher(self.url, self._timeout)
            observations, invalid_rows = self._parse_archive(archive, received_at)
        except TimeoutError:
            return _unavailable(ProviderErrorCode.TIMEOUT, "DWD request timed out")
        except OSError:
            return _unavailable(ProviderErrorCode.UPSTREAM, "DWD request failed")
        except (BadZipFile, KeyError, UnicodeError, ValueError):
            return _unavailable(ProviderErrorCode.INVALID_RESPONSE, "invalid DWD archive")

        if not observations:
            return _unavailable(
                ProviderErrorCode.INVALID_RESPONSE,
                "DWD archive contains no valid air-temperature observations",
            )

        latest = max(observations, key=lambda item: item.observed_at)
        age = received_at.astimezone(UTC) - latest.observed_at.astimezone(UTC)
        freshness = (
            Freshness.FRESH
            if age <= timedelta(minutes=self.config.freshness_minutes)
            else Freshness.STALE
        )
        if invalid_rows:
            return ProviderResult(
                availability=Availability.DEGRADED,
                freshness=freshness,
                observations=(latest,),
                error=ProviderError(
                    code=ProviderErrorCode.INVALID_RESPONSE,
                    message=f"ignored {invalid_rows} invalid DWD row(s)",
                ),
            )
        return ProviderResult(
            availability=Availability.AVAILABLE,
            freshness=freshness,
            observations=(latest,),
        )

    def _parse_archive(
        self, archive: bytes, received_at: datetime
    ) -> tuple[list[Observation], int]:
        if len(archive) > MAX_ARCHIVE_BYTES:
            raise ValueError("DWD archive exceeds size limit")
        with ZipFile(BytesIO(archive)) as source:
            members = []
            for item in source.infolist():
                match = PRODUCT_MEMBER.fullmatch(item.filename)
                if match and match.group(1) == self.config.station_id and not item.is_dir():
                    members.append(item)
            if len(members) != 1 or members[0].file_size > MAX_MEMBER_BYTES:
                raise ValueError("DWD archive has an unexpected product member")
            with source.open(members[0]) as member:
                raw_payload = member.read(MAX_MEMBER_BYTES + 1)
            if len(raw_payload) > MAX_MEMBER_BYTES:
                raise ValueError("DWD product member exceeds size limit")
            payload = raw_payload.decode("latin-1")
        return self._parse_csv(payload, received_at)

    def _parse_csv(self, payload: str, received_at: datetime) -> tuple[list[Observation], int]:
        reader = DictReader(StringIO(payload), delimiter=";")
        if reader.fieldnames is None:
            raise ValueError("DWD CSV has no header")
        reader.fieldnames = [name.strip() for name in reader.fieldnames]
        required = {"STATIONS_ID", "MESS_DATUM", "QN", "TT_10"}
        if not required.issubset(reader.fieldnames):
            raise ValueError("DWD CSV is missing required columns")

        observations: list[Observation] = []
        invalid_rows = 0
        for raw_row in reader:
            row = {key.strip(): (value or "").strip() for key, value in raw_row.items() if key}
            if row.get("TT_10") == "-999":
                continue
            try:
                station_id = row["STATIONS_ID"].zfill(5)
                if station_id != self.config.station_id:
                    raise ValueError("unexpected DWD station")
                observed_at = datetime.strptime(row["MESS_DATUM"], "%Y%m%d%H%M").replace(tzinfo=UTC)
                value = Decimal(row["TT_10"])
                if not value.is_finite():
                    raise ValueError("non-finite DWD value")
                observations.append(
                    Observation(
                        city_id=self.config.city_id,
                        source_id=self.config.source_id,
                        capability_id="weather",
                        entity=EntityReference(
                            city_id=self.config.city_id,
                            entity_type="weather_station",
                            entity_id=f"dwd_station_{station_id}",
                        ),
                        quantity_id="air_temperature",
                        value=value,
                        unit="Cel",
                        observed_at=observed_at,
                        received_at=received_at,
                        quality_scheme="dwd_qn",
                        quality_code=row["QN"],
                    )
                )
            except (InvalidOperation, KeyError, ValueError):
                invalid_rows += 1
        return observations, invalid_rows


def _unavailable(code: ProviderErrorCode, message: str) -> ProviderResult:
    return ProviderResult(
        availability=Availability.UNAVAILABLE,
        freshness=Freshness.UNKNOWN,
        error=ProviderError(code=code, message=message),
    )


def _fetch_bytes(url: str, timeout: float) -> bytes:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - URL is fixed by the adapter
        payload = cast(bytes, response.read(MAX_ARCHIVE_BYTES + 1))
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise ValueError("DWD archive exceeds size limit")
    return payload


def _utc_now() -> datetime:
    return datetime.now(UTC)
