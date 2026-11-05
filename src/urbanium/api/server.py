"""Runtime composition root for the Urbanium machine API."""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from urbanium.api.app import create_app
from urbanium.core.provider import ObservationProvider
from urbanium.providers.dwd.air_temperature import (
    DwdCdcAirTemperatureProvider,
    load_dwd_air_temperature_config,
)
from urbanium.providers.vbb.gtfs_rt import VbbGtfsRtProvider, load_vbb_gtfs_rt_config
from urbanium.registry import CityRegistry


def create_runtime_app(cities_root: Path | None = None) -> FastAPI:
    """Compose validated city definitions with implemented provider adapters."""

    root = cities_root or Path(os.environ.get("URBANIUM_CITIES", "cities"))
    registry = CityRegistry.from_directory(root)

    providers: list[ObservationProvider] = []
    for config_path in sorted(root.glob("*/providers/dwd_air_temperature.yaml")):
        dwd_config = load_dwd_air_temperature_config(config_path)
        providers.append(DwdCdcAirTemperatureProvider(dwd_config))
    for config_path in sorted(root.glob("*/providers/vbb_gtfs_rt.yaml")):
        vbb_config = load_vbb_gtfs_rt_config(config_path)
        providers.append(VbbGtfsRtProvider(vbb_config))

    app = create_app(registry, providers=providers)
    dashboard = Path(__file__).with_name("dashboard") / "index.html"

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def show_dashboard() -> HTMLResponse:
        return HTMLResponse(dashboard.read_text(encoding="utf-8"))

    return app
