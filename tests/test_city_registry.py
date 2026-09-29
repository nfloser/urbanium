from pathlib import Path

import pytest

from urbanium.core.city import CapabilitySupport
from urbanium.registry import CityConfigurationError, CityRegistry, load_city_definition

ROOT = Path(__file__).resolve().parents[1]
CITIES = ROOT / "cities"


def test_berlin_and_mainz_use_the_same_city_contract() -> None:
    berlin = load_city_definition(CITIES / "berlin" / "city.yaml")
    mainz = load_city_definition(CITIES / "mainz" / "city.yaml")

    assert type(berlin) is type(mainz)
    assert berlin.schema_version == "1"
    assert mainz.schema_version == "1"
    assert berlin.id == "berlin"
    assert mainz.id == "mainz"


def test_capabilities_are_explicit_instead_of_fabricated() -> None:
    registry = CityRegistry.from_directory(CITIES)

    assert registry.capability("berlin", "weather").support is CapabilitySupport.CONFIGURED
    assert registry.capability("mainz", "weather").support is CapabilitySupport.CONFIGURED
    assert registry.capability("berlin", "realtime_transport").support is CapabilitySupport.CONFIGURED
    assert registry.capability("mainz", "realtime_transport").support is CapabilitySupport.CANDIDATE
    assert registry.capability("mainz", "river_level").support is CapabilitySupport.CONFIGURED
    assert registry.capability("berlin", "river_level").support is CapabilitySupport.UNKNOWN
    assert not registry.supports("mainz", "realtime_transport")


def test_configured_capability_has_a_verified_source() -> None:
    registry = CityRegistry.from_directory(CITIES)

    for city in registry.cities:
        for capability in city.capabilities:
            if capability.support is not CapabilitySupport.CONFIGURED:
                continue
            sources = registry.sources_for_capability(city.id, capability.id)
            assert sources
            assert any(source.status.value == "verified" for source in sources)


def test_source_licence_metadata_is_present() -> None:
    registry = CityRegistry.from_directory(CITIES)

    for city in registry.cities:
        for source in city.sources:
            assert source.license.redistribution.value in {"permitted", "restricted", "unknown"}
            assert source.license.identifier or source.license.terms_url or source.license.notes


def test_malformed_city_configuration_fails_clearly(tmp_path: Path) -> None:
    path = tmp_path / "city.yaml"
    path.write_text(
        """
schema_version: "1"
id: example
name: Example
country_code: DE
timezone: Europe/Berlin
capabilities:
  - id: weather
    support: configured
sources: []
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(CityConfigurationError, match="configured capability 'weather'"):
        load_city_definition(path)
