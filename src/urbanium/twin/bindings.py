"""Compose a city's area-based source bindings from its provider configuration.

This module is a composition root: it is the only place in the twin layer that
knows concrete adapters. Agents and the snapshot model stay adapter-free.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from urbanium.core.discovery import DiscoveredEntity, SourceDiscovery
from urbanium.core.provider import ObservationProvider
from urbanium.providers.dwd.discovery import (
    DwdAreaConfig,
    DwdStationDiscovery,
    load_dwd_area_config,
)
from urbanium.providers.dwd.network import DwdAirTemperatureNetworkProvider
from urbanium.providers.pegelonline.water_level import (
    PegelonlineConfig,
    PegelonlineGaugeDiscovery,
    PegelonlineWaterLevelProvider,
    load_pegelonline_config,
)

FetchBytes = Callable[[str, float], bytes]
Clock = Callable[[], datetime]


@dataclass(frozen=True)
class AreaBinding:
    """One source capability whose entities are found by area discovery."""

    capability_id: str
    source_id: str
    quantity_id: str
    freshness_minutes: int
    discovery: SourceDiscovery
    provider_for: Callable[[tuple[DiscoveredEntity, ...]], ObservationProvider]


def area_bindings(city_dir: Path, *, fetcher: FetchBytes, clock: Clock) -> tuple[AreaBinding, ...]:
    """Bindings declared in `cities/<id>/providers/`, in a stable order."""

    providers = city_dir / "providers"
    bindings: list[AreaBinding] = []

    dwd_path = providers / "dwd_air_temperature_area.yaml"
    if dwd_path.is_file():
        dwd = load_dwd_area_config(dwd_path)
        bindings.append(
            AreaBinding(
                capability_id="weather",
                source_id=dwd.source_id,
                quantity_id="air_temperature",
                freshness_minutes=dwd.freshness_minutes,
                discovery=DwdStationDiscovery(dwd, fetcher=fetcher, clock=clock),
                provider_for=_dwd_network(dwd, fetcher, clock),
            )
        )

    pegel_path = providers / "pegelonline.yaml"
    if pegel_path.is_file():
        pegel = load_pegelonline_config(pegel_path)
        bindings.append(
            AreaBinding(
                capability_id="river_level",
                source_id=pegel.source_id,
                quantity_id="water_level",
                freshness_minutes=pegel.freshness_minutes,
                discovery=PegelonlineGaugeDiscovery(pegel, fetcher=fetcher, clock=clock),
                provider_for=_pegel_provider(pegel, fetcher, clock),
            )
        )
    return tuple(bindings)


ProviderFactory = Callable[[tuple[DiscoveredEntity, ...]], ObservationProvider]


def _dwd_network(config: DwdAreaConfig, fetcher: FetchBytes, clock: Clock) -> ProviderFactory:
    def make(stations: tuple[DiscoveredEntity, ...]) -> ObservationProvider:
        return DwdAirTemperatureNetworkProvider(config, stations, fetcher=fetcher, clock=clock)

    return make


def _pegel_provider(
    config: PegelonlineConfig, fetcher: FetchBytes, clock: Clock
) -> ProviderFactory:
    def make(gauges: tuple[DiscoveredEntity, ...]) -> ObservationProvider:
        return PegelonlineWaterLevelProvider(config, gauges, fetcher=fetcher, clock=clock)

    return make
