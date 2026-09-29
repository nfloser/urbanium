"""Load and query versioned city deployment definitions."""

from collections.abc import Iterable
from pathlib import Path

from pydantic import ValidationError
from yaml import YAMLError, safe_load

from urbanium.core.city import (
    CapabilityDefinition,
    CapabilitySupport,
    CityDefinition,
    SourceDefinition,
)


class CityConfigurationError(ValueError):
    """Raised when a city configuration cannot be parsed or validated."""


def load_city_definition(path: Path) -> CityDefinition:
    """Load one city.yaml file through the canonical city contract."""

    try:
        raw = safe_load(path.read_text(encoding="utf-8"))
    except (OSError, YAMLError) as exc:
        raise CityConfigurationError(f"failed to read city configuration {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise CityConfigurationError(f"city configuration {path} must contain a YAML mapping")

    try:
        return CityDefinition.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(error["msg"] for error in exc.errors())
        raise CityConfigurationError(f"invalid city configuration {path}: {details}") from exc


class CityRegistry:
    """Immutable lookup view over one or more validated city definitions."""

    def __init__(self, cities: Iterable[CityDefinition]) -> None:
        by_id: dict[str, CityDefinition] = {}
        for city in cities:
            if city.id in by_id:
                raise CityConfigurationError(f"duplicate city id '{city.id}'")
            by_id[city.id] = city
        self._cities = by_id

    @classmethod
    def from_directory(cls, root: Path) -> "CityRegistry":
        paths = sorted(root.glob("*/city.yaml"))
        if not paths:
            raise CityConfigurationError(f"no city.yaml files found below {root}")
        return cls(load_city_definition(path) for path in paths)

    @property
    def cities(self) -> tuple[CityDefinition, ...]:
        return tuple(self._cities[city_id] for city_id in sorted(self._cities))

    def city(self, city_id: str) -> CityDefinition:
        try:
            return self._cities[city_id]
        except KeyError as exc:
            raise KeyError(f"unknown city '{city_id}'") from exc

    def capability(self, city_id: str, capability_id: str) -> CapabilityDefinition:
        city = self.city(city_id)
        for capability in city.capabilities:
            if capability.id == capability_id:
                return capability
        raise KeyError(f"city '{city_id}' does not declare capability '{capability_id}'")

    def supports(self, city_id: str, capability_id: str) -> bool:
        try:
            capability = self.capability(city_id, capability_id)
        except KeyError:
            return False
        return capability.support is CapabilitySupport.CONFIGURED

    def sources_for_capability(
        self, city_id: str, capability_id: str
    ) -> tuple[SourceDefinition, ...]:
        self.capability(city_id, capability_id)
        city = self.city(city_id)
        return tuple(source for source in city.sources if capability_id in source.capabilities)
