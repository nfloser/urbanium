"""Basemap extracts cover each city's whole search envelope."""

import importlib.util
from pathlib import Path

from urbanium.registry import CityRegistry

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("basemaps", ROOT / "demo" / "basemaps.py")
assert spec is not None and spec.loader is not None
basemaps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(basemaps)


def test_bbox_covers_the_search_envelope_including_surroundings() -> None:
    for city in CityRegistry.from_directory(ROOT / "cities").cities:
        box = basemaps.bbox(city)
        assert box is not None and city.area is not None
        west, south, east, north = box
        envelope = city.area.search_envelope
        assert west < envelope.west and east > envelope.east
        assert south < envelope.south and north > envelope.north


def test_city_without_area_gets_no_extract() -> None:
    city = CityRegistry.from_directory(ROOT / "cities").city("berlin")
    assert basemaps.bbox(city.model_copy(update={"area": None})) is None


def test_newest_build_key_accepts_both_spellings_and_ignores_others() -> None:
    keys = ["20261119.pmtiles", "20261121", "latest", "20261120.pmtiles", "2026112.pmtiles"]

    assert basemaps.newest_key(keys) == "20261121.pmtiles"
    assert basemaps.newest_key(["nothing"]) is None
