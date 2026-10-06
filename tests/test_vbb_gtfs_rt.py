from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from google.transit import gtfs_realtime_pb2
from tests.contracts.provider import ProviderContractCases, assert_provider_contract
from urbanium.core.provider import Availability, Freshness, ProviderErrorCode
from urbanium.providers.vbb.gtfs_rt import (
    VbbGtfsRtConfig,
    VbbGtfsRtProvider,
    load_vbb_gtfs_rt_config,
)
from urbanium.registry import load_city_definition

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 6, 9, 15, tzinfo=UTC)
FEED_TIME = datetime(2026, 10, 6, 9, 14, tzinfo=UTC)


def feed(*, alerts: int = 2, timestamp: int | None = int(FEED_TIME.timestamp())) -> bytes:
    message = gtfs_realtime_pb2.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    if timestamp is not None:
        message.header.timestamp = timestamp

    for index in range(alerts):
        entity = message.entity.add()
        entity.id = f"alert-{index + 1}"
        entity.alert.header_text.translation.add(text=f"Service alert {index + 1}", language="en")

    trip_update = message.entity.add()
    trip_update.id = "trip-update-1"
    trip_update.trip_update.trip.trip_id = "trip-1"

    return message.SerializeToString()


def fetch(payload: bytes) -> Callable[[str, float], bytes]:
    def fixture_fetcher(url: str, timeout: float) -> bytes:
        assert url == "https://production.gtfsrt.vbb.de"
        assert timeout == 10.0
        return payload

    return fixture_fetcher


def provider(
    payload: bytes | None = None,
    *,
    now: datetime = NOW,
) -> VbbGtfsRtProvider:
    return VbbGtfsRtProvider(
        VbbGtfsRtConfig(
            city_id="berlin",
            source_id="vbb_gtfs_rt",
            endpoint="https://production.gtfsrt.vbb.de",
            freshness_seconds=300,
        ),
        fetcher=fetch(payload if payload is not None else feed()),
        clock=lambda: now,
    )


def test_reference_configuration_binds_the_verified_berlin_source() -> None:
    config = load_vbb_gtfs_rt_config(
        ROOT / "cities" / "berlin" / "providers" / "vbb_gtfs_rt.yaml"
    )

    assert config.city_id == "berlin"
    assert config.source_id == "vbb_gtfs_rt"
    assert str(config.endpoint).rstrip("/") == "https://production.gtfsrt.vbb.de"


def test_alert_entities_are_normalized_as_a_numeric_mobility_observation() -> None:
    result = provider(feed(alerts=3)).read()

    assert result.availability is Availability.AVAILABLE
    assert result.freshness is Freshness.FRESH
    assert len(result.observations) == 1

    observation = result.observations[0]
    assert observation.city_id == "berlin"
    assert observation.source_id == "vbb_gtfs_rt"
    assert observation.capability_id == "realtime_transport"
    assert observation.entity.canonical_id == "berlin:transport_network:vbb_network"
    assert observation.quantity_id == "active_service_alerts"
    assert str(observation.value) == "3"
    assert observation.unit == "1"
    assert observation.observed_at == FEED_TIME
    assert observation.received_at == NOW
    assert observation.quality_scheme == "gtfs_rt_snapshot_time"
    assert observation.quality_code == "feed_header"


def test_zero_alerts_remains_an_available_observation() -> None:
    result = provider(feed(alerts=0)).read()

    assert result.availability is Availability.AVAILABLE
    assert str(result.observations[0].value) == "0"


def test_missing_feed_timestamp_degrades_but_keeps_the_observed_alert_count() -> None:
    result = provider(feed(alerts=1, timestamp=None)).read()

    assert result.availability is Availability.DEGRADED
    assert result.freshness is Freshness.UNKNOWN
    assert str(result.observations[0].value) == "1"
    assert result.observations[0].observed_at == NOW
    assert result.observations[0].quality_code == "receipt_fallback"
    assert result.error is not None
    assert result.error.code is ProviderErrorCode.INVALID_RESPONSE


def test_old_feed_timestamp_is_stale_without_becoming_unavailable() -> None:
    result = provider(
        feed(alerts=1, timestamp=int(datetime(2026, 10, 6, 8, 0, tzinfo=UTC).timestamp()))
    ).read()

    assert result.availability is Availability.AVAILABLE
    assert result.freshness is Freshness.STALE


def test_timeout_malformed_and_oversized_feeds_are_explicitly_unavailable() -> None:
    def timeout(_url: str, _timeout: float) -> bytes:
        raise TimeoutError("fixture timeout")

    timeout_provider = VbbGtfsRtProvider(
        provider().config,
        fetcher=timeout,
        clock=lambda: NOW,
    )
    timeout_result = timeout_provider.read()
    assert timeout_result.availability is Availability.UNAVAILABLE
    assert timeout_result.error is not None
    assert timeout_result.error.code is ProviderErrorCode.TIMEOUT

    malformed = provider(b"not-a-protobuf").read()
    assert malformed.availability is Availability.UNAVAILABLE
    assert malformed.error is not None
    assert malformed.error.code is ProviderErrorCode.INVALID_RESPONSE

    oversized = provider(b"x" * 5_000_001).read()
    assert oversized.availability is Availability.UNAVAILABLE
    assert oversized.error is not None
    assert oversized.error.code is ProviderErrorCode.INVALID_RESPONSE


def test_future_feed_timestamp_is_rejected_instead_of_rewriting_provenance() -> None:
    future = int(datetime(2026, 10, 6, 9, 16, tzinfo=UTC).timestamp())

    result = provider(feed(timestamp=future)).read()

    assert result.availability is Availability.UNAVAILABLE
    assert result.error is not None
    assert result.error.code is ProviderErrorCode.INVALID_RESPONSE


def test_vbb_adapter_passes_the_shared_provider_contract() -> None:
    city = load_city_definition(ROOT / "cities" / "berlin" / "city.yaml")

    def timeout(_url: str, _timeout: float) -> bytes:
        raise TimeoutError("fixture timeout")

    assert_provider_contract(
        ProviderContractCases(
            city=city,
            available=provider(feed(alerts=2)),
            degraded=provider(feed(alerts=1, timestamp=None)),
            unavailable=VbbGtfsRtProvider(
                provider().config,
                fetcher=timeout,
                clock=lambda: NOW,
            ),
        )
    )
