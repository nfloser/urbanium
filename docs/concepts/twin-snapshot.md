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
3. Build layers (discovery and read outcome per binding) and entities (sourced location, attributes, evidence, latest value, recent series, per-entity freshness).
4. Derive [relations](agents.md#relationships) and run every [agent](agents.md). Agents that do not resolve for the city keep their resolution reasons; agents whose capability had no read are marked as skipped with a reason.

Nothing is filled in: an unavailable discovery yields no entities, a station without values stays in the snapshot with `freshness: no_data`, and an agent without the evidence it needs reports why.

## Data modes

| Mode | Meaning |
|---|---|
| `live` | Responses were fetched from the sources during the build. |
| `replay` | Responses come from a recording of real sources (`--record`). The snapshot time is the recording time. |
| `synthetic` | The recording is marked as hand-made example data. Clients must label it prominently. |

Replay serves only recorded URLs. Anything else fails like an unreachable upstream, so a replay cannot invent responses.

## RDF projection

`project_snapshot` extends the validated relationship projection with `rdfs:label`, `geo:hasGeometry`/`geo:asWKT` points and one `sosa:Observation` per entity's latest value (`sosa:hasSimpleResult`, `sosa:resultTime`).
