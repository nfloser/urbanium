"""DWD stations are discovered from the published inventory inside the city area."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from urbanium.core.discovery import DiscoveryStatus, validate_discovery_result
from urbanium.core.provider import ProviderErrorCode
from urbanium.providers.dwd.discovery import (
    DWD_NOW_STATION_LIST_URL,
    DwdAreaConfig,
    DwdStationDiscovery,
    load_dwd_area_config,
)
from urbanium.registry import load_city_definition

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 23, 9, tzinfo=UTC)
HEADER = (
    "Stations_id von_datum bis_datum Stationshoehe geoBreite geoLaenge "
    "Stationsname Bundesland Abgabe\n"
    "----------- --------- --------- ------------- --------- --------- "
    "----------------------------------------- ---------- ------\n"
)
BERLIN = load_city_definition(ROOT / "cities" / "berlin" / "city.yaml")


def row(
    station_id: str,
    latitude: float,
    longitude: float,
    *,
    until: str = "20261122",
    name: str = "Example Station",
    state: str = "Berlin",
) -> str:
    # Coordinates in fixtures are illustrative, not verified station metadata.
    return f"{station_id} 19900101 {until} 48 {latitude:.4f} {longitude:.4f} {name} {state} Frei\n"


def discovery(
    payload: bytes | Exception,
    *,
    config: DwdAreaConfig | None = None,
) -> DwdStationDiscovery:
    def fetcher(url: str, timeout: float) -> bytes:
        assert url == DWD_NOW_STATION_LIST_URL
        if isinstance(payload, Exception):
            raise payload
        return payload

    return DwdStationDiscovery(
        config
        or load_dwd_area_config(ROOT / "cities/berlin/providers/dwd_air_temperature_area.yaml"),
        fetcher=fetcher,
        clock=lambda: NOW,
    )


def test_only_recently_active_stations_inside_the_area_are_discovered() -> None:
    payload = (
        HEADER
        + row("00433", 52.4675, 13.4021, name="Berlin-Tempelhof")
        + row("00403", 52.4537, 13.3017, name="Berlin-Dahlem (FU)")
        + row("00399", 52.5000, 13.5000, until="19991231", name="Closed Station")
        + row("03137", 49.9655, 8.2135, name="Mainz-Lerchenberg (ZDF)", state="Rheinland-Pfalz")
    ).encode("latin-1")

    result = discovery(payload).discover(BERLIN)

    validate_discovery_result(BERLIN, result)
    assert result.status is DiscoveryStatus.AVAILABLE
    ids = [item.location.entity.entity_id for item in result.entities]
    assert ids == ["dwd_station_00433", "dwd_station_00403"]  # nearest to centre first
    first = result.entities[0]
    assert first.label == "Berlin-Tempelhof"
    assert first.attributes == {
        "station_id": "00433",
        "elevation_m": 48,
        "state": "Berlin",
        "inventory_until": "2026-11-22",
    }
    assert first.location.entity.entity_type == "weather_station"
    assert first.location.evidence[0].record_id.startswith(
        "zehn_now_tu_Beschreibung_Stationen.txt:00433:"
    )


def test_station_names_with_spaces_and_multi_word_states_are_kept_intact() -> None:
    payload = (
        HEADER + row("00433", 52.4675, 13.4021, name="Berlin Mitte Nord", state="Berlin")
    ).encode("latin-1")

    item = discovery(payload).discover(BERLIN).entities[0]

    assert item.label == "Berlin Mitte Nord"
    assert item.attributes["state"] == "Berlin"


def test_max_stations_limits_the_result_deterministically() -> None:
    config = DwdAreaConfig(city_id="berlin", source_id="dwd_open_data", max_stations=1)
    payload = (HEADER + row("00403", 52.4537, 13.3017) + row("00433", 52.4675, 13.4021)).encode(
        "latin-1"
    )

    result = discovery(payload, config=config).discover(BERLIN)

    assert [item.location.entity.entity_id for item in result.entities] == ["dwd_station_00433"]


def test_malformed_rows_are_skipped_but_never_invent_locations() -> None:
    payload = (HEADER + "00433 broken\n" + row("00403", 52.4537, 13.3017)).encode("latin-1")

    result = discovery(payload).discover(BERLIN)

    assert [item.location.entity.entity_id for item in result.entities] == ["dwd_station_00403"]


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (TimeoutError(), ProviderErrorCode.TIMEOUT),
        (OSError("down"), ProviderErrorCode.UPSTREAM),
        (b"not an inventory\n", ProviderErrorCode.INVALID_RESPONSE),
        (HEADER.encode("latin-1"), ProviderErrorCode.INVALID_RESPONSE),
    ],
)
def test_unreadable_inventory_makes_discovery_unavailable(
    payload: bytes | Exception, code: ProviderErrorCode
) -> None:
    result = discovery(payload).discover(BERLIN)

    assert result.status is DiscoveryStatus.UNAVAILABLE
    assert result.entities == ()
    assert result.error is not None and result.error.code is code


def test_discovery_requires_matching_city_with_area() -> None:
    mainz = load_city_definition(ROOT / "cities" / "mainz" / "city.yaml")
    with pytest.raises(ValueError, match="city"):
        discovery(HEADER.encode("latin-1")).discover(mainz)


def test_shipped_area_configs_validate() -> None:
    for path in sorted(ROOT.glob("cities/*/providers/dwd_air_temperature_area.yaml")):
        config = load_dwd_area_config(path)
        city = load_city_definition(path.parents[1] / "city.yaml")
        assert config.city_id == city.id
        assert city.area is not None
        assert any(source.id == config.source_id for source in city.sources)


def test_duplicate_inventory_rows_for_one_station_are_trusted_by_neither() -> None:
    payload = (
        HEADER
        + row("00433", 52.4675, 13.4021)
        + row("00433", 52.5, 13.4)
        + row("00403", 52.45, 13.3)
    ).encode("latin-1")

    result = discovery(payload).discover(BERLIN)

    assert [item.location.entity.entity_id for item in result.entities] == ["dwd_station_00403"]


def test_station_whose_inventory_ended_more_than_a_week_ago_counts_as_closed() -> None:
    payload = (
        HEADER + row("00433", 52.4675, 13.4021) + row("00403", 52.4537, 13.3017, until="20261110")
    ).encode("latin-1")

    result = discovery(payload).discover(BERLIN)

    assert [item.location.entity.entity_id for item in result.entities] == ["dwd_station_00433"]


def test_surroundings_bring_in_stations_just_outside_the_area() -> None:
    raw = BERLIN.model_dump(mode="json")
    raw["area"]["surroundings_km"] = 15
    with_ring = BERLIN.model_validate(raw)
    payload = (
        HEADER
        + row("00433", 52.4675, 13.4021)
        + row("00427", 52.3807, 13.5306)
        # ~10 km south of the area
        + row("05825", 52.25, 13.40, name="Umlandstation")
    ).encode("latin-1")

    without = discovery(payload).discover(BERLIN)
    with_surroundings = discovery(payload).discover(with_ring)

    assert "dwd_station_05825" not in [e.location.entity.entity_id for e in without.entities]
    assert "dwd_station_05825" in [e.location.entity.entity_id for e in with_surroundings.entities]
    validate_discovery_result(with_ring, with_surroundings)
