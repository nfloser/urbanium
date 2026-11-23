"""PEGELONLINE gauges are discovered by area and read as sourced water-level series."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.contracts.provider import ProviderContractCases, assert_provider_contract
from urbanium.core.discovery import DiscoveredEntity, DiscoveryStatus, validate_discovery_result
from urbanium.core.provider import Availability, Freshness, ProviderErrorCode
from urbanium.providers.pegelonline.water_level import (
    PEGELONLINE_BASE_URL,
    PegelonlineConfig,
    PegelonlineGaugeDiscovery,
    PegelonlineWaterLevelProvider,
    load_pegelonline_config,
)
from urbanium.registry import load_city_definition

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "pegelonline"
NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)  # 10:00 local, 15 min after fixtures
BERLIN = load_city_definition(ROOT / "cities" / "berlin" / "city.yaml")
CONFIG = load_pegelonline_config(ROOT / "cities" / "berlin" / "providers" / "pegelonline.yaml")
MUEHLENDAMM = "09e15cf6-f155-4b76-b92f-6c260839121c"
SPANDAU = "6a5c4b3e-2f1d-4c0b-9a8e-7d6c5b4a3f2e"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fetcher_for(responses: dict[str, bytes | Exception]):  # type: ignore[no-untyped-def]
    requested: list[str] = []

    def fetch(url: str, timeout: float) -> bytes:
        requested.append(url)
        for marker, response in responses.items():
            if marker in url:
                if isinstance(response, Exception):
                    raise response
                return response
        raise AssertionError(f"unexpected url {url}")

    return fetch, requested


def discovered(config: PegelonlineConfig = CONFIG) -> tuple[DiscoveredEntity, ...]:
    fetch, _ = fetcher_for({"stations.json": fixture("stations.json")})
    result = PegelonlineGaugeDiscovery(config, fetcher=fetch, clock=lambda: NOW).discover(BERLIN)
    return result.entities


def test_discovery_queries_around_the_area_and_keeps_water_level_gauges_inside_it() -> None:
    fetch, requested = fetcher_for({"stations.json": fixture("stations.json")})

    result = PegelonlineGaugeDiscovery(CONFIG, fetcher=fetch, clock=lambda: NOW).discover(BERLIN)

    validate_discovery_result(BERLIN, result)
    query = parse_qs(urlsplit(requested[0]).query)
    assert requested[0].startswith(f"{PEGELONLINE_BASE_URL}/stations.json?")
    assert BERLIN.area is not None
    assert float(query["latitude"][0]) == pytest.approx(BERLIN.area.center.latitude)
    assert float(query["radius"][0]) >= BERLIN.area.covering_radius_km
    assert query["includeTimeseries"] == ["true"]

    assert result.status is DiscoveryStatus.AVAILABLE
    assert [item.label for item in result.entities] == ["BERLIN-MÜHLENDAMM UP", "SPANDAU UP"]
    gauge = result.entities[0]
    assert gauge.location.entity.canonical_id == "berlin:river_gauge:pegelonline_5803200"
    assert gauge.attributes == {
        "uuid": MUEHLENDAMM,
        "number": "5803200",
        "water": "SPREE-ODER-WASSERSTRASSE",
        "agency": "SPREE-HAVEL",
        "river_km": 17.6,
        "gauge_zero_m": 30.0,
    }
    assert gauge.location.evidence[0].record_id.startswith(f"stations.json:{MUEHLENDAMM}:")


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (TimeoutError(), ProviderErrorCode.TIMEOUT),
        (OSError("down"), ProviderErrorCode.UPSTREAM),
        (b"{}", ProviderErrorCode.INVALID_RESPONSE),
        (b"not json", ProviderErrorCode.INVALID_RESPONSE),
    ],
)
def test_unreadable_station_list_makes_discovery_unavailable(
    response: bytes | Exception, code: ProviderErrorCode
) -> None:
    fetch, _ = fetcher_for({"stations.json": response})

    result = PegelonlineGaugeDiscovery(CONFIG, fetcher=fetch, clock=lambda: NOW).discover(BERLIN)

    assert result.status is DiscoveryStatus.UNAVAILABLE
    assert result.error is not None and result.error.code is code


def provider(
    responses: dict[str, bytes | Exception],
    *,
    clock: datetime = NOW,
) -> PegelonlineWaterLevelProvider:
    fetch, _ = fetcher_for(responses)
    return PegelonlineWaterLevelProvider(CONFIG, discovered(), fetcher=fetch, clock=lambda: clock)


def test_measurement_history_becomes_sourced_observations_for_every_gauge() -> None:
    result = provider(
        {
            MUEHLENDAMM: fixture("measurements_muehlendamm.json"),
            SPANDAU: fixture("measurements_spandau.json"),
        }
    ).read()

    assert result.availability is Availability.DEGRADED  # one null value was skipped
    assert result.error is not None and "1 invalid" in result.error.message
    assert result.freshness is Freshness.FRESH
    by_gauge: dict[str, list[Decimal]] = {}
    for item in result.observations:
        by_gauge.setdefault(item.entity.entity_id, []).append(item.value)
        assert item.quantity_id == "water_level"
        assert item.unit == "cm"
        assert item.capability_id == "river_level"
        assert item.received_at == NOW
        assert item.observed_at.tzinfo is not None
    assert by_gauge == {
        "pegelonline_5803200": [Decimal("331"), Decimal("334"), Decimal("336"), Decimal("337")],
        "pegelonline_5865000": [Decimal("229"), Decimal("224")],
    }


def test_measurement_request_uses_the_gauge_uuid_and_history_window() -> None:
    fetch, requested = fetcher_for(
        {
            MUEHLENDAMM: fixture("measurements_muehlendamm.json"),
            SPANDAU: fixture("measurements_spandau.json"),
        }
    )
    PegelonlineWaterLevelProvider(CONFIG, discovered(), fetcher=fetch, clock=lambda: NOW).read()

    assert requested[0] == (
        f"{PEGELONLINE_BASE_URL}/stations/{MUEHLENDAMM}/W/measurements.json?start=P1D"
    )


def test_one_failing_gauge_degrades_and_all_failing_gauges_make_the_read_unavailable() -> None:
    degraded = provider(
        {MUEHLENDAMM: fixture("measurements_muehlendamm.json"), SPANDAU: OSError("down")}
    ).read()
    assert degraded.availability is Availability.DEGRADED
    assert degraded.error is not None and "1 of 2 gauges" in degraded.error.message

    unavailable = provider({MUEHLENDAMM: TimeoutError(), SPANDAU: OSError("down")}).read()
    assert unavailable.availability is Availability.UNAVAILABLE
    assert unavailable.observations == ()


def test_old_latest_values_are_stale_and_future_values_are_rejected() -> None:
    late = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    stale = provider(
        {MUEHLENDAMM: fixture("measurements_muehlendamm.json"), SPANDAU: b"[]"},
        clock=late,
    ).read()
    assert stale.freshness is Freshness.STALE

    early = datetime(2026, 11, 23, 8, 40, tzinfo=UTC)  # 09:40 local: 09:45 lies in the future
    result = provider(
        {MUEHLENDAMM: fixture("measurements_muehlendamm.json"), SPANDAU: b"[]"},
        clock=early,
    ).read()
    assert all(item.observed_at <= early for item in result.observations)
    assert result.availability is Availability.DEGRADED


def test_no_gauges_means_no_measurement_read_is_possible() -> None:
    result = PegelonlineWaterLevelProvider(CONFIG, (), fetcher=None, clock=lambda: NOW).read()

    assert result.availability is Availability.UNAVAILABLE
    assert result.error is not None and "no gauges" in result.error.message


def test_shared_provider_contract() -> None:
    available = provider({MUEHLENDAMM: fixture("measurements_muehlendamm.json"), SPANDAU: b"[]"})
    # Gauge with an empty series counts as unavailable for this read.
    assert available.read().availability is Availability.DEGRADED
    clean_gauges = discovered()[:1]
    fetch_ok, _ = fetcher_for({MUEHLENDAMM: fixture("measurements_muehlendamm.json")})
    fetch_bad, _ = fetcher_for({MUEHLENDAMM: OSError("down")})
    assert_provider_contract(
        ProviderContractCases(
            city=BERLIN,
            available=PegelonlineWaterLevelProvider(
                CONFIG, clean_gauges, fetcher=fetch_ok, clock=lambda: NOW
            ),
            degraded=available,
            unavailable=PegelonlineWaterLevelProvider(
                CONFIG, clean_gauges, fetcher=fetch_bad, clock=lambda: NOW
            ),
        )
    )


def test_gauges_from_another_city_or_source_are_rejected() -> None:
    other = CONFIG.model_copy(update={"city_id": "mainz"})
    with pytest.raises(ValueError, match="gauge"):
        PegelonlineWaterLevelProvider(other, discovered(), fetcher=None, clock=lambda: NOW)


def test_shipped_configs_bind_verified_sources() -> None:
    paths = sorted(ROOT.glob("cities/*/providers/pegelonline.yaml"))
    assert {path.parents[1].name for path in paths} >= {"berlin", "mainz"}
    for path in paths:
        config = load_pegelonline_config(path)
        city = load_city_definition(path.parents[1] / "city.yaml")
        source = next(item for item in city.sources if item.id == config.source_id)
        assert source.license.redistribution.value == "permitted"
        assert "river_level" in source.capabilities
