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
    "mainz": [(0.35, 0.40, "Beispielstation Mainz", 6.1)],
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
# (city, offset, name, water, base level cm, change over 24 h cm)
GAUGES = {
    "berlin": [
        (0.52, 0.47, "BEISPIELPEGEL SPREE MITTE", "SPREE-ODER-WASSERSTRASSE", 312, 4),
        (0.58, 0.18, "BEISPIELPEGEL HAVEL", "UNTERE HAVEL-WASSERSTRASSE", 238, -9),
        (0.30, 0.75, "BEISPIELPEGEL DAHME", "DAHME-WASSERSTRASSE", 181, 1),
    ],
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
        for gauge_index, (fy, fx, name, water, level, change) in enumerate(GAUGES.get(city.id, [])):
            uuid = f"{city_index:08x}-0000-4000-8000-{gauge_index:012x}"
            stations_json[city.id].append(
                {
                    "uuid": uuid,
                    "number": f"{9000000 + city_index * 100 + gauge_index}",
                    "shortname": name[:40],
                    "longname": name,
                    "agency": "BEISPIEL",
                    "km": 10.0 + gauge_index * 3.5,
                    "latitude": round(area.south + fy * (area.north - area.south), 5),
                    "longitude": round(area.west + fx * (area.east - area.west), 5),
                    "water": {"shortname": water, "longname": water},
                    "timeseries": [
                        {
                            "shortname": "W",
                            "longname": "WASSERSTAND ROHDATEN",
                            "unit": "cm",
                            "gaugeZero": {"unit": "m. ü. NHN", "value": 30.0 + gauge_index},
                        }
                    ],
                }
            )
            tidal = city.id == "hamburg"
            series[uuid] = _measurements(level, change, tidal=tidal)

    inventory_bytes = ("\n".join(inventory) + "\n").encode("latin-1")

    def fetch(url: str, timeout: float) -> bytes:
        if url == DWD_NOW_STATION_LIST_URL:
            return inventory_bytes
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cities", type=Path, default=Path("cities"))
    args = parser.parse_args()
    registry = CityRegistry.from_directory(args.cities)
    recorder = RecordingFetcher(synthetic_upstream(registry), args.output)
    for city in registry.cities:
        if city.area is None:
            continue
        bindings = area_bindings(args.cities / city.id, fetcher=recorder, clock=lambda: RECORDED_AT)
        build_city_snapshot(city, bindings, clock=lambda: RECORDED_AT, data_mode=DataMode.SYNTHETIC)
    manifest = recorder.write_manifest(RECORDED_AT).model_copy(
        update={"synthetic": True, "note": "Invented example data for offline development."}
    )
    (args.output / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
