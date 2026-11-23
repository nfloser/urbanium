"""`urbanium-twin build`: write static twin snapshots for every city with an area."""

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from urbanium.registry import CityRegistry
from urbanium.twin.bindings import area_bindings
from urbanium.twin.fetching import FetchBytes, RecordingFetcher, ReplayFetcher, live_fetch
from urbanium.twin.snapshot import (
    DataMode,
    TwinSnapshot,
    build_city_snapshot,
    build_index,
    project_snapshot,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="urbanium-twin", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="build snapshots, an index and Turtle files")
    build.add_argument("--cities", type=Path, default=Path("cities"))
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--only", action="append", default=[], help="limit to these city ids")
    build.add_argument(
        "--previous",
        type=Path,
        help="directory with earlier <city>.json snapshots used as last known values",
    )
    source = build.add_mutually_exclusive_group()
    source.add_argument("--record", type=Path, help="fetch live and keep every response here")
    source.add_argument("--replay", type=Path, help="serve responses from a recording")
    args = parser.parse_args(argv)

    fetcher: FetchBytes
    recorder: RecordingFetcher | None = None
    if args.replay:
        replay = ReplayFetcher(args.replay)
        fetcher = replay
        recorded_at = replay.manifest.recorded_at

        def clock() -> datetime:
            return recorded_at

        mode = DataMode.SYNTHETIC if replay.manifest.synthetic else DataMode.REPLAY
    else:
        fetcher = live_fetch
        if args.record:
            recorder = RecordingFetcher(live_fetch, args.record)
            fetcher = recorder

        def clock() -> datetime:
            return datetime.now(UTC)

        mode = DataMode.LIVE

    registry = CityRegistry.from_directory(args.cities)
    selected = [city for city in registry.cities if not args.only or city.id in args.only]
    unknown = set(args.only) - {city.id for city in registry.cities}
    if unknown:
        parser.error(f"unknown city id(s): {', '.join(sorted(unknown))}")

    args.out.mkdir(parents=True, exist_ok=True)
    snapshots: list[TwinSnapshot] = []
    for city in selected:
        if city.area is None:
            print(f"skip {city.id}: no area declared", file=sys.stderr)
            continue
        bindings = area_bindings(args.cities / city.id, fetcher=fetcher, clock=clock)
        previous = load_previous(args.previous, city.id) if args.previous else None
        twin = build_city_snapshot(city, bindings, clock=clock, data_mode=mode, previous=previous)
        snapshots.append(twin)
        (args.out / f"{city.id}.json").write_text(twin.model_dump_json(), encoding="utf-8")
        (args.out / f"{city.id}.ttl").write_text(
            project_snapshot(twin).serialize(format="turtle"), encoding="utf-8"
        )
        summary = ", ".join(
            f"{layer.capability_id}={layer.availability}({layer.entity_count})"
            for layer in twin.layers
        )
        carried = sum(layer.carried_over for layer in twin.layers)
        note = f"; {carried} carried over" if carried else ""
        print(f"{city.id}: {len(twin.entities)} entities; {summary}{note}", file=sys.stderr)

    index = build_index(snapshots, generated_at=clock(), data_mode=mode)
    (args.out / "index.json").write_text(index.model_dump_json(indent=2), encoding="utf-8")
    if recorder is not None:
        recorder.write_manifest(index.generated_at)
    return 0


def load_previous(directory: Path, city_id: str) -> TwinSnapshot | None:
    """Earlier snapshot of a city, or None when missing or unreadable."""

    path = directory / f"{city_id}.json"
    if not path.is_file():
        return None
    try:
        return TwinSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"ignore previous snapshot {path}: {type(exc).__name__}", file=sys.stderr)
        return None


if __name__ == "__main__":
    raise SystemExit(main())
