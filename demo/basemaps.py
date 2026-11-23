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
import re
import subprocess
import sys
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from urbanium.core.city import CityDefinition
from urbanium.registry import CityRegistry

BUILDS = "https://build-metadata.protomaps.dev/builds.json"
PLANET = "https://build.protomaps.com/{key}"
MARGIN_DEG = 0.03
# Some hosts reject urllib's default user agent (the first CI run got HTTP 403).
HEADERS = {"User-Agent": "Urbanium basemap extract (https://github.com/nfloser/urbanium)"}


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


def newest_key(keys: Iterable[str]) -> str | None:
    """Newest daily build key, accepting '20261120' and '20261120.pmtiles'."""

    dated = sorted(
        match.group(1)
        for key in keys
        if (match := re.fullmatch(r"(\d{8})(?:\.pmtiles)?", str(key).strip()))
    )
    return f"{dated[-1]}.pmtiles" if dated else None


def latest_build() -> str:
    """Newest build from the metadata list, else by probing the last ten days."""

    try:
        with urlopen(Request(BUILDS, headers=HEADERS), timeout=30) as response:  # noqa: S310
            listed = json.load(response)
        key = newest_key(item.get("key", "") for item in listed if isinstance(item, dict))
        if key:
            return key
    except (URLError, OSError, ValueError) as exc:
        print(f"build list unavailable ({exc}); probing recent builds", file=sys.stderr)
    today = datetime.now(UTC).date()
    for days in range(10):
        key = f"{today - timedelta(days=days):%Y%m%d}.pmtiles"
        try:
            request = Request(PLANET.format(key=key), headers=HEADERS, method="HEAD")
            with urlopen(request, timeout=30):  # noqa: S310 - fixed host
                return key
        except (URLError, OSError):
            continue
    raise RuntimeError("no Protomaps build found in the last ten days")


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
