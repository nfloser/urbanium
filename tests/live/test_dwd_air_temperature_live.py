import os
from pathlib import Path

import pytest

from urbanium.core.provider import Availability
from urbanium.providers.dwd.air_temperature import (
    DwdCdcAirTemperatureProvider,
    load_dwd_air_temperature_config,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("URBANIUM_LIVE_DWD") != "1",
    reason="set URBANIUM_LIVE_DWD=1 to access DWD Open Data",
)
@pytest.mark.parametrize("city_id", ["berlin", "mainz"])
def test_current_dwd_station_archive_is_readable(city_id: str) -> None:
    config = load_dwd_air_temperature_config(
        ROOT / "cities" / city_id / "providers" / "dwd_air_temperature.yaml"
    )

    result = DwdCdcAirTemperatureProvider(config).read()

    assert result.availability is not Availability.UNAVAILABLE, result.error
    assert result.observations
