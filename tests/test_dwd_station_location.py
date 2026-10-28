"""Station inventory coordinates remain provider metadata, not weather coverage."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from urbanium.core.entity import StateCategory
from urbanium.providers.dwd.air_temperature import (
    DwdAirTemperatureConfig,
    load_dwd_air_temperature_config,
)
from urbanium.providers.dwd.station_location import (
    DWD_STATION_LIST_URL,
    DwdCdcStationLocationProvider,
    DwdStationMetadataError,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 25, 11, tzinfo=UTC)
HEADER = (
    "Stations_id von_datum bis_datum Stationshoehe geoBreite geoLaenge "
    "Stationsname Bundesland\n"
    "----------- --------- --------- ------------- --------- --------- "
    "----------------------------------------- ----------\n"
)


def station_row(
    station_id: str = "00433",
    latitude: str = "52.4675",
    longitude: str = "13.4021",
) -> str:
    # Coordinates in fixtures are illustrative, not verified station metadata.
    return f"{station_id} 19480101 20261025 48 {latitude} {longitude} Example Station Berlin\n"


def subject(
    payload: bytes,
    *,
    city: str = "berlin",
    clock: datetime = NOW,
) -> DwdCdcStationLocationProvider:
    config = load_dwd_air_temperature_config(
        ROOT / "cities" / city / "providers" / "dwd_air_temperature.yaml"
    )

    def fetcher(url: str, timeout: float) -> bytes:
        assert url == DWD_STATION_LIST_URL
        assert timeout == 10.0
        return payload

    return DwdCdcStationLocationProvider(config, fetcher=fetcher, clock=lambda: clock)


def test_station_list_yields_sourced_reference_point() -> None:
    result = subject((HEADER + station_row()).encode("latin-1")).read()

    assert result is not None
    assert result.entity.canonical_id == "berlin:weather_station:dwd_station_00433"
    assert result.point.latitude == 52.4675
    assert result.point.longitude == 13.4021
    assert result.state_category is StateCategory.REFERENCE
    assert result.asserted_at == NOW
    assert result.evidence[0].source_id == "dwd_open_data"
    assert result.evidence[0].retrieved_at == NOW
    assert result.evidence[0].record_id.startswith("zehn_min_tu_Beschreibung_Stationen.txt:00433:")
    assert len(result.evidence[0].record_id.split(":")[-1]) == 64


def test_berlin_and_mainz_use_same_inventory_parser_without_shared_identity() -> None:
    payload = (HEADER + station_row("00433") + station_row("03137")).encode("latin-1")
    berlin = subject(payload).read()
    mainz = subject(payload, city="mainz").read()

    assert berlin is not None and mainz is not None
    assert berlin.entity.city_id == "berlin"
    assert mainz.entity.canonical_id == "mainz:weather_station:dwd_station_03137"
    assert berlin.point == mainz.point  # Synthetic shared coordinates do not imply coverage.


@pytest.mark.parametrize("payload", [HEADER.splitlines()[0] + "\n", HEADER, HEADER + "\n  \n"])
def test_empty_inventory_is_not_mistaken_for_missing_station(payload: str) -> None:
    with pytest.raises(DwdStationMetadataError, match="no station records"):
        subject(payload.encode("latin-1")).read()


def test_station_not_in_inventory_remains_missing() -> None:
    assert subject((HEADER + station_row("03137")).encode("latin-1")).read() is None


@pytest.mark.parametrize(
    "rows",
    [
        station_row() + station_row(),
        "00433 broken\n",
        station_row(latitude="91"),
        station_row(longitude="nan"),
        station_row(latitude="5_2"),
        station_row(longitude="1_3.4"),
        "00433 20261231 20260101 48 52.0 13.0 Example Berlin\n",
    ],
)
def test_invalid_or_ambiguous_target_station_is_rejected(rows: str) -> None:
    with pytest.raises(DwdStationMetadataError):
        subject((HEADER + rows).encode("latin-1")).read()


def test_ascii_signed_and_exponent_coordinates_remain_valid() -> None:
    result = subject(
        (HEADER + station_row(latitude="+52.4675", longitude="1.34021e1")).encode("latin-1")
    ).read()

    assert result is not None
    assert result.point.latitude == 52.4675
    assert result.point.longitude == 13.4021


def test_invalid_inventory_header_is_not_mistaken_for_missing_station() -> None:
    with pytest.raises(DwdStationMetadataError, match="header"):
        subject(b"unrecognized source file\n").read()


@pytest.mark.parametrize(
    "header",
    [
        "prefix_stations_id von_datum bis_datum Stationshoehe "
        "geoBreite geoLaenge Stationsname Bundesland\n",
        "Stations_id von_datum bis_datum geoBreite Stationshoehe "
        "geoLaenge Stationsname Bundesland\n",
        "Stations_id von_datum bis_datum Stationshoehe geoLaenge "
        "geoBreite Stationsname Bundesland\n",
    ],
)
def test_station_header_must_match_positional_fields(header: str) -> None:
    with pytest.raises(DwdStationMetadataError, match="header"):
        subject((header + station_row()).encode("latin-1")).read()


def test_oversized_inventory_is_rejected() -> None:
    with pytest.raises(DwdStationMetadataError, match="size"):
        subject(b"x" * 1_000_001).read()


def test_network_failure_is_not_mistaken_for_missing_station() -> None:
    def failing_fetcher(_url: str, _timeout: float) -> bytes:
        raise TimeoutError("source unreachable")

    config = DwdAirTemperatureConfig(
        city_id="berlin",
        source_id="dwd_open_data",
        station_id="00433",
        station_name="Berlin-Tempelhof",
    )
    provider = DwdCdcStationLocationProvider(config, fetcher=failing_fetcher, clock=lambda: NOW)
    with pytest.raises(DwdStationMetadataError, match="request"):
        provider.read()


def test_clock_is_sampled_after_download() -> None:
    fetched = False

    def fetcher(_url: str, _timeout: float) -> bytes:
        nonlocal fetched
        fetched = True
        return (HEADER + station_row()).encode("latin-1")

    def clock() -> datetime:
        assert fetched
        return NOW

    config = DwdAirTemperatureConfig(
        city_id="berlin",
        source_id="dwd_open_data",
        station_id="00433",
        station_name="Berlin-Tempelhof",
    )
    result = DwdCdcStationLocationProvider(config, fetcher=fetcher, clock=clock).read()
    assert result is not None and result.asserted_at == NOW


def test_naive_clock_is_rejected() -> None:
    with pytest.raises(DwdStationMetadataError, match="timezone-aware"):
        subject((HEADER + station_row()).encode("latin-1"), clock=NOW.replace(tzinfo=None)).read()


def test_evidence_digest_changes_when_inventory_changes() -> None:
    first = subject((HEADER + station_row()).encode("latin-1")).read()
    second = subject((HEADER + station_row() + station_row("03137")).encode("latin-1")).read()
    assert first is not None and second is not None
    assert first.evidence[0].record_id != second.evidence[0].record_id
