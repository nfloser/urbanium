"""One bounded HTTP entry point for the twin build, with record and replay.

Live mode dispatches each URL to the bounded fetcher of the adapter that owns
it. Recording stores every response next to a manifest. Replay serves only
recorded URLs; anything else fails like an unreachable upstream, so a replay
can never invent a response.
"""

import json
from collections.abc import Callable
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from urbanium.providers.dwd.air_temperature import DWD_NOW_BASE_URL, fetch_archive
from urbanium.providers.dwd.discovery import DWD_NOW_STATION_LIST_URL
from urbanium.providers.dwd.station_location import DWD_STATION_LIST_URL, fetch_station_inventory
from urbanium.providers.pegelonline.water_level import PEGELONLINE_BASE_URL, fetch_json_bytes
from urbanium.providers.vbb.alert_stops import fetch_gtfs_zip
from urbanium.providers.vbb.gtfs_rt import _fetch_bytes as fetch_vbb_feed

FetchBytes = Callable[[str, float], bytes]
VBB_RT_PREFIX = "https://production.gtfsrt.vbb.de/"
VBB_STATIC_PREFIX = (
    "https://unternehmen.vbb.de/fileadmin/user_upload/VBB/Dokumente/API-Datensaetze/"
)
MANIFEST = "manifest.json"


def live_fetch(url: str, timeout: float) -> bytes:
    """Route a URL to the size-limited fetcher of its adapter."""

    if url in (DWD_STATION_LIST_URL, DWD_NOW_STATION_LIST_URL):
        return fetch_station_inventory(url, timeout)
    if url.startswith(f"{DWD_NOW_BASE_URL}/"):
        return fetch_archive(url, timeout)
    if url.startswith(f"{PEGELONLINE_BASE_URL}/"):
        return fetch_json_bytes(url, timeout)
    if url.startswith(VBB_RT_PREFIX):
        return fetch_vbb_feed(url, timeout)
    if url.startswith(VBB_STATIC_PREFIX):
        return fetch_gtfs_zip(url, timeout)
    raise ValueError(f"no adapter owns {url}")


class RecordingManifest(BaseModel):
    """Index of a recording. `synthetic` marks hand-made example data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    recorded_at: datetime
    synthetic: bool = False
    note: str | None = None
    responses: dict[str, str]


class RecordingFetcher:
    """Pass requests through and keep every successful response."""

    def __init__(self, inner: FetchBytes, directory: Path) -> None:
        self._inner = inner
        self._directory = directory
        self._responses: dict[str, str] = {}
        directory.mkdir(parents=True, exist_ok=True)

    def __call__(self, url: str, timeout: float) -> bytes:
        payload = self._inner(url, timeout)
        name = sha256(url.encode("utf-8")).hexdigest()[:24] + ".bin"
        (self._directory / name).write_bytes(payload)
        self._responses[url] = name
        return payload

    def write_manifest(self, recorded_at: datetime) -> RecordingManifest:
        manifest = RecordingManifest(
            recorded_at=recorded_at, responses=dict(sorted(self._responses.items()))
        )
        (self._directory / MANIFEST).write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        return manifest


class ReplayFetcher:
    """Serve responses from a recording; unknown URLs behave like an outage."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self.manifest = RecordingManifest.model_validate(
            json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
        )

    def __call__(self, url: str, timeout: float) -> bytes:
        name = self.manifest.responses.get(url)
        if name is None:
            raise OSError(f"no recorded response for {url}")
        path = (self._directory / name).resolve()
        if path.parent != self._directory.resolve():
            raise OSError("recorded response escapes the recording directory")
        return path.read_bytes()
