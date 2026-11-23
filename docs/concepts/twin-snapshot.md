# Twin snapshot

`urbanium.twin` builds a versioned read model of one city: `urbanium.twin-snapshot/1`. It is the contract between the platform and static clients such as the [Twin Explorer](../../demo/README.md).

## Build

~~~bash
urbanium-twin build --out _site/data                 # live sources
urbanium-twin build --out _site/data --record rec/   # live, keep every response
urbanium-twin build --out _site/data --replay rec/   # reproducible, offline
~~~

Each city with an `area` gets `<id>.json` and `<id>.ttl`; `index.json` summarises all cities. Cities without an area are skipped with a message.

## Pipeline per city

1. For every area binding (`dwd_air_temperature_area.yaml`, `pegelonline.yaml`): discover entities, validate them against the city, read measurements through the provider, validate the read.
2. Sample the completion time once, after all upstream responses.
3. Build layers (discovery and read outcome per binding, plus a `summary` of observations about the source as a whole, such as how many alerts the VBB feed carries) and entities (sourced location, attributes, evidence, latest value, recent series, per-entity freshness).
4. Derive [relations](agents.md#relationships) and run every [agent](agents.md). Agents that do not resolve for the city keep their resolution reasons; agents whose capability had no read are marked as skipped with a reason.

Nothing is filled in: an unavailable discovery yields no entities, a station without values stays in the snapshot with `freshness: no_data`, and an agent without the evidence it needs reports why.

## Observation archive

`--history DIR` appends this run's full-hour values to an append-only archive (`DIR/<city>/<YYYY-MM>.csv` with `entity, quantity, observed_at, value, unit`) and attaches `daily` summaries for the last 30 local days to every entity: minimum, maximum, mean and count per day in the city's time zone. Carried-over values are never archived again.

On GitHub the archive lives on the `data` branch. The Pages build job only reads it and hands the updated files to a separate `archive` job, which runs on `main` only and is the only job with write access. Builds on `main` are serialised so archive commits cannot overwrite each other. One value per hour keeps the archive at a few tens of megabytes per year for the four reference cities.

The explorer offers "24 Stunden" and "30 Tage" in the detail panel once two or more days exist, and labels the long view as coming from the site's own archive rather than from the source.

## Last known values

`--previous DIR` passes earlier snapshots (`DIR/<city>.json`) to the build. The published site uses the snapshots it served before. When this run gets nothing for a layer (discovery failed) or for a single entity (no values), the build keeps the earlier values under these rules:

- only from a snapshot of the same city and the same data mode, so example or replayed data never enters a live snapshot;
- only values measured at most 48 hours ago (`CARRY_WINDOW`), so a long outage still ends up empty;
- every kept entity has `freshness: last_known` and `carried_over_from` (the snapshot it came from; unchanged when carried again), and its layer counts them in `carried_over`;
- relations of carried entities come along; agents never compute on carried values, because they describe a run that did not happen.

The explorer shows such values dashed and in italics, and says in the detail panel where they come from.

## Data modes

| Mode | Meaning |
|---|---|
| `live` | Responses were fetched from the sources during the build. |
| `replay` | Responses come from a recording of real sources (`--record`). The snapshot time is the recording time. |
| `synthetic` | The recording is marked as hand-made example data. Clients must label it prominently. |

Replay serves only recorded URLs. Anything else fails like an unreachable upstream, so a replay cannot invent responses.

## RDF projection

`project_snapshot` extends the validated relationship projection with `rdfs:label`, `geo:hasGeometry`/`geo:asWKT` points and one `sosa:Observation` per entity's latest value (`sosa:hasSimpleResult`, `sosa:resultTime`).
