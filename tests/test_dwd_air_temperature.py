from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from tests.contracts.provider import ProviderContractCases, assert_provider_contract
from urbanium.core.provider import Availability, Freshness, ProviderErrorCode
from urbanium.providers.dwd.air_temperature import (
    DwdAirTemperatureConfig,
    DwdCdcAirTemperatureProvider,
    load_dwd_air_temperature_config,
)
from urbanium.registry import load_city_definition

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "dwd"
NOW = datetime(2026, 9, 29, 12, 30, tzinfo=UTC)


def archive(fixture: str, station_id: str = "00433") -> bytes:
    payload = (FIXTURES / fixture).read_bytes().replace(b"00433", station_id.encode("ascii"))
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as target:
        target.writestr(f"produkt_zehn_now_tu_20260929_20260929_{station_id}.txt", payload)
    return buffer.getvalue()


def fetch(payload: bytes, station_id: str = "00433") -> Callable[[str, float], bytes]:
    def fixture_fetcher(url: str, timeout: float) -> bytes:
        assert url.endswith(f"/10minutenwerte_TU_{station_id}_now.zip")
        assert timeout == 10.0
        return payload

    return fixture_fetcher


def provider(
    fixture: str = "air_temperature_now.csv",
    *,
    now: datetime = NOW,
) -> DwdCdcAirTemperatureProvider:
    return DwdCdcAirTemperatureProvider(
        DwdAirTemperatureConfig(
            city_id="berlin",
            source_id="dwd_open_data",
            station_id="00433",
            station_name="Berlin-Tempelhof",
            freshness_minutes=90,
        ),
        fetcher=fetch(archive(fixture)),
        clock=lambda: now,
    )


def test_same_adapter_configuration_contract_is_used_by_berlin_and_mainz() -> None:
    berlin = load_dwd_air_temperature_config(
        ROOT / "cities" / "berlin" / "providers" / "dwd_air_temperature.yaml"
    )
    mainz = load_dwd_air_temperature_config(
        ROOT / "cities" / "mainz" / "providers" / "dwd_air_temperature.yaml"
    )

    assert type(berlin) is type(mainz)
    assert berlin.station_id == "00433"
    assert mainz.station_id == "03137"
    assert berlin.city_id == "berlin"
    assert mainz.city_id == "mainz"


def test_berlin_and_mainz_normalize_through_the_same_adapter() -> None:
    for city_id in ("berlin", "mainz"):
        config = load_dwd_air_temperature_config(
            ROOT / "cities" / city_id / "providers" / "dwd_air_temperature.yaml"
        )
        subject = DwdCdcAirTemperatureProvider(
            config,
            fetcher=fetch(archive("air_temperature_now.csv", config.station_id), config.station_id),
            clock=lambda: NOW,
        )

        result = subject.read()

        assert result.availability is Availability.AVAILABLE
        assert result.observations[0].city_id == city_id
        assert result.observations[0].entity_id == f"dwd_station_{config.station_id}"


def test_dwd_row_is_normalized_with_quality_time_unit_and_provenance() -> None:
    result = provider().read()

    assert result.availability is Availability.AVAILABLE
    assert result.freshness is Freshness.FRESH
    assert len(result.observations) == 1
    observation = result.observations[0]
    assert str(observation.value) == "17.1"
    assert observation.unit == "Cel"
    assert observation.observed_at == datetime(2026, 9, 29, 12, tzinfo=UTC)
    assert observation.received_at == NOW
    assert observation.quality_scheme == "dwd_qn"
    assert observation.quality_code == "2"
    assert observation.city_id == "berlin"
    assert observation.source_id == "dwd_open_data"
    assert observation.entity_id == "dwd_station_00433"


def test_freshness_is_assessed_without_changing_availability() -> None:
    result = provider(now=datetime(2026, 9, 29, 14, tzinfo=UTC)).read()

    assert result.availability is Availability.AVAILABLE
    assert result.freshness is Freshness.STALE


def test_partial_invalid_payload_degrades_instead_of_discarding_valid_data() -> None:
    result = provider("air_temperature_partial.csv").read()

    assert result.availability is Availability.DEGRADED
    assert result.error is not None
    assert result.error.code is ProviderErrorCode.INVALID_RESPONSE
    assert len(result.observations) == 1


def test_timeout_is_an_explicit_unavailable_result() -> None:
    def timeout(_url: str, _timeout: float) -> bytes:
        raise TimeoutError("fixture timeout")

    subject = DwdCdcAirTemperatureProvider(
        DwdAirTemperatureConfig(
            city_id="berlin",
            source_id="dwd_open_data",
            station_id="00433",
            station_name="Berlin-Tempelhof",
        ),
        fetcher=timeout,
        clock=lambda: NOW,
    )

    result = subject.read()
    assert result.availability is Availability.UNAVAILABLE
    assert result.freshness is Freshness.UNKNOWN
    assert result.error is not None
    assert result.error.code is ProviderErrorCode.TIMEOUT


def test_oversized_decompressed_product_is_rejected() -> None:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as target:
        target.writestr(
            "produkt_zehn_now_tu_20260929_20260929_00433.txt",
            b"x" * 2_000_001,
        )

    subject = DwdCdcAirTemperatureProvider(
        provider().config,
        fetcher=fetch(buffer.getvalue()),
        clock=lambda: NOW,
    )

    result = subject.read()

    assert result.availability is Availability.UNAVAILABLE
    assert result.error is not None
    assert result.error.code is ProviderErrorCode.INVALID_RESPONSE


def test_dwd_adapter_passes_shared_provider_contract() -> None:
    city = load_city_definition(ROOT / "cities" / "berlin" / "city.yaml")

    def timeout(_url: str, _timeout: float) -> bytes:
        raise TimeoutError("fixture timeout")

    config = provider().config
    assert_provider_contract(
        ProviderContractCases(
            city=city,
            available=provider(),
            degraded=provider("air_temperature_partial.csv"),
            unavailable=DwdCdcAirTemperatureProvider(
                config,
                fetcher=timeout,
                clock=lambda: NOW,
            ),
        )
    )
