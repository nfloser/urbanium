# PEGELONLINE water level

PEGELONLINE is the WSV's public service for gauges on German federal waterways. Urbanium uses it as a shared nationwide source: one adapter serves every city whose area contains federal waterway gauges.

- API: `https://www.pegelonline.wsv.de/webservices/rest-api/v2/` (no authentication)
- Licence: DL-DE->Zero-2.0 per the [PEGELONLINE terms](https://www.pegelonline.wsv.de/gast/nutzungsbedingungen); redistribution is permitted. Values are raw and unchecked, and WSV excludes liability for accuracy and timeliness.
- History: the API keeps measurements for the last 31 days.

## Configuration

`cities/<city>/providers/pegelonline.yaml`:

~~~yaml
schema_version: "1"
city_id: mainz
source_id: pegelonline
freshness_minutes: 60
history_hours: 24
max_gauges: 25
~~~

## Discovery

`PegelonlineGaugeDiscovery` queries `stations.json` around the area centre with a radius that covers every corner of the [area](../concepts/area-discovery.md), then keeps only stations that

- lie inside the area,
- have a well-formed `uuid` and numeric `number`,
- publish a `W` (water level) time series.

Entities are `river_gauge:pegelonline_<number>` with a `reference` location. Attributes carry uuid, number, water body, operating agency, river kilometre and gauge zero (metres above NHN) when published. Evidence is `stations.json:<uuid>:<sha256 of response>`.

## Measurements

`PegelonlineWaterLevelProvider` reads `stations/<uuid>/W/measurements.json?start=<window>` for each discovered gauge and normalizes every value to an observation with quantity `water_level` and unit `cm` (above gauge zero, not above sea level).

- Missing or non-numeric values and timestamps after receipt are skipped and counted.
- A gauge whose request fails or whose series is empty counts as a failed gauge.
- No observations at all: `unavailable`. Some failed gauges or skipped values: `degraded` with an explanatory error. Otherwise `available`.
- Freshness is `stale` as soon as one gauge's latest value is older than `freshness_minutes`.

The provider returns the whole recent series, not only the latest value, so trend components can work without a separate persistence layer.
