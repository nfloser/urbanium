"""Synthetic upstream responses for twin tests.

Everything here is illustrative test data in the real upstream formats. It is
not real station metadata and not real measurements.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from urbanium.providers.dwd.air_temperature import DWD_NOW_BASE_URL
from urbanium.providers.dwd.discovery import DWD_NOW_STATION_LIST_URL
from urbanium.providers.pegelonline.water_level import PEGELONLINE_BASE_URL

VBB_RT_URL = "https://production.gtfsrt.vbb.de/data"
VBB_STATIC_PREFIX = "https://unternehmen.vbb.de/"
# Stop ids and positions are invented; one stop lies near gauge 580001.
STATIC_STOPS = [
    ("900100003", "Beispielhaltestelle Spree", 52.512, 13.415),
    ("900200005", "Beispielhaltestelle Süd", 52.45, 13.30),
]
ALERTS = [
    ("alert-a", "Ersatzverkehr Beispiellinie", ["900100003", "unknown:1"]),
    ("alert-b", "Aufzug außer Betrieb", ["900200005"]),
]


def vbb_feed(*, at: datetime | None = None) -> bytes:
    from google.transit import gtfs_realtime_pb2

    message = gtfs_realtime_pb2.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    message.header.timestamp = int(((at or NOW) - timedelta(minutes=1)).timestamp())
    for alert_id, text, stops in ALERTS:
        entity = message.entity.add()
        entity.id = alert_id
        for stop in stops:
            entity.alert.informed_entity.add().stop_id = stop
        translation = entity.alert.header_text.translation.add()
        translation.text = text
        translation.language = "de"
    return message.SerializeToString()


def gtfs_zip() -> bytes:
    rows = ["stop_id,stop_name,stop_lat,stop_lon"] + [
        f"{sid},{name},{lat},{lon}" for sid, name, lat, lon in STATIC_STOPS
    ]
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as target:
        target.writestr("stops.txt", "\n".join(rows) + "\n")
    return buffer.getvalue()


NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
INVENTORY_HEADER = (
    "Stations_id von_datum bis_datum Stationshoehe geoBreite geoLaenge "
    "Stationsname Bundesland Abgabe\n"
    "----------- --------- --------- ------------- --------- --------- "
    "----------------------------------------- ---------- ------\n"
)


def dwd_archive(station_id: str, values: list[float], *, end: datetime = NOW) -> bytes:
    """A `now` archive with one value every 10 minutes ending 10 minutes before `end`."""

    rows = ["STATIONS_ID;MESS_DATUM;  QN;PP_10;TT_10;TM5_10;RF_10;TD_10;eor"]
    last = end.replace(minute=end.minute - end.minute % 10) - timedelta(minutes=10)
    for index, value in enumerate(values):
        moment = last - timedelta(minutes=10 * (len(values) - 1 - index))
        rows.append(f"{station_id};{moment:%Y%m%d%H%M};3;1010.0;{value:.1f};-999;80.0;1.0;eor")
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as target:
        target.writestr(
            f"produkt_zehn_now_tu_{end:%Y%m%d}_{end:%Y%m%d}_{station_id}.txt",
            "\n".join(rows) + "\n",
        )
    return buffer.getvalue()


def gauge(
    uuid: str, number: str, name: str, lat: float, lon: float, water: str
) -> dict[str, object]:
    return {
        "uuid": uuid,
        "number": number,
        "shortname": name[:40],
        "longname": name,
        "agency": "EXAMPLE",
        "latitude": lat,
        "longitude": lon,
        "water": {"shortname": water, "longname": water},
        "timeseries": [{"shortname": "W", "longname": "WASSERSTAND ROHDATEN", "unit": "cm"}],
    }


def measurements(values: list[float], *, end: datetime = NOW) -> bytes:
    last = end.replace(minute=end.minute - end.minute % 15) - timedelta(minutes=15)
    rows = [
        {
            "timestamp": (last - timedelta(minutes=15 * (len(values) - 1 - i))).isoformat(),
            "value": value,
        }
        for i, value in enumerate(values)
    ]
    return json.dumps(rows).encode("utf-8")


BERLIN_STATIONS = [
    ("10001", 52.52, 13.40, "Beispielstation Mitte", [3.0, 3.2, 3.4]),
    ("10002", 52.45, 13.30, "Beispielstation Sued", [2.0, 2.2, 2.6]),
    ("10003", 52.56, 13.31, "Beispielstation Nord", [2.5, 2.7, 2.9]),
]
MAINZ_STATIONS = [("20001", 49.97, 8.21, "Beispielstation Mainz", [5.0, 5.1, 5.3])]
BERLIN_GAUGES = [
    (
        "11111111-1111-4111-8111-111111111111",
        "580001",
        "BEISPIELPEGEL SPREE",
        52.51,
        13.41,
        "SPREE",
    ),
    (
        "22222222-2222-4222-8222-222222222222",
        "580002",
        "BEISPIELPEGEL HAVEL",
        52.54,
        13.21,
        "HAVEL",
    ),
]


def upstream(
    *,
    broken: set[str] | None = None,
) -> Callable[[str, float], bytes]:
    """Route upstream URLs to synthetic responses; `broken` URL fragments raise OSError."""

    broken = broken or set()
    inventory = INVENTORY_HEADER + "".join(
        f"{sid} 19900101 20261122 40 {lat:.4f} {lon:.4f} {name} Berlin Frei\n"
        for sid, lat, lon, name, _ in BERLIN_STATIONS + MAINZ_STATIONS
    )
    archives = {
        sid: dwd_archive(sid, values) for sid, _, _, _, values in BERLIN_STATIONS + MAINZ_STATIONS
    }
    stations = json.dumps([gauge(*item) for item in BERLIN_GAUGES]).encode("utf-8")
    series = {
        BERLIN_GAUGES[0][0]: measurements([300.0] * 20 + [301.0, 305.0, 309.0, 312.0, 314.0]),
        BERLIN_GAUGES[1][0]: measurements([220.0] * 25),
    }

    def fetch(url: str, timeout: float) -> bytes:
        if any(fragment in url for fragment in broken):
            raise OSError("synthetic outage")
        if url == VBB_RT_URL:
            return vbb_feed()
        if url.startswith(VBB_STATIC_PREFIX):
            return gtfs_zip()
        if url == DWD_NOW_STATION_LIST_URL:
            return inventory.encode("latin-1")
        if url.startswith(DWD_NOW_BASE_URL):
            sid = url.rsplit("_TU_", 1)[1][:5]
            if sid in archives:
                return archives[sid]
            raise OSError("404")
        if url.startswith(f"{PEGELONLINE_BASE_URL}/stations.json"):
            return stations if "latitude=52" in url else b"[]"
        if url.startswith(f"{PEGELONLINE_BASE_URL}/stations/"):
            uuid = url.split("/stations/", 1)[1].split("/", 1)[0]
            return series[uuid]
        raise AssertionError(f"unexpected url {url}")

    return fetch
