"""VBB GTFS-Realtime alert-count adapter."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast
from urllib.request import urlopen

from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError
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

MAX_FEED_BYTES = 5_000_000
FetchBytes = Callable[[str, float], bytes]
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class VbbAlertStopReference:
    """A stop ID explicitly named by an Alert selector, not an affected-stop claim."""

    alert_id: str
    selector_index: int
    stop_id: str


@dataclass(frozen=True, slots=True)
class VbbAlertSnapshot:
    """Canonical alert count and provider-specific stop references from one feed."""

    result: ProviderResult
    stop_references: tuple[VbbAlertStopReference, ...]


class VbbGtfsRtConfigurationError(ValueError):
    """Raised when VBB GTFS-Realtime configuration is invalid."""


class VbbGtfsRtConfig(BaseModel):
    """Berlin deployment binding for the public VBB GTFS-Realtime feed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    city_id: Identifier
    source_id: Identifier
    endpoint: HttpUrl
    freshness_seconds: int = Field(default=300, ge=30, le=3600)


def load_vbb_gtfs_rt_config(path: Path) -> VbbGtfsRtConfig:
    """Load the provider-specific city binding."""

    try:
        raw = safe_load(path.read_text(encoding="utf-8"))
    except (OSError, YAMLError) as exc:
        raise VbbGtfsRtConfigurationError(
            f"failed to read VBB GTFS-RT config {path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise VbbGtfsRtConfigurationError(f"VBB GTFS-RT config {path} must contain a mapping")
    try:
        return VbbGtfsRtConfig.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(error["msg"] for error in exc.errors())
        raise VbbGtfsRtConfigurationError(f"invalid VBB GTFS-RT config {path}: {details}") from exc


class VbbGtfsRtProvider:
    """Normalize one VBB GTFS-RT snapshot into an alert-count observation."""

    def __init__(
        self,
        config: VbbGtfsRtConfig,
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
            capability_id="realtime_transport",
            adapter_version="1.0.0",
        )

    @property
    def url(self) -> str:
        return str(self.config.endpoint).rstrip("/")

    def read(self) -> ProviderResult:
        """Preserve the canonical count-only provider contract."""

        return self.read_snapshot().result

    def read_snapshot(self) -> VbbAlertSnapshot:
        """Read one feed, retaining only explicitly named Alert stop references."""

        try:
            payload = self._fetcher(self.url, self._timeout)
        except TimeoutError:
            return VbbAlertSnapshot(
                result=_unavailable(ProviderErrorCode.TIMEOUT, "VBB GTFS-RT request timed out"),
                stop_references=(),
            )
        except OSError:
            return VbbAlertSnapshot(
                result=_unavailable(ProviderErrorCode.UPSTREAM, "VBB GTFS-RT request failed"),
                stop_references=(),
            )
        except ValueError:
            return VbbAlertSnapshot(
                result=_unavailable(
                    ProviderErrorCode.INVALID_RESPONSE,
                    "VBB GTFS-RT feed exceeds size limit",
                ),
                stop_references=(),
            )

        # A feed generated while downloading may be newer than request start.
        received_at = self._clock()
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            return VbbAlertSnapshot(
                result=_unavailable(
                    ProviderErrorCode.UNKNOWN,
                    "provider clock is not timezone-aware",
                ),
                stop_references=(),
            )

        if len(payload) > MAX_FEED_BYTES:
            return VbbAlertSnapshot(
                result=_unavailable(
                    ProviderErrorCode.INVALID_RESPONSE,
                    "VBB GTFS-RT feed exceeds size limit",
                ),
                stop_references=(),
            )

        try:
            message = gtfs_realtime_pb2.FeedMessage()
            message.ParseFromString(payload)
            if not message.IsInitialized():
                raise ValueError("GTFS-Realtime feed is missing required fields")
            alert_count = sum(1 for entity in message.entity if entity.HasField("alert"))
            observed_at, freshness, quality_code, degraded_error = self._snapshot_time(
                message,
                received_at,
            )
            observation = Observation(
                city_id=self.config.city_id,
                source_id=self.config.source_id,
                capability_id="realtime_transport",
                entity=EntityReference(
                    city_id=self.config.city_id,
                    entity_type="transport_network",
                    entity_id="vbb_network",
                ),
                quantity_id="active_service_alerts",
                value=Decimal(alert_count),
                unit="1",
                observed_at=observed_at,
                received_at=received_at,
                quality_scheme="gtfs_rt_snapshot_time",
                quality_code=quality_code,
            )
            stop_references = _alert_stop_references(message)
        except (DecodeError, OverflowError, OSError, ValueError):
            return VbbAlertSnapshot(
                result=_unavailable(
                    ProviderErrorCode.INVALID_RESPONSE,
                    "invalid VBB GTFS-Realtime feed",
                ),
                stop_references=(),
            )

        if degraded_error is not None:
            result = ProviderResult(
                availability=Availability.DEGRADED,
                freshness=freshness,
                observations=(observation,),
                error=degraded_error,
            )
        else:
            result = ProviderResult(
                availability=Availability.AVAILABLE,
                freshness=freshness,
                observations=(observation,),
            )
        return VbbAlertSnapshot(result=result, stop_references=stop_references)

    def _snapshot_time(
        self,
        message: Any,
        received_at: datetime,
    ) -> tuple[datetime, Freshness, str, ProviderError | None]:
        header = message.header
        if not header.HasField("timestamp"):
            return (
                received_at,
                Freshness.UNKNOWN,
                "receipt_fallback",
                ProviderError(
                    code=ProviderErrorCode.INVALID_RESPONSE,
                    message="GTFS-Realtime header timestamp missing; receipt time used",
                ),
            )

        timestamp = cast(int, header.timestamp)
        observed_at = datetime.fromtimestamp(timestamp, UTC)
        if observed_at > received_at.astimezone(UTC):
            raise ValueError("GTFS-Realtime timestamp is in the future")

        age = received_at.astimezone(UTC) - observed_at
        freshness = (
            Freshness.FRESH
            if age <= timedelta(seconds=self.config.freshness_seconds)
            else Freshness.STALE
        )
        return observed_at, freshness, "feed_header", None



def _alert_stop_references(
    message: gtfs_realtime_pb2.FeedMessage,
) -> tuple[VbbAlertStopReference, ...]:
    # A selector can also constrain a route/trip. Its stop ID is a source
    # reference only, not proof that the entire stop is affected.
    return tuple(
        VbbAlertStopReference(
            alert_id=entity.id,
            selector_index=index,
            stop_id=selector.stop_id,
        )
        for entity in message.entity
        if entity.HasField("alert")
        for index, selector in enumerate(entity.alert.informed_entity)
        if selector.HasField("stop_id") and selector.stop_id
    )


def _unavailable(code: ProviderErrorCode, message: str) -> ProviderResult:
    return ProviderResult(
        availability=Availability.UNAVAILABLE,
        freshness=Freshness.UNKNOWN,
        error=ProviderError(code=code, message=message),
    )


def _fetch_bytes(url: str, timeout: float) -> bytes:
    with urlopen(url, timeout=timeout) as response:
        payload = cast(bytes, response.read(MAX_FEED_BYTES + 1))
    if len(payload) > MAX_FEED_BYTES:
        raise ValueError("VBB GTFS-RT feed exceeds size limit")
    return payload


def _utc_now() -> datetime:
    return datetime.now(UTC)
