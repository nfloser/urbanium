"""PEGELONLINE (WSV) water-level gauges: area discovery and measurement series."""

import json
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from math import ceil
from pathlib import Path
from re import fullmatch
from typing import Literal, cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from yaml import YAMLError, safe_load

from urbanium.core.city import CityDefinition, Identifier
from urbanium.core.discovery import DiscoveredEntity, DiscoveryResult, DiscoveryStatus
from urbanium.core.entity import EntityReference, EvidenceReference, StateCategory
from urbanium.core.provider import (
    Availability,
    Freshness,
    Observation,
    ProviderDescriptor,
    ProviderError,
    ProviderErrorCode,
    ProviderResult,
)
from urbanium.core.spatial import EntityPointLocation, Wgs84Point, distance_km

PEGELONLINE_BASE_URL = "https://www.pegelonline.wsv.de/webservices/rest-api/v2"
MAX_RESPONSE_BYTES = 4_000_000
WATER_LEVEL_TIMESERIES = "W"
ENTITY_TYPE = "river_gauge"
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

FetchBytes = Callable[[str, float], bytes]
Clock = Callable[[], datetime]


class PegelonlineConfigurationError(ValueError):
    """Raised when a PEGELONLINE binding cannot be loaded."""


class PegelonlineConfig(BaseModel):
    """Bind PEGELONLINE water levels for all gauges in a city's area."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    city_id: Identifier
    source_id: Identifier
    freshness_minutes: int = Field(default=60, ge=15, le=1500)
    history_hours: int = Field(default=24, ge=1, le=744)  # API keeps 31 days
    max_gauges: int = Field(default=25, ge=1, le=200)


def load_pegelonline_config(path: Path) -> PegelonlineConfig:
    try:
        raw = safe_load(path.read_text(encoding="utf-8"))
    except (OSError, YAMLError) as exc:
        raise PegelonlineConfigurationError(f"failed to read {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PegelonlineConfigurationError(f"PEGELONLINE config {path} must contain a mapping")
    try:
        return PegelonlineConfig.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(error["msg"] for error in exc.errors())
        raise PegelonlineConfigurationError(
            f"invalid PEGELONLINE config {path}: {details}"
        ) from exc


class PegelonlineGaugeDiscovery:
    """Find gauges with a water-level time series inside the city area."""

    def __init__(
        self,
        config: PegelonlineConfig,
        *,
        fetcher: FetchBytes | None = None,
        clock: Clock | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.config = config
        self._fetcher = fetcher or fetch_json_bytes
        self._clock = clock or (lambda: datetime.now(UTC))
        self._timeout = timeout

    @property
    def city_id(self) -> str:
        return self.config.city_id

    @property
    def source_id(self) -> str:
        return self.config.source_id

    def url(self, city: CityDefinition) -> str:
        if city.area is None:
            raise ValueError("PEGELONLINE discovery requires a city area")
        envelope = city.area.search_envelope
        center = envelope.center
        query = urlencode(
            {
                "latitude": f"{center.latitude:.5f}",
                "longitude": f"{center.longitude:.5f}",
                "radius": str(ceil(envelope.covering_radius_km) + 1),
                "includeTimeseries": "true",
                "includeCurrentMeasurement": "true",
            }
        )
        return f"{PEGELONLINE_BASE_URL}/stations.json?{query}"

    def discover(self, city: CityDefinition) -> DiscoveryResult:
        if city.id != self.city_id or city.area is None:
            raise ValueError("PEGELONLINE discovery requires its own city with a declared area")
        area = city.area.search_envelope
        try:
            payload = self._fetcher(self.url(city), self._timeout)
        except TimeoutError:
            return self._unavailable(ProviderErrorCode.TIMEOUT, "PEGELONLINE request timed out")
        except (OSError, ValueError):
            return self._unavailable(ProviderErrorCode.UPSTREAM, "PEGELONLINE request failed")
        discovered_at = self._clock()
        try:
            stations = json.loads(payload)
            if not isinstance(stations, list):
                raise ValueError("station list is not an array")
        except (UnicodeError, ValueError):
            return self._unavailable(
                ProviderErrorCode.INVALID_RESPONSE, "invalid PEGELONLINE station list"
            )

        digest = sha256(payload).hexdigest()
        candidates: list[tuple[float, str, DiscoveredEntity]] = []
        seen: set[str] = set()
        for raw in stations:
            entity = self._entity(raw, digest, discovered_at)
            if entity is None or not area.contains(entity.location.point):
                continue
            key = entity.location.entity.entity_id
            if key in seen:
                continue
            seen.add(key)
            distance = round(distance_km(area.center, entity.location.point), 6)
            candidates.append((distance, key, entity))
        candidates.sort(key=lambda item: (item[0], item[1]))
        return DiscoveryResult(
            city_id=self.city_id,
            source_id=self.source_id,
            status=DiscoveryStatus.AVAILABLE,
            discovered_at=discovered_at,
            entities=tuple(item[2] for item in candidates[: self.config.max_gauges]),
        )

    def _entity(self, raw: object, digest: str, discovered_at: datetime) -> DiscoveredEntity | None:
        """Map one station object; anything incomplete is skipped, never guessed."""

        if not isinstance(raw, dict):
            return None
        uuid, number = raw.get("uuid"), raw.get("number")
        if not isinstance(uuid, str) or not fullmatch(_UUID, uuid):
            return None
        if not isinstance(number, str) or not fullmatch(r"\d{1,12}", number):
            return None
        series = raw.get("timeseries")
        water_level = None
        if isinstance(series, list):
            water_level = next(
                (
                    item
                    for item in series
                    if isinstance(item, dict) and item.get("shortname") == WATER_LEVEL_TIMESERIES
                ),
                None,
            )
        if water_level is None:
            return None
        try:
            point = Wgs84Point(
                latitude=_number(raw.get("latitude")), longitude=_number(raw.get("longitude"))
            )
        except (TypeError, ValidationError):
            return None
        label = raw.get("longname") or raw.get("shortname")
        if not isinstance(label, str) or not label.strip():
            return None

        attributes: dict[str, str | int | float | bool] = {"uuid": uuid, "number": number}
        water = raw.get("water")
        if isinstance(water, dict) and isinstance(water.get("longname"), str):
            attributes["water"] = water["longname"]
        if isinstance(raw.get("agency"), str):
            attributes["agency"] = raw["agency"]
        if isinstance(raw.get("km"), int | float) and not isinstance(raw.get("km"), bool):
            attributes["river_km"] = float(raw["km"])
        zero = water_level.get("gaugeZero")
        if isinstance(zero, dict) and isinstance(zero.get("value"), int | float):
            attributes["gauge_zero_m"] = float(zero["value"])

        return DiscoveredEntity(
            location=EntityPointLocation(
                entity=EntityReference(
                    city_id=self.city_id,
                    entity_type=ENTITY_TYPE,
                    entity_id=f"pegelonline_{number}",
                ),
                point=point,
                state_category=StateCategory.REFERENCE,
                asserted_at=discovered_at,
                evidence=(
                    EvidenceReference(
                        city_id=self.city_id,
                        source_id=self.source_id,
                        record_id=f"stations.json:{uuid}:{digest}",
                        retrieved_at=discovered_at,
                    ),
                ),
            ),
            label=label.strip(),
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


class PegelonlineWaterLevelProvider:
    """Read the recent water-level series (`W`, cm above gauge zero) of discovered gauges."""

    def __init__(
        self,
        config: PegelonlineConfig,
        gauges: Iterable[DiscoveredEntity],
        *,
        fetcher: FetchBytes | None = None,
        clock: Clock | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.config = config
        self.gauges = tuple(gauges)
        for gauge in self.gauges:
            entity = gauge.location.entity
            if (
                entity.city_id != config.city_id
                or entity.entity_type != ENTITY_TYPE
                or any(item.source_id != config.source_id for item in gauge.location.evidence)
                or not isinstance(gauge.attributes.get("uuid"), str)
            ):
                raise ValueError(f"gauge '{entity.canonical_id}' does not belong to this binding")
        self._fetcher = fetcher or fetch_json_bytes
        self._clock = clock or (lambda: datetime.now(UTC))
        self._timeout = timeout

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            city_id=self.config.city_id,
            source_id=self.config.source_id,
            capability_id="river_level",
            adapter_version="1.0.0",
        )

    def measurement_url(self, gauge: DiscoveredEntity) -> str:
        uuid = cast(str, gauge.attributes["uuid"])
        hours = self.config.history_hours
        window = f"P{hours // 24}D" if hours % 24 == 0 else f"PT{hours}H"
        return (
            f"{PEGELONLINE_BASE_URL}/stations/{uuid}/{WATER_LEVEL_TIMESERIES}"
            f"/measurements.json?start={window}"
        )

    def read(self) -> ProviderResult:
        if not self.gauges:
            return _unavailable(ProviderErrorCode.INVALID_RESPONSE, "no gauges discovered")

        payloads: list[tuple[DiscoveredEntity, object]] = []
        failures: list[ProviderErrorCode] = []
        for gauge in self.gauges:
            try:
                raw = self._fetcher(self.measurement_url(gauge), self._timeout)
                payloads.append((gauge, json.loads(raw)))
            except TimeoutError:
                failures.append(ProviderErrorCode.TIMEOUT)
            except (OSError, UnicodeError, ValueError):
                failures.append(ProviderErrorCode.UPSTREAM)
        received_at = self._clock()
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            return _unavailable(ProviderErrorCode.UNKNOWN, "provider clock is not timezone-aware")

        observations: list[Observation] = []
        invalid = 0
        empty = 0
        stale = False
        for gauge, payload in payloads:
            series, skipped = self._parse(gauge, payload, received_at)
            invalid += skipped
            if not series:
                empty += 1
                continue
            latest = max(item.observed_at for item in series)
            if received_at - latest > timedelta(minutes=self.config.freshness_minutes):
                stale = True
            observations.extend(series)

        failed = len(failures) + empty
        if not observations:
            if not failures:
                code = ProviderErrorCode.INVALID_RESPONSE
            elif len(set(failures)) == 1:
                code = failures[0]
            else:
                code = ProviderErrorCode.UPSTREAM
            return _unavailable(
                code, f"{failed} of {len(self.gauges)} gauges returned no water levels"
            )

        problems = []
        if failed:
            problems.append(f"{failed} of {len(self.gauges)} gauges returned no water levels")
        if invalid:
            problems.append(f"ignored {invalid} invalid value(s)")
        freshness = Freshness.STALE if stale else Freshness.FRESH
        if problems:
            return ProviderResult(
                availability=Availability.DEGRADED,
                freshness=freshness,
                observations=tuple(observations),
                error=ProviderError(
                    code=(
                        ProviderErrorCode.UPSTREAM if failed else ProviderErrorCode.INVALID_RESPONSE
                    ),
                    message="; ".join(problems),
                ),
            )
        return ProviderResult(
            availability=Availability.AVAILABLE,
            freshness=freshness,
            observations=tuple(observations),
        )

    def _parse(
        self, gauge: DiscoveredEntity, payload: object, received_at: datetime
    ) -> tuple[list[Observation], int]:
        if not isinstance(payload, list):
            return [], 1
        result: list[Observation] = []
        invalid = 0
        for item in payload:
            try:
                if not isinstance(item, dict):
                    raise ValueError("measurement is not an object")
                observed_at = datetime.fromisoformat(item["timestamp"])
                raw_value = item["value"]
                if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
                    raise ValueError("missing numeric value")
                value = Decimal(str(raw_value))
                if not value.is_finite():
                    raise ValueError("non-finite value")
                if observed_at.tzinfo is None or observed_at > received_at:
                    raise ValueError("measurement time is not usable")
                result.append(
                    Observation(
                        city_id=self.config.city_id,
                        source_id=self.config.source_id,
                        capability_id="river_level",
                        entity=gauge.location.entity,
                        quantity_id="water_level",
                        value=value,
                        unit="cm",
                        observed_at=observed_at,
                        received_at=received_at,
                    )
                )
            except (InvalidOperation, KeyError, TypeError, ValueError, ValidationError):
                invalid += 1
        result.sort(key=lambda observation: observation.observed_at)
        return result, invalid


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("coordinate is not numeric")
    return float(value)


def _unavailable(code: ProviderErrorCode, message: str) -> ProviderResult:
    return ProviderResult(
        availability=Availability.UNAVAILABLE,
        freshness=Freshness.UNKNOWN,
        error=ProviderError(code=code, message=message),
    )


def fetch_json_bytes(url: str, timeout: float) -> bytes:
    """Fetch a bounded JSON document from the fixed PEGELONLINE API base."""

    if not url.startswith(f"{PEGELONLINE_BASE_URL}/"):
        raise ValueError("refusing to fetch outside the PEGELONLINE API")
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed API base
        payload = cast(bytes, response.read(MAX_RESPONSE_BYTES + 1))
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ValueError("PEGELONLINE response exceeds size limit")
    return payload
