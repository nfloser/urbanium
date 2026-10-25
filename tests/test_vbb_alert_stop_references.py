"""Only explicit GTFS-Realtime Alert stop selectors are exposed as references."""

from datetime import UTC, datetime

from google.transit import gtfs_realtime_pb2

from urbanium.core.provider import Availability, ProviderErrorCode
from urbanium.providers.vbb.gtfs_rt import (
    VbbAlertStopReference,
    VbbGtfsRtConfig,
    VbbGtfsRtProvider,
)

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def _feed(*, timestamp: bool = True, include_stops: bool = True) -> bytes:
    message = gtfs_realtime_pb2.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    if timestamp:
        message.header.timestamp = int(NOW.timestamp()) - 60

    first = message.entity.add()
    first.id = "alert-A"
    first.alert.header_text.translation.add(text="Synthetic alert", language="en")
    first.alert.informed_entity.add().route_id = "M41"
    if include_stops:
        first.alert.informed_entity.add().stop_id = "stop-1"
        qualified = first.alert.informed_entity.add()
        qualified.route_id = "M41"
        qualified.stop_id = "stop-2"
    first.alert.informed_entity.add().trip.trip_id = "trip-only"

    second = message.entity.add()
    second.id = "alert-B"
    second.alert.header_text.translation.add(text="Another synthetic alert", language="en")
    if include_stops:
        second.alert.informed_entity.add().stop_id = "stop-1"
    second.alert.informed_entity.add().stop_id = ""

    update = message.entity.add()
    update.id = "trip-update"
    update.trip_update.trip.trip_id = "not-an-alert"
    return message.SerializeToString()


def _provider(payload: bytes, *, fetcher=None) -> VbbGtfsRtProvider:
    return VbbGtfsRtProvider(
        VbbGtfsRtConfig(
            city_id="berlin",
            source_id="vbb_gtfs_rt",
            endpoint="https://production.gtfsrt.vbb.de",
        ),
        fetcher=fetcher or (lambda _url, _timeout: payload),
        clock=lambda: NOW,
    )


def test_stop_references_keep_alert_identity_selector_order_and_duplicates() -> None:
    snapshot = _provider(_feed()).read_snapshot()

    assert snapshot.result.availability is Availability.AVAILABLE
    assert str(snapshot.result.observations[0].value) == "2"
    assert snapshot.stop_references == (
        VbbAlertStopReference(alert_id="alert-A", selector_index=1, stop_id="stop-1"),
        VbbAlertStopReference(alert_id="alert-A", selector_index=2, stop_id="stop-2"),
        VbbAlertStopReference(alert_id="alert-B", selector_index=0, stop_id="stop-1"),
    )


def test_route_and_trip_only_alert_selectors_do_not_imply_a_stop() -> None:
    snapshot = _provider(_feed(include_stops=False)).read_snapshot()

    assert snapshot.result.availability is Availability.AVAILABLE
    assert str(snapshot.result.observations[0].value) == "2"
    assert snapshot.stop_references == ()


def test_missing_feed_header_time_preserves_degradation_and_explicit_references() -> None:
    snapshot = _provider(_feed(timestamp=False)).read_snapshot()

    assert snapshot.result.availability is Availability.DEGRADED
    assert len(snapshot.stop_references) == 3
    assert snapshot.result.observations[0].quality_code == "receipt_fallback"


def test_unavailable_feeds_never_expose_unvalidated_stop_references() -> None:
    malformed = _provider(b"not-a-protobuf").read_snapshot()
    assert malformed.result.availability is Availability.UNAVAILABLE
    assert malformed.stop_references == ()
    assert malformed.result.error is not None
    assert malformed.result.error.code is ProviderErrorCode.INVALID_RESPONSE

    def timeout(_url: str, _timeout: float) -> bytes:
        raise TimeoutError("offline")

    unavailable = _provider(b"", fetcher=timeout).read_snapshot()
    assert unavailable.result.availability is Availability.UNAVAILABLE
    assert unavailable.stop_references == ()


def test_snapshot_fetches_once_and_existing_read_contract_remains_numeric() -> None:
    calls = 0

    def fetcher(_url: str, _timeout: float) -> bytes:
        nonlocal calls
        calls += 1
        return _feed()

    snapshot = _provider(b"", fetcher=fetcher).read_snapshot()
    assert calls == 1
    assert len(snapshot.stop_references) == 3

    result = _provider(_feed()).read()
    assert result.availability is Availability.AVAILABLE
    assert len(result.observations) == 1
    assert result.observations[0].quantity_id == "active_service_alerts"
