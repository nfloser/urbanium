"""Write a synthetic recording for offline development of the Twin Explorer.

Every response is invented example data in the real upstream formats. The
manifest is marked `synthetic`, snapshots built from it carry
`data_mode: synthetic`, and the explorer labels them as example data.

    python demo/sample_recording.py /tmp/urbanium-sample
    urbanium-twin build --replay /tmp/urbanium-sample --out demo/explorer/data
"""

import argparse
import json
import math
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from urbanium.providers.dwd.air_temperature import DWD_NOW_BASE_URL
from urbanium.providers.dwd.discovery import DWD_NOW_STATION_LIST_URL
from urbanium.providers.pegelonline.water_level import PEGELONLINE_BASE_URL
from urbanium.registry import CityRegistry
from urbanium.twin.bindings import area_bindings
from urbanium.twin.fetching import RecordingFetcher
from urbanium.twin.snapshot import DataMode, build_city_snapshot

RECORDED_AT = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
STATE = {
    "berlin": "Berlin",
    "mainz": "Rheinland-Pfalz",
    "hamburg": "Hamburg",
    "koeln": "Nordrhein-Westfalen",
}

# (city, offset within area as fractions, name, base temperature)
STATIONS = {
    "berlin": [
        (0.50, 0.48, "Beispielstation Mitte", 4.6),
        (0.32, 0.30, "Beispielstation Südwest", 3.1),
        (0.78, 0.33, "Beispielstation Nord", 3.4),
        (0.62, 0.80, "Beispielstation Ost", 3.0),
        (0.18, 0.62, "Beispielstation Süd", 2.6),
        (0.55, 0.12, "Beispielstation West", 3.3),
    ],
    # Fractions outside 0..1 place a station in the surroundings ring.
    "mainz": [
        (0.35, 0.40, "Beispielstation Mainz", 6.1),
        (1.35, 0.20, "Beispielstation Umland Nord", 5.4),
        (-0.40, 0.75, "Beispielstation Umland Süd", 6.6),
    ],
    "hamburg": [
        (0.52, 0.45, "Beispielstation Hafen", 6.4),
        (0.80, 0.55, "Beispielstation Nord", 5.2),
        (0.30, 0.70, "Beispielstation Ost", 5.6),
        (0.40, 0.20, "Beispielstation West", 5.9),
    ],
    "koeln": [
        (0.50, 0.50, "Beispielstation Innenstadt", 7.3),
        (0.25, 0.75, "Beispielstation Südost", 6.2),
        (0.75, 0.30, "Beispielstation Nordwest", 6.5),
    ],
}
BERLIN_GAUGES = [
    ("BERLIN-MÜHLENDAMM OP", 52.514460, 13.411460, "SPREE-ODER-WASSERSTRASSE", 337, 3),
    ("BERLIN-MÜHLENDAMM UP", 52.514897, 13.408690, "SPREE-ODER-WASSERSTRASSE", 192, 2),
    ("BERLIN-OBERSCHLEUSE UP", 52.497408, 13.448833, "LANDWEHRKANAL", 184, -1),
    ("BERLIN-OBERSCHLEUSE OP", 52.498278, 13.449730, "LANDWEHRKANAL", 340, 4),
    ("BERLIN-UNTERSCHLEUSE OP", 52.511402, 13.336519, "LANDWEHRKANAL", 205, 1),
    ("BERLIN-UNTERSCHLEUSE UP", 52.511608, 13.335037, "LANDWEHRKANAL", 158, 0),
    ("BERLIN-PLÖTZENSEE UP", 52.543036, 13.323859, "BERLIN-SPANDAUER-SCHIFFFAHRTSKANAL", 211, -2),
    ("BERLIN-PLÖTZENSEE OP", 52.543700, 13.323142, "BERLIN-SPANDAUER-SCHIFFFAHRTSKANAL", 254, 1),
    ("BERLIN-CHARLOTTENBURG OP", 52.531423, 13.292224, "SPREE-ODER-WASSERSTRASSE", 214, 0),
    ("BERLIN-CHARLOTTENBURG UP", 52.530037, 13.282545, "SPREE-ODER-WASSERSTRASSE", 174, -6),
    ("BERLIN-KÖPENICK", 52.429690, 13.573986, "SPREE-ODER-WASSERSTRASSE", 222, 7),
    ("BERLIN-SPANDAU UP", 52.540064, 13.209346, "HAVEL-ODER-WASSERSTRASSE", 239, -9),
    ("BERLIN-SPANDAU OP", 52.541856, 13.209042, "HAVEL-ODER-WASSERSTRASSE", 268, -2),
    ("KLEINMACHNOW OP", 52.395689, 13.209949, "TELTOWKANAL", 312, 1),
    ("KLEINMACHNOW UP", 52.395529, 13.207976, "TELTOWKANAL", 241, 0),
    ("BERLIN-SCHMÖCKWITZ", 52.374398, 13.653581, "DAHME-WASSERSTRASSE", 181, 2),
    ("WERNSDORF UP", 52.372628, 13.707554, "SPREE-ODER-WASSERSTRASSE", 202, 3),
    ("WERNSDORF OP", 52.371176, 13.711208, "SPREE-ODER-WASSERSTRASSE", 361, 1),
    ("SCHÖNWALDE OP", 52.607862, 13.088864, "HAVELKANAL", 296, 0),
]

# (city, offset, name, water, base level cm, change over 24 h cm)
GAUGES: dict[str, object] = {
    # Berlin uses the published gauge positions (PEGELONLINE reference data,
    # DL-DE->Zero-2.0) so the explorer is tested at real density. Levels stay invented.
    "berlin": "real_positions",
    "mainz": [(0.62, 0.66, "BEISPIELPEGEL RHEIN", "RHEIN", 296, 22)],
    "hamburg": [
        (0.50, 0.42, "BEISPIELPEGEL ELBE HAFEN", "ELBE", 520, 140),
        (0.40, 0.75, "BEISPIELPEGEL ELBE OST", "ELBE", 480, 120),
    ],
    "koeln": [
        (0.50, 0.55, "BEISPIELPEGEL RHEIN INNENSTADT", "RHEIN", 344, 31),
        (0.20, 0.62, "BEISPIELPEGEL RHEIN SÜD", "RHEIN", 368, 28),
    ],
}


def synthetic_upstream(registry: CityRegistry):  # type: ignore[no-untyped-def]
    inventory = [
        "Stations_id von_datum bis_datum Stationshoehe geoBreite geoLaenge "
        "Stationsname Bundesland Abgabe",
        "----------- --------- --------- ------------- --------- --------- "
        "----------------------------------------- ---------- ------",
    ]
    archives: dict[str, bytes] = {}
    stations_json: dict[str, list[dict[str, object]]] = {}
    series: dict[str, bytes] = {}
    number = 90000
    for city_index, city in enumerate(registry.cities):
        area = city.area
        assert area is not None
        for station_index, (fy, fx, name, base) in enumerate(STATIONS.get(city.id, [])):
            number += 1
            sid = f"{number:05d}"
            lat = area.south + fy * (area.north - area.south)
            lon = area.west + fx * (area.east - area.west)
            inventory.append(
                f"{sid} 19900101 20261122 {30 + station_index * 7} {lat:.4f} {lon:.4f} "
                f"{name} {STATE[city.id]} Frei"
            )
            archives[sid] = _archive(sid, base, phase=station_index * 0.7)
        stations_json[city.id] = []
        gauges = GAUGES.get(city.id, [])
        if gauges == "real_positions":
            gauges = [
                (
                    (lat - area.south) / (area.north - area.south),
                    (lon - area.west) / (area.east - area.west),
                    name,
                    water,
                    level,
                    change,
                )
                for name, lat, lon, water, level, change in BERLIN_GAUGES
            ]
        for gauge_index, (fy, fx, name, water, level, change) in enumerate(gauges):
            uuid = f"{city_index:08x}-0000-4000-8000-{gauge_index:012x}"
            stations_json[city.id].append(
                {
                    "uuid": uuid,
                    "number": f"{9000000 + city_index * 100 + gauge_index}",
                    "shortname": name[:40],
                    "longname": name,
                    "agency": "BEISPIEL",
                    "km": 10.0 + gauge_index * 3.5,
                    "latitude": round(area.south + fy * (area.north - area.south), 6),
                    "longitude": round(area.west + fx * (area.east - area.west), 6),
                    "water": {"shortname": water, "longname": water},
                    "timeseries": [
                        {
                            "shortname": "W",
                            "longname": "WASSERSTAND ROHDATEN",
                            "unit": "cm",
                            "gaugeZero": {"unit": "m. ü. NHN", "value": 30.0 + gauge_index},
                            "characteristicValues": _characteristic(
                                city.id, level, gauge_index, name
                            ),
                        }
                    ],
                }
            )
            tidal = city.id == "hamburg"
            series[uuid] = _measurements(level, change, tidal=tidal)

    inventory_bytes = ("\n".join(inventory) + "\n").encode("latin-1")
    vbb_feed, gtfs_zip = _vbb_examples()

    def fetch(url: str, timeout: float) -> bytes:
        if url == DWD_NOW_STATION_LIST_URL:
            return inventory_bytes
        if url.startswith("https://production.gtfsrt.vbb.de/"):
            return vbb_feed
        if url.startswith("https://unternehmen.vbb.de/"):
            return gtfs_zip
        if url.startswith(DWD_NOW_BASE_URL):
            return archives[url.rsplit("_TU_", 1)[1][:5]]
        if url.startswith(f"{PEGELONLINE_BASE_URL}/stations.json"):
            for city in registry.cities:
                assert city.area is not None
                if f"latitude={city.area.center.latitude:.5f}" in url:
                    return json.dumps(stations_json[city.id]).encode("utf-8")
            return b"[]"
        uuid = url.split("/stations/", 1)[1].split("/", 1)[0]
        return series[uuid]

    return fetch


def _characteristic(
    city_id: str, level: int, index: int, name: str = ""
) -> list[dict[str, object]]:
    """Invented long-term values; Hamburg's tidal gauges publish none here."""

    if city_id == "hamburg" or index % 4 == 3:
        return []
    if name == "BERLIN-MÜHLENDAMM OP":
        # Above its mean high water, next to a stop named in an invented alert.
        return [
            {"shortname": "MNW", "unit": "cm", "value": level - 70},
            {"shortname": "MW", "unit": "cm", "value": level - 40},
            {"shortname": "MHW", "unit": "cm", "value": level - 5},
        ]
    # Mainz' Rhine gauge sits above its mean high water to show that case.
    shift = 60 if city_id == "mainz" else 0
    return [
        {"shortname": "MNW", "unit": "cm", "value": level - 45 - shift},
        {"shortname": "MW", "unit": "cm", "value": level - 10 - shift},
        {"shortname": "MHW", "unit": "cm", "value": level + 30 - shift},
    ]


def _vbb_examples() -> tuple[bytes, bytes]:
    """Invented alerts and stops in the real GTFS-Realtime and GTFS formats."""

    from google.transit import gtfs_realtime_pb2

    stops = [
        ("ex:1001", "Beispielhaltestelle Mühlendamm", 52.5162, 13.4131),
        ("ex:1002", "Beispielhaltestelle Charlottenburg", 52.5262, 13.2952),
        ("ex:1003", "Beispielhaltestelle Köpenick", 52.4448, 13.5754),
    ]
    alerts = [
        ("ex-alert-1", "Beispiel: Ersatzverkehr wegen Bauarbeiten", ["ex:1001"]),
        ("ex-alert-2", "Beispiel: Aufzug außer Betrieb", ["ex:1002", "ex:9999"]),
        ("ex-alert-3", "Beispiel: Haltestelle verlegt", ["ex:1003"]),
    ]
    message = gtfs_realtime_pb2.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    message.header.timestamp = int((RECORDED_AT - timedelta(minutes=1)).timestamp())
    for alert_id, text, stop_ids in alerts:
        entity = message.entity.add()
        entity.id = alert_id
        for stop_id in stop_ids:
            entity.alert.informed_entity.add().stop_id = stop_id
        translation = entity.alert.header_text.translation.add()
        translation.text = text
        translation.language = "de"
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as target:
        target.writestr(
            "stops.txt",
            "stop_id,stop_name,stop_lat,stop_lon\n"
            + "".join(f"{sid},{name},{lat},{lon}\n" for sid, name, lat, lon in stops),
        )
    return message.SerializeToString(), buffer.getvalue()


def _archive(sid: str, base: float, *, phase: float) -> bytes:
    rows = ["STATIONS_ID;MESS_DATUM;  QN;PP_10;TT_10;TM5_10;RF_10;TD_10;eor"]
    for step in range(9 * 6, 0, -1):  # since midnight, every 10 minutes
        moment = RECORDED_AT - timedelta(minutes=10 * step)
        hours = (moment - RECORDED_AT.replace(hour=0)).total_seconds() / 3600
        value = base + 1.6 * math.sin((hours - 9 + phase) / 24 * 2 * math.pi) + 0.05 * (step % 3)
        rows.append(f"{sid};{moment:%Y%m%d%H%M};3;1012.0;{value:.1f};-999;86.0;1.5;eor")
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as target:
        target.writestr(
            f"produkt_zehn_now_tu_{RECORDED_AT:%Y%m%d}_{RECORDED_AT:%Y%m%d}_{sid}.txt",
            "\n".join(rows) + "\n",
        )
    return buffer.getvalue()


def _measurements(level: int, change: int, *, tidal: bool) -> bytes:
    rows = []
    for step in range(96, 0, -1):  # 24 h every 15 minutes
        moment = RECORDED_AT - timedelta(minutes=15 * step)
        progress = (96 - step) / 95
        value = level - change + change * progress
        if tidal:
            value += 160 * math.sin(step / 49.7 * 2 * math.pi)
        rows.append({"timestamp": moment.isoformat(), "value": round(value)})
    return json.dumps(rows).encode("utf-8")


def _write_archive(root: Path, twin) -> None:  # type: ignore[no-untyped-def]
    """Invented hourly values for the 29 days before the recording."""

    directory = root / twin.city.id
    directory.mkdir(parents=True, exist_ok=True)
    files: dict[str, list[str]] = {}
    for entity in twin.entities:
        if entity.latest is None:
            continue
        base = float(entity.latest.value)
        temperature = entity.latest.quantity_id == "air_temperature"
        for hour in range(24 * 29, 24, -1):
            moment = RECORDED_AT - timedelta(hours=hour)
            day = hour / 24
            if temperature:
                value = (
                    base
                    + 3 * math.sin(day / 5)
                    + 2.5 * math.sin((moment.hour - 9) / 24 * 2 * math.pi)
                )
                text = f"{value:.1f}"
            else:
                value = base + 25 * math.sin(day / 7) - day * 0.8
                text = f"{round(value)}"
            files.setdefault(moment.strftime("%Y-%m"), []).append(
                f"{entity.id},{entity.latest.quantity_id},{moment:%Y-%m-%dT%H:%M:%SZ},{text},{entity.latest.unit}"
            )
    for month, lines in files.items():
        (directory / f"{month}.csv").write_text(
            "entity,quantity,observed_at,value,unit\n" + "\n".join(lines) + "\n", encoding="utf-8"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cities", type=Path, default=Path("cities"))
    parser.add_argument(
        "--archive", type=Path, help="also write 29 days of invented hourly history"
    )
    args = parser.parse_args()
    registry = CityRegistry.from_directory(args.cities)
    recorder = RecordingFetcher(synthetic_upstream(registry), args.output)
    for city in registry.cities:
        if city.area is None:
            continue
        bindings = area_bindings(args.cities / city.id, fetcher=recorder, clock=lambda: RECORDED_AT)
        twin = build_city_snapshot(
            city, bindings, clock=lambda: RECORDED_AT, data_mode=DataMode.SYNTHETIC
        )
        if args.archive:
            _write_archive(args.archive, twin)
    manifest = recorder.write_manifest(RECORDED_AT).model_copy(
        update={"synthetic": True, "note": "Invented example data for offline development."}
    )
    (args.output / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
