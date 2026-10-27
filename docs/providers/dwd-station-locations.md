# DWD station inventory point locations

The DWD CDC publishes `zehn_min_tu_Beschreibung_Stationen.txt` alongside
its 10-minute air-temperature dataset. It reports the **latest geographic
position** of each station and its data-coverage dates. The DWD dataset
documentation identifies WGS84 (EPSG:4326) as the coordinate reference system.

`DwdCdcStationLocationProvider` reads this fixed upstream inventory and
selects the configured station ID from the existing Berlin or Mainz DWD
binding. It emits an `EntityPointLocation` in the `reference` state,
with the same typed station identity used by the temperature observation
adapter. No coordinates are stored in deployment configuration or invented
when metadata is missing.

## Use

```python
from pathlib import Path

from urbanium.providers.dwd.air_temperature import load_dwd_air_temperature_config
from urbanium.providers.dwd.station_location import DwdCdcStationLocationProvider

config = load_dwd_air_temperature_config(Path("cities/berlin/providers/dwd_air_temperature.yaml"))
location = DwdCdcStationLocationProvider(config).read()
if location is None:
    print("Station absent from DWD inventory")
else:
    print(location.point, location.evidence)
```

The adapter downloads at most 1 MB from the fixed DWD host with a 10-second
default timeout. It never accepts arbitrary URLs. Missing station IDs return
`None`; failed downloads, malformed station rows, duplicates, invalid
coordinates, invalid inventory headers and oversized responses raise
`DwdStationMetadataError`. Consumers must treat these failures as missing
evidence, **not** replace them with guessed positions.

The retrieval clock is sampled after the download. The source record ID
contains the inventory filename, station ID and SHA-256 digest of the fetched
inventory bytes, while the evidence carries the retrieval instant. This
supports reconstructing the source version *if the original bytes are
retained by the consuming system*; Urbanium does not persist the inventory
in this slice.

## Interpretation and limits

The inventory reports a station's latest listed point, not its historical
movement trajectory. Its `von_datum` and `bis_datum` fields describe
measurement coverage; they do not certify the period for which the current
coordinate was valid. The assertion timestamp is the time Urbanium read
the inventory, **not** a claim that the station moved then.

A point is not a weather observation footprint, an interpolation surface,
or a spatial join to VBB service alerts. A station's location alone cannot
establish weather-related traffic effects. The source list can change
independently of the observation archive and should be re-read or cached
with an explicit refresh policy by future orchestration.

Deterministic unit tests use synthetic inventory lines without network
access. An optional live smoke check can be run with:

```bash
URBANIUM_LIVE_DWD_STATIONS=1 pytest tests/live/test_dwd_station_location_live.py
```

## Source and attribution

- DWD CDC dataset: “10-minute station observations of air temperature for
  Germany”, dataset ID
  `urn:x-wmo:md:de.dwd.cdc::obsgermany-climate-10min-air_temperature`.
- Inventory:
  `https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/historical/zehn_min_tu_Beschreibung_Stationen.txt`.
- Dataset description:
  `https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/DESCRIPTION_obsgermany_climate_10min_air_temperature_en.pdf`.

DWD's dataset is distributed under CC BY 4.0; downstream redistribution
must preserve attribution and applicable licence notices.

An inventory containing only the header, separator or blank lines is rejected as
invalid metadata; it does not establish that the configured station is absent.
