"""Runtime composition root for the Urbanium machine API."""

import os
from pathlib import Path

from fastapi import FastAPI

from urbanium.api.app import create_app
from urbanium.core.provider import ObservationProvider
from urbanium.providers.dwd.air_temperature import (
    DwdCdcAirTemperatureProvider,
    load_dwd_air_temperature_config,
)
from urbanium.registry import CityRegistry


def create_runtime_app(cities_root: Path | None = None) -> FastAPI:
    """Compose validated city definitions with implemented provider adapters."""

    root = cities_root or Path(os.environ.get("URBANIUM_CITIES", "cities"))
    registry = CityRegistry.from_directory(root)

    providers: list[ObservationProvider] = []
    for config_path in sorted(root.glob("*/providers/dwd_air_temperature.yaml")):
        config = load_dwd_air_temperature_config(config_path)
        providers.append(DwdCdcAirTemperatureProvider(config))

    return create_app(registry, providers=providers)
