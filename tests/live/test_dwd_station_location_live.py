"""Optional external-source smoke test; never part of deterministic CI."""

import os
from pathlib import Path

import pytest

from urbanium.providers.dwd.air_temperature import load_dwd_air_temperature_config
from urbanium.providers.dwd.station_location import DwdCdcStationLocationProvider

ROOT = Path(__file__).resolve().parents[2]

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("URBANIUM_LIVE_DWD_STATIONS") != "1",
        reason="set URBANIUM_LIVE_DWD_STATIONS=1 to query the DWD station inventory",
    ),
]


@pytest.mark.parametrize("city", ["berlin", "mainz"])
def test_configured_dwd_station_has_a_sourced_inventory_point(city: str) -> None:
    config = load_dwd_air_temperature_config(
        ROOT / "cities" / city / "providers" / "dwd_air_temperature.yaml"
    )
    location = DwdCdcStationLocationProvider(config).read()

    assert location is not None
    assert location.entity.city_id == city
    assert location.entity.entity_id == f"dwd_station_{config.station_id}"
    assert location.evidence[0].source_id == config.source_id
