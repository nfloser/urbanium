"""Runtime composition root for the Urbanium machine API."""

import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import JsonValue

from urbanium.analysis.observation_inputs import observation_input
from urbanium.analysis.weather_transport_readiness import assess_weather_transport_readiness
from urbanium.api.app import create_app
from urbanium.core.provider import ObservationProvider
from urbanium.providers.dwd.air_temperature import (
    DwdCdcAirTemperatureProvider,
    load_dwd_air_temperature_config,
)
from urbanium.providers.dwd.station_location import (
    DwdCdcStationLocationProvider,
    DwdStationMetadataError,
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

    @app.get("/demo/cities/{city_id}/evidence", include_in_schema=False)
    def inspect_evidence(city_id: str) -> dict[str, JsonValue]:
        weather = [
            provider
            for provider in providers
            if isinstance(provider, DwdCdcAirTemperatureProvider)
            and provider.config.city_id == city_id
        ]
        transport = [
            provider
            for provider in providers
            if isinstance(provider, VbbGtfsRtProvider) and provider.config.city_id == city_id
        ]
        if len(weather) != 1 or len(transport) != 1:
            raise HTTPException(404, "No unique weather and transport provider pair")

        weather_read = weather[0].read()
        transit = transport[0].read_snapshot()
        now = datetime.now(UTC)
        city = registry.city(city_id)
        readiness = assess_weather_transport_readiness(
            city,
            weather=observation_input(city, weather[0].descriptor, weather_read, prepared_at=now),
            transport=observation_input(
                city, transport[0].descriptor, transit.result, prepared_at=now
            ),
            executed_at=now,
        )
        station = None
        station_error = None
        try:
            station = DwdCdcStationLocationProvider(weather[0].config).read()
        except DwdStationMetadataError as exc:
            station_error = str(exc)

        return {
            "readiness": readiness.model_dump(mode="json"),
            "station": station.model_dump(mode="json") if station else None,
            "station_name": weather[0].config.station_name,
            "station_error": station_error,
            "transport_status": transit.result.availability.value,
            "alert_stop_reference_count": len(transit.stop_references),
            "alert_stop_references": [
                {"alert_id": ref.alert_id, "stop_id": ref.stop_id, "selector": ref.selector_index}
                for ref in transit.stop_references[:100]
            ],
        }

    return app
