import os
from pathlib import Path

import pytest

from urbanium.core.provider import Availability
from urbanium.providers.vbb.gtfs_rt import VbbGtfsRtProvider, load_vbb_gtfs_rt_config

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("URBANIUM_LIVE_VBB") != "1",
    reason="set URBANIUM_LIVE_VBB=1 to access the VBB GTFS-Realtime feed",
)
def test_current_vbb_gtfs_rt_feed_is_readable() -> None:
    config = load_vbb_gtfs_rt_config(ROOT / "cities" / "berlin" / "providers" / "vbb_gtfs_rt.yaml")

    result = VbbGtfsRtProvider(config).read()

    assert result.availability is not Availability.UNAVAILABLE, result.error
    assert result.observations
    assert result.observations[0].quantity_id == "active_service_alerts"
