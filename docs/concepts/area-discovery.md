# Area-based source discovery

A city deployment can declare an `area`: a WGS84 envelope (`south`, `west`, `north`, `east`) in which Urbanium looks for source entities such as weather stations or river gauges.

~~~yaml
area:
  south: 52.338
  west: 13.088
  north: 52.676
  east: 13.761
~~~

The area is a search envelope, not an administrative boundary. Being inside it does not make a point part of the city, and it does not imply that a source covers the surrounding space.

## Why discovery exists

Without discovery, every deployment had to name individual station ids by hand (for example one DWD station per city). That ties the data model to whoever wrote the YAML and does not scale to "any city that publishes the data".

With discovery, a nationwide source adapter asks its own inventory which entities lie inside the area. Adding a city that is covered by such a source is then a configuration task: define the area, declare the source and bind the adapter.

## Contract

`urbanium.core.discovery` defines the city-independent boundary:

- `DiscoveryResult` holds one run for one city source: `available` with zero or more `DiscoveredEntity` items, or `unavailable` with an explicit error and no entities.
- `DiscoveredEntity` carries an `EntityPointLocation` (state `reference`, with evidence pointing at the inventory record), a display label and simple typed attributes.
- `validate_discovery_result` rejects results for another city, sources that are not verified for the city, entities outside the declared area and entities whose evidence cites a different source.

An empty but available discovery is a valid finding: the inventory was read and contains nothing in the area. It is never replaced by a hand-picked fallback.

Discovery says that an entity is published. Whether it currently delivers measurements is decided by the measurement read and reported through the normal provider outcome.

## Adapters

- [DWD station discovery](../providers/dwd-station-discovery.md) — 10-minute air-temperature stations from the DWD inventory, read together as a station network.
- [PEGELONLINE water level](../providers/pegelonline-water-level.md) — federal waterway gauges.
