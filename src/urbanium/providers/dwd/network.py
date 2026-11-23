"""Read all discovered DWD stations of a city as one air-temperature network."""

from collections.abc import Iterable

from urbanium.core.discovery import DiscoveredEntity
from urbanium.core.provider import (
    Availability,
    Freshness,
    Observation,
    ProviderDescriptor,
    ProviderError,
    ProviderErrorCode,
    ProviderResult,
)
from urbanium.providers.dwd.air_temperature import (
    Clock,
    DwdAirTemperatureConfig,
    DwdCdcAirTemperatureProvider,
    FetchBytes,
)
from urbanium.providers.dwd.discovery import DwdAreaConfig


class DwdAirTemperatureNetworkProvider:
    """Combine the per-station `now` series into one sourced weather read.

    Each station is still read through the single-station adapter, so parsing,
    limits and quality semantics stay identical. The network only aggregates
    outcomes and never fills in a missing station.
    """

    def __init__(
        self,
        config: DwdAreaConfig,
        stations: Iterable[DiscoveredEntity],
        *,
        fetcher: FetchBytes | None = None,
        clock: Clock | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.config = config
        self.stations = tuple(stations)
        self._members: list[DwdCdcAirTemperatureProvider] = []
        for item in self.stations:
            entity = item.location.entity
            station_id = item.attributes.get("station_id")
            if (
                entity.city_id != config.city_id
                or entity.entity_type != "weather_station"
                or not isinstance(station_id, str)
                or any(
                    evidence.source_id != config.source_id for evidence in item.location.evidence
                )
            ):
                raise ValueError(f"station '{entity.canonical_id}' does not belong to this binding")
            self._members.append(
                DwdCdcAirTemperatureProvider(
                    DwdAirTemperatureConfig(
                        city_id=config.city_id,
                        source_id=config.source_id,
                        station_id=station_id,
                        station_name=item.label,
                        freshness_minutes=config.freshness_minutes,
                    ),
                    fetcher=fetcher,
                    clock=clock,
                    timeout=timeout,
                )
            )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            city_id=self.config.city_id,
            source_id=self.config.source_id,
            capability_id="weather",
            adapter_version="1.0.0",
        )

    def read(self) -> ProviderResult:
        if not self._members:
            return _unavailable(ProviderErrorCode.INVALID_RESPONSE, "no stations discovered")

        observations: list[Observation] = []
        failed: list[ProviderError] = []
        notes: list[str] = []
        stale = False
        for member in self._members:
            result = member.read_series()
            if result.availability is Availability.UNAVAILABLE:
                if result.error is not None:
                    failed.append(result.error)
                continue
            if result.freshness is not Freshness.FRESH:
                stale = True
            if result.error is not None:
                notes.append(f"station {member.config.station_id}: {result.error.message}")
            observations.extend(result.observations)

        total = len(self._members)
        if not observations:
            codes = {item.code for item in failed}
            code = codes.pop() if len(codes) == 1 else ProviderErrorCode.UPSTREAM
            return _unavailable(code, f"{total} of {total} stations returned no air temperature")

        if failed:
            notes.insert(0, f"{len(failed)} of {total} stations returned no air temperature")
        freshness = Freshness.STALE if stale else Freshness.FRESH
        if notes:
            return ProviderResult(
                availability=Availability.DEGRADED,
                freshness=freshness,
                observations=tuple(observations),
                error=ProviderError(
                    code=ProviderErrorCode.UPSTREAM
                    if failed
                    else ProviderErrorCode.INVALID_RESPONSE,
                    message="; ".join(notes),
                ),
            )
        return ProviderResult(
            availability=Availability.AVAILABLE,
            freshness=freshness,
            observations=tuple(observations),
        )


def _unavailable(code: ProviderErrorCode, message: str) -> ProviderResult:
    return ProviderResult(
        availability=Availability.UNAVAILABLE,
        freshness=Freshness.UNKNOWN,
        error=ProviderError(code=code, message=message),
    )


__all__ = ["DwdAirTemperatureNetworkProvider"]
