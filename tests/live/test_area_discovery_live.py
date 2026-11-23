"""Live checks that the area-based sources still answer in the formats we parse.

Run weekly by .github/workflows/live-check.yml; locally enable with
URBANIUM_LIVE_AREA=1. A failure means an upstream format, endpoint or
inventory changed, not that Urbanium's deterministic logic is wrong.
"""

import os
from pathlib import Path

import pytest

from urbanium.core.discovery import DiscoveryStatus, validate_discovery_result
from urbanium.core.provider import Availability
from urbanium.providers.dwd.discovery import DwdStationDiscovery, load_dwd_area_config
from urbanium.providers.dwd.network import DwdAirTemperatureNetworkProvider
from urbanium.providers.pegelonline.water_level import (
    PegelonlineGaugeDiscovery,
    PegelonlineWaterLevelProvider,
    load_pegelonline_config,
)
from urbanium.registry import load_city_definition

ROOT = Path(__file__).resolve().parents[2]
CITIES = ROOT / "cities"

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("URBANIUM_LIVE_AREA") != "1",
        reason="set URBANIUM_LIVE_AREA=1 to query DWD and PEGELONLINE by city area",
    ),
]


@pytest.mark.parametrize("city_id", ["berlin", "hamburg"])
def test_dwd_now_inventory_yields_stations_with_plausible_temperatures(city_id: str) -> None:
    city = load_city_definition(CITIES / city_id / "city.yaml")
    config = load_dwd_area_config(CITIES / city_id / "providers" / "dwd_air_temperature_area.yaml")

    discovery = DwdStationDiscovery(config).discover(city)

    validate_discovery_result(city, discovery)
    assert discovery.status is DiscoveryStatus.AVAILABLE, discovery.error
    assert discovery.entities, "no active DWD station found in the area"
    result = DwdAirTemperatureNetworkProvider(config, discovery.entities).read()
    assert result.availability is not Availability.UNAVAILABLE, result.error
    assert all(-45 <= float(item.value) <= 50 for item in result.observations)


@pytest.mark.parametrize("city_id", ["berlin", "mainz"])
def test_pegelonline_yields_gauges_with_plausible_levels(city_id: str) -> None:
    city = load_city_definition(CITIES / city_id / "city.yaml")
    config = load_pegelonline_config(CITIES / city_id / "providers" / "pegelonline.yaml")

    discovery = PegelonlineGaugeDiscovery(config).discover(city)

    validate_discovery_result(city, discovery)
    assert discovery.status is DiscoveryStatus.AVAILABLE, discovery.error
    assert discovery.entities, "no PEGELONLINE gauge with a W series found in the area"
    assert all("water" in item.attributes for item in discovery.entities)
    result = PegelonlineWaterLevelProvider(config, discovery.entities).read()
    assert result.availability is not Availability.UNAVAILABLE, result.error
    assert all(-500 <= float(item.value) <= 3000 for item in result.observations)
