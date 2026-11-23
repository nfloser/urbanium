# DWD station discovery

`urbanium.providers.dwd.discovery.DwdStationDiscovery` finds DWD CDC 10-minute air-temperature stations inside a city's [area](../concepts/area-discovery.md).

## Configuration

`cities/<city>/providers/dwd_air_temperature_area.yaml`:

~~~yaml
schema_version: "1"
city_id: berlin
source_id: dwd_open_data
freshness_minutes: 90
active_within_days: 7
max_stations: 30
~~~

The existing single-station binding (`dwd_air_temperature.yaml`) is unchanged and still serves the local dashboard and API.

## Behaviour

1. Read the inventory of the `now` archives, `10_minutes/air_temperature/now/zehn_now_tu_Beschreibung_Stationen.txt` (size-limited, same parser as [station locations](dwd-station-locations.md)). Unlike the historical inventory, its end dates are current, so closed stations drop out within days.
2. Parse each row. Malformed rows are skipped; they never produce a location.
3. Keep stations whose inventory end date lies within `active_within_days` (default 7) and whose coordinates are inside the area. The measurement read still decides whether a station delivers data in a given run.
4. Drop station ids that appear in more than one qualifying row, because the location would be ambiguous.
5. Order by distance to the area centre, then by id, and keep at most `max_stations`.

Every entity is `weather_station:dwd_station_<id>` with a `reference` location and evidence `zehn_now_tu_Beschreibung_Stationen.txt:<id>:<sha256 of inventory>`. Attributes carry the station id, elevation in metres, federal state where recognisable and the inventory end date.

Transport failures, oversize or unreadable inventories make the discovery `unavailable` with `timeout`, `upstream` or `invalid_response`.

## Reading the station network

`urbanium.providers.dwd.network.DwdAirTemperatureNetworkProvider` reads every discovered station through the unchanged single-station adapter and combines the results into one `weather` read for the city's `dwd_open_data` source:

- each station contributes its full `now` series (`DwdCdcAirTemperatureProvider.read_series()`), oldest first;
- a station without usable values counts as failed and is named in the degraded error, never filled in;
- partial rows inside a station keep the single-station diagnostics, prefixed with the station id;
- no usable station at all makes the network `unavailable`;
- freshness is `stale` as soon as one station's latest value is older than `freshness_minutes`.

`read()` of the single-station adapter still returns only the latest value, so the existing API and dashboard behave as before.
