"""Dependency-free WGS84 geometry primitives shared by core contracts."""

from math import asin, cos, radians, sin, sqrt
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

EARTH_RADIUS_KM = 6371.0088


class Wgs84Point(BaseModel):
    """Latitude/longitude in EPSG:4326 degrees, not an area of coverage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


def distance_km(a: Wgs84Point, b: Wgs84Point) -> float:
    """Great-circle (haversine) distance on the mean Earth radius."""

    lat1, lon1, lat2, lon2 = map(radians, (a.latitude, a.longitude, b.latitude, b.longitude))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(min(1.0, sqrt(h)))


class CityArea(BaseModel):
    """WGS84 envelope in which a deployment discovers sources.

    The envelope is a deliberately simple search area. It is not an
    administrative boundary and does not imply that every point inside it is
    part of the city or covered by any source.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    south: float = Field(ge=-90, le=90, allow_inf_nan=False)
    west: float = Field(ge=-180, le=180, allow_inf_nan=False)
    north: float = Field(ge=-90, le=90, allow_inf_nan=False)
    east: float = Field(ge=-180, le=180, allow_inf_nan=False)
    # Optional ring around the area that discovery also searches. Entities in
    # it are reported as being in the surroundings, never as in the city.
    surroundings_km: float = Field(default=0, ge=0, le=50, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_orientation(self) -> Self:
        if self.south >= self.north:
            raise ValueError("area south must be below north")
        if self.west >= self.east:
            raise ValueError("area west must be below east (antimeridian spans unsupported)")
        return self

    def contains(self, point: Wgs84Point) -> bool:
        return (
            self.south <= point.latitude <= self.north and self.west <= point.longitude <= self.east
        )

    @property
    def search_envelope(self) -> "CityArea":
        """The area grown by `surroundings_km` on every side (itself without a ring)."""

        if self.surroundings_km == 0:
            return self
        dlat = self.surroundings_km / 111.32
        dlon = self.surroundings_km / (111.32 * max(cos(radians(self.center.latitude)), 0.01))
        return CityArea(
            south=max(-90.0, self.south - dlat),
            west=max(-180.0, self.west - dlon),
            north=min(90.0, self.north + dlat),
            east=min(180.0, self.east + dlon),
        )

    def in_surroundings(self, point: Wgs84Point) -> bool:
        return not self.contains(point) and self.search_envelope.contains(point)

    @property
    def center(self) -> Wgs84Point:
        return Wgs84Point(
            latitude=(self.south + self.north) / 2,
            longitude=(self.west + self.east) / 2,
        )

    @property
    def covering_radius_km(self) -> float:
        """Smallest radius around `center` that reaches every corner."""

        center = self.center
        return max(
            distance_km(center, Wgs84Point(latitude=lat, longitude=lon))
            for lat in (self.south, self.north)
            for lon in (self.west, self.east)
        )
