"""Stops named in current VBB alerts, located through the static GTFS inventory.

A stop that an alert selector names is a reference made by the source, not a
statement that the stop is disrupted: the selector may also restrict a route
or trip. Entities and texts here say "named in an alert", never "disrupted".
Static and realtime stop ids are compared exactly; references that the
static inventory does not contain are counted and reported, not dropped.
"""

import json
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError
from yaml import YAMLError, safe_load

from urbanium.core.city import CityDefinition, Identifier
from urbanium.core.discovery import DiscoveredEntity, DiscoveryResult, DiscoveryStatus
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
from urbanium.providers.vbb.gtfs_rt import VbbAlertSnapshot, VbbGtfsRtConfig, VbbGtfsRtProvider
from urbanium.providers.vbb.static_stops import (
    MAX_GTFS_ZIP_BYTES,
    VbbGtfsStaticStopConfig,
    VbbGtfsStaticStopError,
    VbbGtfsStaticStopInventory,
)

FetchBytes = Callable[[str, float], bytes]
Clock = Callable[[], datetime]
QUANTITY = "alert_mentions"


class VbbAlertStopsConfigurationError(ValueError):
    """Raised when the alert-stops binding cannot be loaded."""


class VbbAlertStopsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    city_id: Identifier
    source_id: Identifier  # realtime feed
    static_source_id: Identifier  # static GTFS that locates the stops
    endpoint: HttpUrl
    static_url: HttpUrl
    static_max_age_days: int = Field(default=7, ge=1, le=60)
    freshness_seconds: int = Field(default=300, ge=30, le=3600)


def load_vbb_alert_stops_config(path: Path) -> VbbAlertStopsConfig:
    try:
        raw = safe_load(path.read_text(encoding="utf-8"))
    except (OSError, YAMLError) as exc:
        raise VbbAlertStopsConfigurationError(f"failed to read {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise VbbAlertStopsConfigurationError(f"{path} must contain a mapping")
    try:
        return VbbAlertStopsConfig.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(error["msg"] for error in exc.errors())
        raise VbbAlertStopsConfigurationError(f"invalid config {path}: {details}") from exc


def fetch_gtfs_zip(url: str, timeout: float) -> bytes:
    """Bounded download of the static GTFS archive."""

    request = Request(url, headers={"User-Agent": "Urbanium (https://github.com/nfloser/urbanium)"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL from verified config
        payload = cast(bytes, response.read(MAX_GTFS_ZIP_BYTES + 1))
    if len(payload) > MAX_GTFS_ZIP_BYTES:
        raise ValueError("static GTFS archive exceeds size limit")
    return payload


class StaticGtfsLoader:
    """Load the static archive, reusing a cached copy younger than `max_age`.

    The static feed changes weekly; downloading ~80 MB on every half-hourly
    build would be wasteful. The cache keeps the bytes and the real retrieval
    time, which becomes the evidence time of every stop location.
    """

    def __init__(
        self,
        url: str,
        *,
        cache_dir: Path | None,
        max_age: timedelta,
        fetcher: FetchBytes,
        clock: Clock,
        timeout: float = 120.0,
    ) -> None:
        self.url = url
        self._cache_dir = cache_dir
        self._max_age = max_age
        self._fetcher = fetcher
        self._clock = clock
        self._timeout = timeout

    def load(self) -> tuple[bytes, datetime]:
        now = self._clock()
        if self._cache_dir is not None:
            archive = self._cache_dir / "gtfs-static.zip"
            meta = self._cache_dir / "gtfs-static.json"
            if archive.is_file() and meta.is_file():
                try:
                    info = json.loads(meta.read_text(encoding="utf-8"))
                    retrieved_at = datetime.fromisoformat(info["retrieved_at"])
                    if (
                        info.get("url") == self.url
                        and timedelta(0) <= now - retrieved_at <= self._max_age
                    ):
                        return archive.read_bytes(), retrieved_at
                except (OSError, KeyError, TypeError, ValueError):
                    pass
        payload = self._fetcher(self.url, self._timeout)
        retrieved_at = self._clock()
        if self._cache_dir is not None:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            (self._cache_dir / "gtfs-static.zip").write_bytes(payload)
            (self._cache_dir / "gtfs-static.json").write_text(
                json.dumps({"url": self.url, "retrieved_at": retrieved_at.isoformat()}),
                encoding="utf-8",
            )
        return payload, retrieved_at


class VbbAlertStopDiscovery:
    """Discover stops inside the city's search envelope that current alerts name."""

    def __init__(
        self,
        config: VbbAlertStopsConfig,
        *,
        fetcher: FetchBytes | None = None,
        clock: Clock | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.config = config
        self._clock = clock or (lambda: datetime.now(UTC))
        self._rt = VbbGtfsRtProvider(
            VbbGtfsRtConfig(
                city_id=config.city_id,
                source_id=config.source_id,
                endpoint=config.endpoint,
                freshness_seconds=config.freshness_seconds,
            ),
            fetcher=fetcher,
            clock=self._clock,
        )
        self._static = StaticGtfsLoader(
            str(config.static_url),
            cache_dir=cache_dir,
            max_age=timedelta(days=config.static_max_age_days),
            fetcher=fetcher or fetch_gtfs_zip,
            clock=self._clock,
        )
        self.snapshot: VbbAlertSnapshot | None = None
        self.unresolved = 0
        self.references = 0

    @property
    def city_id(self) -> str:
        return self.config.city_id

    @property
    def source_id(self) -> str:
        return self.config.static_source_id

    def discover(self, city: CityDefinition) -> DiscoveryResult:
        if city.id != self.city_id or city.area is None:
            raise ValueError("alert stop discovery requires its own city with a declared area")
        envelope = city.area.search_envelope

        snapshot = self._rt.read_snapshot()
        self.snapshot = snapshot
        if snapshot.result.availability is Availability.UNAVAILABLE:
            error = snapshot.result.error
            return self._unavailable(
                error.code if error else ProviderErrorCode.UNKNOWN,
                f"realtime feed: {error.message if error else 'unavailable'}",
            )
        try:
            archive, retrieved_at = self._static.load()
            inventory = VbbGtfsStaticStopInventory.from_gtfs_zip(
                VbbGtfsStaticStopConfig(city_id=self.city_id, source_id=self.source_id),
                archive_bytes=archive,
                retrieved_at=retrieved_at,
            )
        except TimeoutError:
            return self._unavailable(ProviderErrorCode.TIMEOUT, "static GTFS request timed out")
        except (OSError, ValueError, VbbGtfsStaticStopError):
            return self._unavailable(
                ProviderErrorCode.UPSTREAM, "static GTFS unavailable or invalid"
            )

        alerts_by_stop: dict[str, set[str]] = defaultdict(set)
        for reference in snapshot.stop_references:
            alerts_by_stop[reference.stop_id].add(reference.alert_id)
        self.references = len(alerts_by_stop)
        self.unresolved = 0

        discovered_at = self._clock()
        entities: list[DiscoveredEntity] = []
        for stop_id, alert_ids in sorted(alerts_by_stop.items()):
            location = inventory.resolve(stop_id)
            if location is None:
                self.unresolved += 1
                continue
            if not envelope.contains(location.point):
                continue
            first_alert = sorted(alert_ids)[0]
            attributes: dict[str, str | int | float | bool] = {
                "stop_id": stop_id,
                "alert_count": len(alert_ids),
                "alert_ids": ", ".join(sorted(alert_ids))[:300],
            }
            header = snapshot.alert_headers.get(first_alert)
            if header:
                attributes["alert_text"] = header
            entities.append(
                DiscoveredEntity(
                    location=location.model_copy(
                        update={"asserted_at": max(location.asserted_at, discovered_at)}
                    ),
                    label=inventory.name(stop_id) or stop_id,
                    attributes=attributes,
                )
            )
        return DiscoveryResult(
            city_id=self.city_id,
            source_id=self.source_id,
            status=DiscoveryStatus.AVAILABLE,
            discovered_at=discovered_at,
            entities=tuple(entities),
        )

    def _unavailable(self, code: ProviderErrorCode, message: str) -> DiscoveryResult:
        return DiscoveryResult(
            city_id=self.city_id,
            source_id=self.source_id,
            status=DiscoveryStatus.UNAVAILABLE,
            discovered_at=self._clock(),
            error=ProviderError(code=code, message=message),
        )


class VbbAlertStopProvider:
    """How often each discovered stop is named in the alerts of the same feed read."""

    def __init__(self, discovery: VbbAlertStopDiscovery, stops: tuple[DiscoveredEntity, ...]):
        self._discovery = discovery
        self.stops = stops

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            city_id=self._discovery.config.city_id,
            source_id=self._discovery.config.source_id,
            capability_id="realtime_transport",
            adapter_version="1.0.0",
        )

    def read(self) -> ProviderResult:
        snapshot = self._discovery.snapshot
        if snapshot is None or snapshot.result.availability is Availability.UNAVAILABLE:
            return ProviderResult(
                availability=Availability.UNAVAILABLE,
                freshness=Freshness.UNKNOWN,
                error=ProviderError(
                    code=ProviderErrorCode.UPSTREAM, message="no realtime feed read"
                ),
            )
        feed = snapshot.result.observations[0]
        config = self._discovery.config
        network = EntityReference(
            city_id=config.city_id, entity_type="transport_network", entity_id="vbb_network"
        )
        observations = [
            # Always present, so an hour without named stops is still a valid read.
            Observation(
                city_id=config.city_id,
                source_id=config.source_id,
                capability_id="realtime_transport",
                entity=network,
                quantity_id="named_stops_in_area",
                value=Decimal(len(self.stops)),
                unit="1",
                observed_at=feed.observed_at,
                received_at=feed.received_at,
            )
        ]
        # Feed-wide counts (alerts, trip updates, vehicle positions) as read.
        observations.extend(snapshot.result.observations)
        observations.extend(
            Observation(
                city_id=config.city_id,
                source_id=config.source_id,
                capability_id="realtime_transport",
                entity=stop.location.entity,
                quantity_id=QUANTITY,
                value=Decimal(int(stop.attributes.get("alert_count", 0))),
                unit="1",
                observed_at=feed.observed_at,
                received_at=feed.received_at,
            )
            for stop in self.stops
        )
        problems = []
        if snapshot.result.error is not None:
            problems.append(snapshot.result.error.message)
        if self._discovery.unresolved:
            problems.append(
                f"{self._discovery.unresolved} of {self._discovery.references} alert stop ids "
                "are not in the static GTFS inventory"
            )
        if problems:
            return ProviderResult(
                availability=Availability.DEGRADED,
                freshness=snapshot.result.freshness,
                observations=tuple(observations),
                error=ProviderError(
                    code=ProviderErrorCode.INVALID_RESPONSE, message="; ".join(problems)
                ),
            )
        return ProviderResult(
            availability=Availability.AVAILABLE,
            freshness=snapshot.result.freshness,
            observations=tuple(observations),
        )
