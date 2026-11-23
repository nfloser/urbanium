"""Extract a self-hosted vector basemap per city from a Protomaps OSM build.

    python demo/basemaps.py OUT_DIR [--cities cities] [--maxzoom 13]

Needs the `pmtiles` CLI (github.com/protomaps/go-pmtiles) on PATH. The newest
daily planet build is located through build-metadata.protomaps.dev and only
the byte ranges for each city's area are downloaded. Existing files are kept,
so a cached directory is only filled up. Data © OpenStreetMap contributors
(ODbL), schema and builds by Protomaps.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

from urbanium.core.city import CityDefinition
from urbanium.registry import CityRegistry

BUILDS = "https://build-metadata.protomaps.dev/builds.json"
PLANET = "https://build.protomaps.com/{key}"
MARGIN_DEG = 0.03


def bbox(city: CityDefinition) -> tuple[float, float, float, float] | None:
    """west, south, east, north of the search envelope plus a small margin."""

    if city.area is None:
        return None
    envelope = city.area.search_envelope
    return (
        round(envelope.west - MARGIN_DEG, 4),
        round(envelope.south - MARGIN_DEG, 4),
        round(envelope.east + MARGIN_DEG, 4),
        round(envelope.north + MARGIN_DEG, 4),
    )


def latest_build() -> str:
    with urlopen(BUILDS, timeout=30) as response:  # noqa: S310 - fixed metadata URL
        builds = json.load(response)
    keys = sorted(item["key"] for item in builds if str(item.get("key", "")).endswith(".pmtiles"))
    if not keys:
        raise RuntimeError("no Protomaps build listed")
    return keys[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument("--cities", type=Path, default=Path("cities"))
    parser.add_argument("--maxzoom", type=int, default=13)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    todo = [
        (city.id, box)
        for city in CityRegistry.from_directory(args.cities).cities
        if (box := bbox(city)) is not None and not (args.out / f"{city.id}.pmtiles").is_file()
    ]
    if not todo:
        print("all basemaps present", file=sys.stderr)
        return 0
    source = PLANET.format(key=latest_build())
    failed = 0
    for city_id, box in todo:
        target = args.out / f"{city_id}.pmtiles"
        command = [
            "pmtiles",
            "extract",
            source,
            str(target),
            "--bbox=" + ",".join(str(value) for value in box),
            f"--maxzoom={args.maxzoom}",
        ]
        print(" ".join(command), file=sys.stderr)
        if subprocess.run(command, check=False).returncode != 0:
            target.unlink(missing_ok=True)
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
