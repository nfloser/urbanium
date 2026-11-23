"""Hourly observations are archived and summarised per local day."""

import csv
from datetime import timedelta
from pathlib import Path

from tests.twin_fixtures import NOW, upstream
from urbanium.registry import CityRegistry
from urbanium.twin.bindings import area_bindings
from urbanium.twin.cli import main
from urbanium.twin.fetching import RecordingFetcher
from urbanium.twin.history import append_history, attach_history, daily_stats
from urbanium.twin.snapshot import DataMode, TwinSnapshot, build_city_snapshot

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = CityRegistry.from_directory(ROOT / "cities")


def snapshot(at=NOW, fetch=None) -> TwinSnapshot:  # type: ignore[no-untyped-def]
    city = REGISTRY.city("berlin")
    bindings = area_bindings(
        ROOT / "cities" / "berlin", fetcher=fetch or upstream(), clock=lambda: at
    )
    return build_city_snapshot(city, bindings, clock=lambda: at, data_mode=DataMode.LIVE)


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_only_full_hour_values_are_archived_once(tmp_path: Path) -> None:
    twin = snapshot()

    first = append_history(tmp_path, twin)
    second = append_history(tmp_path, twin)

    archived = rows(tmp_path / "berlin" / "2026-11.csv")
    assert first == len(archived) > 0
    assert second == 0
    assert all(row["observed_at"].endswith(":00:00Z") for row in archived)
    assert set(archived[0]) == {"entity", "quantity", "observed_at", "value", "unit"}


def test_carried_over_values_are_not_archived_again(tmp_path: Path) -> None:
    twin = snapshot()
    carried = twin.model_copy(
        update={
            "entities": [
                e.model_copy(update={"carried_over_from": NOW, "freshness": "last_known"})
                for e in twin.entities
            ]
        }
    )

    assert append_history(tmp_path, carried) == 0


def test_daily_statistics_use_the_city_day_and_the_last_thirty_days(tmp_path: Path) -> None:
    berlin = tmp_path / "berlin"
    berlin.mkdir()
    entity = "berlin:weather_station:dwd_station_10001"
    lines = ["entity,quantity,observed_at,value,unit"]
    # 23:00 UTC on Nov 21 is already Nov 22 in Berlin.
    lines += [
        f"{entity},air_temperature,2026-11-21T22:00:00Z,1.0,Cel",
        f"{entity},air_temperature,2026-11-21T23:00:00Z,5.0,Cel",
        f"{entity},air_temperature,2026-11-22T10:00:00Z,3.0,Cel",
        f"{entity},air_temperature,2026-10-01T10:00:00Z,9.0,Cel",
    ]
    (berlin / "2026-11.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (berlin / "2026-10.csv").write_text(lines[0] + "\n" + lines[-1] + "\n", encoding="utf-8")

    stats = daily_stats(tmp_path, snapshot())[entity]

    days = {str(item.day): item for item in stats}
    assert set(days) == {"2026-11-21", "2026-11-22"}
    assert (days["2026-11-21"].min, days["2026-11-21"].count) == ("1.0", 1)
    nov22 = days["2026-11-22"]
    assert (nov22.min, nov22.max, nov22.mean, nov22.count) == ("3.0", "5.0", "4.00", 2)


def test_attached_history_round_trips(tmp_path: Path) -> None:
    twin = snapshot()
    append_history(tmp_path, twin)

    enriched = attach_history(twin, daily_stats(tmp_path, twin))

    # The synthetic gauges report every 15 minutes, so they have full hours.
    station = next(e for e in enriched.entities if e.entity_id == "pegelonline_580001")
    assert station.daily and station.daily[-1].day == (NOW + timedelta(hours=1)).date()
    assert TwinSnapshot.model_validate_json(enriched.model_dump_json()) == enriched


def test_cli_archives_and_attaches_history(tmp_path: Path) -> None:
    recording = tmp_path / "recording"
    recorder = RecordingFetcher(upstream(), recording)
    snapshot(fetch=recorder)
    recorder.write_manifest(NOW)
    archive = tmp_path / "archive"

    assert (
        main(
            [
                "build",
                "--cities",
                str(ROOT / "cities"),
                "--out",
                str(tmp_path / "out"),
                "--replay",
                str(recording),
                "--only",
                "berlin",
                "--history",
                str(archive),
            ]
        )
        == 0
    )

    assert (archive / "berlin" / "2026-11.csv").is_file()
    twin = TwinSnapshot.model_validate_json((tmp_path / "out" / "berlin.json").read_text("utf-8"))
    assert any(e.daily for e in twin.entities)
