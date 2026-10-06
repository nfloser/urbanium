"""FastAPI application factory for the versioned Urbanium machine API."""

from collections.abc import Iterable
from typing import Never

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from urbanium.api.contracts import (
    API_SEMVER,
    API_VERSION,
    ApiProblem,
    CapabilitiesResponse,
    CitiesResponse,
    CityResponse,
    ObservationReadResponse,
    SourcesResponse,
)
from urbanium.core.city import CapabilitySupport, CityDefinition, SourceDefinition
from urbanium.core.provider import (
    Availability,
    ObservationProvider,
    validate_provider_descriptor,
    validate_provider_result,
)
from urbanium.registry import CityRegistry

ProviderKey = tuple[str, str, str]


class ApiError(Exception):
    """Internal control-flow error rendered as a stable v1 problem body."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def create_app(
    registry: CityRegistry,
    *,
    providers: Iterable[ObservationProvider] = (),
) -> FastAPI:
    """Build one API application over validated registry/provider boundaries."""

    bindings = _bind_providers(registry, providers)
    app = FastAPI(
        title="Urbanium Platform API",
        version=API_SEMVER,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
    )

    @app.exception_handler(ApiError)
    async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
        body = ApiProblem(code=exc.code, message=exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder(body),
        )

    @app.get("/api/v1/cities", response_model=CitiesResponse)
    def list_cities() -> CitiesResponse:
        return CitiesResponse(cities=registry.cities)

    @app.get(
        "/api/v1/cities/{city_id}",
        response_model=CityResponse,
        responses={404: {"model": ApiProblem}},
    )
    def get_city(city_id: str) -> CityResponse:
        return CityResponse(city=_city(registry, city_id))

    @app.get(
        "/api/v1/cities/{city_id}/capabilities",
        response_model=CapabilitiesResponse,
        responses={404: {"model": ApiProblem}},
    )
    def list_capabilities(city_id: str) -> CapabilitiesResponse:
        city = _city(registry, city_id)
        capabilities = tuple(sorted(city.capabilities, key=lambda item: item.id))
        return CapabilitiesResponse(city_id=city.id, capabilities=capabilities)

    @app.get(
        "/api/v1/cities/{city_id}/sources",
        response_model=SourcesResponse,
        responses={404: {"model": ApiProblem}},
    )
    def list_sources(city_id: str) -> SourcesResponse:
        city = _city(registry, city_id)
        sources = tuple(sorted(city.sources, key=lambda item: item.id))
        return SourcesResponse(city_id=city.id, sources=sources)

    @app.get(
        "/api/v1/cities/{city_id}/sources/{source_id}/observations/{capability_id}",
        response_model=ObservationReadResponse,
        responses={
            404: {"model": ApiProblem},
            409: {"model": ApiProblem},
            503: {"model": ObservationReadResponse | ApiProblem},
        },
    )
    def read_observations(
        city_id: str,
        source_id: str,
        capability_id: str,
    ) -> ObservationReadResponse | JSONResponse:
        city = _city(registry, city_id)
        capability = _capability(registry, city_id, capability_id)
        source = _source(city, source_id)

        if capability_id not in source.capabilities:
            _fail(
                404,
                "source_capability_not_found",
                f"source '{source_id}' does not provide capability '{capability_id}'",
            )
        if capability.support is not CapabilitySupport.CONFIGURED:
            _fail(
                409,
                "capability_not_configured",
                f"capability '{capability_id}' is not configured for city '{city_id}'",
            )

        key = (city_id, source_id, capability_id)
        provider = bindings.get(key)
        if provider is None:
            _fail(
                503,
                "provider_not_bound",
                (
                    f"no runtime provider is bound for city '{city_id}', "
                    f"source '{source_id}', capability '{capability_id}'"
                ),
            )

        result = provider.read()
        validate_provider_result(provider.descriptor, result)
        response = ObservationReadResponse(
            city_id=city_id,
            source_id=source_id,
            capability_id=capability_id,
            result=result,
        )
        if result.availability is Availability.UNAVAILABLE:
            return JSONResponse(status_code=503, content=jsonable_encoder(response))
        return response

    return app


def _bind_providers(
    registry: CityRegistry,
    providers: Iterable[ObservationProvider],
) -> dict[ProviderKey, ObservationProvider]:
    bindings: dict[ProviderKey, ObservationProvider] = {}
    for provider in providers:
        descriptor = provider.descriptor
        try:
            city = registry.city(descriptor.city_id)
        except KeyError as exc:
            raise ValueError(
                f"provider '{descriptor.source_id}' references unknown city '{descriptor.city_id}'"
            ) from exc

        validate_provider_descriptor(city, descriptor)
        key = (
            descriptor.city_id,
            descriptor.source_id,
            descriptor.capability_id,
        )
        if key in bindings:
            raise ValueError(
                "duplicate provider binding "
                f"'{descriptor.city_id}:{descriptor.source_id}:{descriptor.capability_id}'"
            )
        bindings[key] = provider
    return bindings


def _city(registry: CityRegistry, city_id: str) -> CityDefinition:
    try:
        return registry.city(city_id)
    except KeyError:
        _fail(404, "city_not_found", f"unknown city '{city_id}'")


def _capability(registry: CityRegistry, city_id: str, capability_id: str):
    try:
        return registry.capability(city_id, capability_id)
    except KeyError:
        _fail(
            404,
            "capability_not_found",
            f"city '{city_id}' does not declare capability '{capability_id}'",
        )


def _source(city: CityDefinition, source_id: str) -> SourceDefinition:
    for source in city.sources:
        if source.id == source_id:
            return source
    _fail(404, "source_not_found", f"city '{city.id}' does not declare source '{source_id}'")


def _fail(status_code: int, code: str, message: str) -> Never:
    raise ApiError(status_code, code, message)


__all__ = ["API_VERSION", "create_app"]
