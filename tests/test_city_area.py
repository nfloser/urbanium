"""A city area is a discovery envelope, not an administrative boundary."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from urbanium.core.city import CityArea, CityDefinition
from urbanium.core.spatial import Wgs84Point, distance_km
from urbanium.registry import load_city_definition

ROOT = Path(__file__).resolve().parents[1]


def area(**overrides: float) -> CityArea:
    values = {"south": 52.3, "west": 13.0, "north": 52.7, "east": 13.8}
    values.update(overrides)
    return CityArea.model_validate(values)


def test_area_contains_points_on_and_inside_its_edges() -> None:
    subject = area()

    assert subject.contains(Wgs84Point(latitude=52.5, longitude=13.4))
    assert subject.contains(Wgs84Point(latitude=52.3, longitude=13.0))
    assert not subject.contains(Wgs84Point(latitude=52.71, longitude=13.4))
    assert not subject.contains(Wgs84Point(latitude=52.5, longitude=12.99))


@pytest.mark.parametrize(
    "overrides",
    [
        {"south": 52.7, "north": 52.3},
        {"west": 13.8, "east": 13.0},
        {"south": 52.5, "north": 52.5},
        {"north": 91.0},
        {"east": 181.0},
    ],
)
def test_area_rejects_inverted_empty_or_out_of_range_envelopes(
    overrides: dict[str, float],
) -> None:
    with pytest.raises(ValidationError):
        area(**overrides)


def test_area_center_and_covering_radius_enclose_every_corner() -> None:
    subject = area()
    center = subject.center

    assert center == Wgs84Point(latitude=52.5, longitude=13.4)
    corners = [
        Wgs84Point(latitude=lat, longitude=lon)
        for lat in (subject.south, subject.north)
        for lon in (subject.west, subject.east)
    ]
    assert all(distance_km(center, corner) <= subject.covering_radius_km for corner in corners)


def test_distance_uses_great_circle_kilometres() -> None:
    berlin = Wgs84Point(latitude=52.52, longitude=13.405)
    mainz = Wgs84Point(latitude=49.9929, longitude=8.2473)

    assert distance_km(berlin, berlin) == 0
    assert 450 < distance_km(berlin, mainz) < 462
    assert distance_km(berlin, mainz) == pytest.approx(distance_km(mainz, berlin))


def test_area_is_optional_so_existing_definitions_remain_valid() -> None:
    city = load_city_definition(ROOT / "cities" / "berlin" / "city.yaml")
    minimal = CityDefinition.model_validate(
        {
            "schema_version": "1",
            "id": "example",
            "name": "Example",
            "country_code": "DE",
            "timezone": "Europe/Berlin",
            "capabilities": [],
            "sources": [],
        }
    )

    assert minimal.area is None
    assert city.area is not None


def test_surroundings_extend_the_search_envelope_but_not_the_area() -> None:
    subject = area(surroundings_km=10)
    envelope = subject.search_envelope
    ring_point = Wgs84Point(latitude=52.75, longitude=13.4)  # ~5.6 km north of the area

    assert not subject.contains(ring_point)
    assert envelope.contains(ring_point)
    assert subject.in_surroundings(ring_point)
    assert not subject.in_surroundings(Wgs84Point(latitude=52.5, longitude=13.4))
    assert not envelope.contains(Wgs84Point(latitude=52.9, longitude=13.4))
    assert envelope.north - subject.north == pytest.approx(10 / 111.32, rel=1e-3)
    assert envelope.surroundings_km == 0
    assert envelope.covering_radius_km > subject.covering_radius_km


def test_without_surroundings_the_envelope_is_the_area() -> None:
    subject = area()

    assert subject.search_envelope == subject
