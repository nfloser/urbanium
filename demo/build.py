"""Build the static browser demo from the canonical city registry."""

import argparse
import json
from pathlib import Path
from shutil import copyfile

from urbanium.registry import CityRegistry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    cities = CityRegistry.from_directory(Path("cities")).cities
    args.output.mkdir(parents=True, exist_ok=True)
    for asset in ("index.html", "explorer.js"):
        copyfile(Path(__file__).with_name(asset), args.output / asset)
    (args.output / "catalog.json").write_text(
        json.dumps([city.model_dump(mode="json") for city in cities], ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
