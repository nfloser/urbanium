# VBB Alert stop ID lookup using GTFS static stops.txt

GTFS-Realtime Alert selectors sometimes explicitly name a `stop_id`.
Urbanium can now compare those **raw identifiers** with a caller-supplied
GTFS static `stops.txt` inventory and return source-backed WGS84 point
assertions where coordinates exist. The lookup does not interpret the
rest of an Alert selector or assert that a stop is disrupted.

The inventory reader is deliberately offline: it does not download a
GTFS ZIP, select an upstream feed, infer the correct static version or
assume that static and realtime IDs share a namespace. A consumer must
obtain the original licensed dataset, record its actual retrieval time,
retain source bytes when reproducibility is required, and verify that
the static feed's publisher, coverage and ID version are compatible
with the GTFS-Realtime feed.

## Synthetic example

```python
from datetime import UTC, datetime

from urbanium.providers.vbb.gtfs_rt import VbbAlertStopReference
from urbanium.providers.vbb.static_stops import (
    VbbGtfsStaticStopConfig,
    VbbGtfsStaticStopInventory,
)

# Synthetic data only; not a published VBB stop position.
stops_txt = b"stop_id,stop_name,stop_lat,stop_lon\nexample:1,Example,52.5,13.4\n"
inventory = VbbGtfsStaticStopInventory(
    VbbGtfsStaticStopConfig(city_id="berlin", source_id="vbb_gtfs_static"),
    stops_txt=stops_txt,
    retrieved_at=datetime(2026, 10, 25, 13, tzinfo=UTC),
)
references = (
    VbbAlertStopReference(alert_id="example-alert", selector_index=0, stop_id="example:1"),
)
matches = inventory.resolve_alert_stop_references(references)
assert matches[0].reference == references[0]
assert matches[0].location is not None
```

For real provider reads, pass the
`VbbGtfsRtProvider.read_snapshot().stop_references` tuple to
`resolve_alert_stop_references()` **only after** checking that the
supplied static inventory belongs to the same compatible feed namespace.
All original Alert IDs, selector positions, ordering and repeated
references are retained. An unknown ID or an inventory record with
both coordinates missing produces `location=None`.

## Using a supplied GTFS ZIP release

A caller can supply the **original ZIP bytes** instead of manually
extracting `stops.txt`:

```python
from datetime import UTC, datetime
from pathlib import Path

from urbanium.providers.vbb.static_stops import (
    VbbGtfsStaticStopConfig,
    VbbGtfsStaticStopInventory,
)

# Obtain this file separately under the publisher's applicable terms.
archive_bytes = Path("licensed-gtfs-release.zip").read_bytes()
inventory = VbbGtfsStaticStopInventory.from_gtfs_zip(
    VbbGtfsStaticStopConfig(city_id="berlin", source_id="vbb_gtfs_static"),
    archive_bytes=archive_bytes,
    retrieved_at=datetime.now(UTC),  # record the actual acquisition time
)
print(inventory.archive_sha256)  # release fingerprint, not a version assertion
```

The reader opens the ZIP **in memory** and reads only the single
root-level `stops.txt`; it never extracts files to disk. It rejects
missing or duplicate root entries, invalid ZIPs, encrypted members,
unsupported compression, archives larger than **100 MB**, archives
with more than **128 members**, and `stops.txt` larger than **20 MB**
(including when compressed). It accepts stored and deflated ZIP members.
Other files in the archive are not parsed or semantically validated.

Resolved point evidence includes both the original `stops.txt`
SHA-256 and the entire ZIP SHA-256. This identifies the exact supplied
release bytes even when two releases have identical stop coordinates.
The direct `stops_txt=` constructor remains supported and retains its
existing record-ID format; its `archive_sha256` is `None`.

The digest alone does not establish the official release identity,
licence, effective dates or compatibility with a GTFS-Realtime feed.
Callers must record that metadata and check ID-namespace compatibility
before using stop references. An offline archive lookup cannot verify
that a realtime Alert actually affects the named stop.

## Parsing and provenance

The `stops.txt` parser accepts at most 20 MB of UTF-8 (optional BOM) CSV, including
quoted fields. It requires `stop_id`, `stop_lat` and `stop_lon`.
Duplicate IDs, missing required columns, malformed rows, invalid
`location_type`, partial coordinate pairs, nonfinite or out-of-range
coordinates, invalid encoding and oversized inputs raise
`VbbGtfsStaticStopError`. Parsing completes before any lookup can
return a point: invalid inventories do not yield partial results.

Resolved points use `EntityPointLocation` in the `reference` state,
with the configured city/source, a source retrieval timestamp and an
evidence record ID containing SHA-256 hashes of both the raw stop ID and
the complete `stops.txt` bytes (and the ZIP bytes when provided). Hashing the raw ID gives a stable
canonical entity ID even when the GTFS identifier contains punctuation.
The original ID remains on the corresponding `VbbAlertStopReference`.
The hash is a fingerprint, **not** a stored copy of the inventory or a
licence record. Consumers must retain source metadata and attribution
separately.

## What the result does not mean

A static stop point is not a stop catchment, service area, route
geometry or proof that a realtime Alert affects every service at the
stop. A selector may also specify a route or trip, which this lookup
does not evaluate. Exact matching of two IDs is only meaningful if
their feed namespaces are compatible. A nearby DWD weather-station
point does not establish overlapping measurement coverage, a
weather-related disruption or causality.

This is a bounded input to [the spatial evidence work](../concepts/spatial-evidence.md)
for [cross-domain issue #8](https://github.com/nfloser/urbanium/issues/8),
not a completed cross-domain impact demonstrator. The source catalogue
and current terms should be checked with the
[VBB datasets page](https://unternehmen.vbb.de/digitale-services/datensaetze/)
before using or redistributing any static GTFS files.

Deterministic tests use synthetic `stops.txt` and ZIP bytes. No static-feed
network request is made by the reader or by CI.
