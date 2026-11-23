"""A city's discovered DWD stations are read together as one weather network."""

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from tests.contracts.provider import ProviderContractCases, assert_provider_contract
from urbanium.core.discovery import DiscoveredEntity
from urbanium.core.entity import EntityReference, EvidenceReference, StateCategory
from urbanium.core.provider import Availability, Freshness
from urbanium.core.spatial import EntityPointLocation, Wgs84Point
from urbanium.providers.dwd.air_temperature import (
    DwdAirTemperatureConfig,
    DwdCdcAirTemperatureProvider,
)
from urbanium.providers.dwd.discovery import DwdAreaConfig
from urbanium.providers.dwd.network import DwdAirTemperatureNetworkProvider
from urbanium.registry import load_city_definition

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "dwd"
NOW = datetime(2026, 9, 29, 12, 30, tzinfo=UTC)
CONFIG = DwdAreaConfig(city_id="berlin", source_id="dwd_open_data", freshness_minutes=90)
BERLIN = load_city_definition(ROOT / "cities" / "berlin" / "city.yaml")


def archive(fixture: str, station_id: str) -> bytes:
    payload = (FIXTURES / fixture).read_bytes().replace(b"00433", station_id.encode("ascii"))
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as target:
        target.writestr(f"produkt_zehn_now_tu_20260929_20260929_{station_id}.txt", payload)
    return buffer.getvalue()


def station(station_id: str, *, city_id: str = "berlin", source_id: str = "dwd_open_data"):  # type: ignore[no-untyped-def]
    return DiscoveredEntity(
        location=EntityPointLocation(
            entity=EntityReference(
                city_id=city_id,
                entity_type="weather_station",
                entity_id=f"dwd_station_{station_id}",
            ),
            point=Wgs84Point(latitude=52.5, longitude=13.4),
            state_category=StateCategory.REFERENCE,
            asserted_at=NOW,
            evidence=(
                EvidenceReference(
                    city_id=city_id,
                    source_id=source_id,
                    record_id=f"inventory:{station_id}",
                    retrieved_at=NOW,
                ),
            ),
        ),
        label=f"Station {station_id}",
        attributes={"station_id": station_id},
    )


def network(responses: dict[str, bytes | Exception], *, now: datetime = NOW):  # type: ignore[no-untyped-def]
    def fetch(url: str, timeout: float) -> bytes:
        for station_id, response in responses.items():
            if url.endswith(f"/10minutenwerte_TU_{station_id}_now.zip"):
                if isinstance(response, Exception):
                    raise response
                return response
        raise AssertionError(url)

    return DwdAirTemperatureNetworkProvider(
        CONFIG,
        tuple(station(station_id) for station_id in responses),
        fetcher=fetch,
        clock=lambda: now,
    )


def test_single_station_series_keeps_every_valid_row_in_time_order() -> None:
    provider = DwdCdcAirTemperatureProvider(
        DwdAirTemperatureConfig(
            city_id="berlin",
            source_id="dwd_open_data",
            station_id="00433",
            station_name="Berlin-Tempelhof",
        ),
        fetcher=lambda url, timeout: archive("air_temperature_now.csv", "00433"),
        clock=lambda: NOW,
    )

    latest = provider.read()
    series = provider.read_series()

    assert len(latest.observations) == 1
    assert [str(item.value) for item in series.observations] == ["16.8", "17.1"]
    assert series.observations[-1] == latest.observations[0]
    assert series.availability is latest.availability
    assert series.freshness is latest.freshness


def test_network_merges_every_station_series_under_one_binding() -> None:
    result = network(
        {
            "00433": archive("air_temperature_now.csv", "00433"),
            "00403": archive("air_temperature_now.csv", "00403"),
        }
    ).read()

    assert result.availability is Availability.AVAILABLE
    assert result.freshness is Freshness.FRESH
    assert {item.entity.entity_id for item in result.observations} == {
        "dwd_station_00433",
        "dwd_station_00403",
    }
    assert len(result.observations) == 4


def test_missing_stations_degrade_the_network_but_keep_the_rest() -> None:
    result = network(
        {
            "00433": archive("air_temperature_now.csv", "00433"),
            "00403": OSError("404"),
        }
    ).read()

    assert result.availability is Availability.DEGRADED
    assert result.error is not None
    assert "1 of 2 stations" in result.error.message
    assert {item.entity.entity_id for item in result.observations} == {"dwd_station_00433"}


def test_partial_rows_are_reported_with_station_context() -> None:
    result = network({"00433": archive("air_temperature_partial.csv", "00433")}).read()

    assert result.availability is Availability.DEGRADED
    assert result.error is not None and "invalid DWD row" in result.error.message


def test_network_without_any_usable_station_is_unavailable() -> None:
    assert network({"00433": TimeoutError()}).read().availability is Availability.UNAVAILABLE
    empty = DwdAirTemperatureNetworkProvider(CONFIG, (), fetcher=None, clock=lambda: NOW).read()
    assert empty.availability is Availability.UNAVAILABLE
    assert empty.error is not None and "no stations" in empty.error.message


def test_one_stale_station_makes_the_network_stale() -> None:
    late = datetime(2026, 9, 29, 14, 30, tzinfo=UTC)
    assert network(
        {"00433": archive("air_temperature_now.csv", "00433")}, now=late
    ).read().freshness is (Freshness.STALE)


def test_stations_from_other_bindings_are_rejected() -> None:
    with pytest.raises(ValueError, match="station"):
        DwdAirTemperatureNetworkProvider(CONFIG, (station("00433", city_id="mainz"),))
    with pytest.raises(ValueError, match="station"):
        DwdAirTemperatureNetworkProvider(CONFIG, (station("00433", source_id="other"),))


def test_network_passes_shared_provider_contract() -> None:
    assert_provider_contract(
        ProviderContractCases(
            city=BERLIN,
            available=network({"00433": archive("air_temperature_now.csv", "00433")}),
            degraded=network(
                {"00433": archive("air_temperature_now.csv", "00433"), "00403": OSError("404")}
            ),
            unavailable=network({"00433": TimeoutError()}),
        )
    )
