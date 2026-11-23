# Agents: derived knowledge with provenance

Agents are Urbanium's reusable deterministic components (see [components](components.md)) that turn canonical city state into new, explicitly derived knowledge. They follow the same rules as every component:

- they declare exact capability inputs and versioned outputs;
- they resolve against a city through its capabilities, never by name;
- they read only canonical provider outcomes (`observation_input`), never provider APIs;
- they report `available`, `degraded` or `unavailable` with explicit problems.

An architecture test enforces that `urbanium.agents` imports no provider, API or city code.

## Shipped agents

| Agent | Input | Output | Rule |
|---|---|---|---|
| `temperature_spread@1` | `weather@1` | `temperature_spread@1` | Lowest, highest, spread and mean air temperature across stations that report **the same measurement time**. The newest time with at least 3 stations is used. Stations without a value at that time are listed in `not_aligned` and never interpolated. |
| `water_level_trend@1` | `river_level@1` | `water_level_trend@1` | Per gauge: latest value minus the measured value closest to 6 h earlier (accepted within ±45 min). `rising` ≥ +5 cm, `falling` ≤ −5 cm, otherwise `steady`. Without a reference value the trend is `unknown`. |

A degraded source makes the derived run degraded with a `source_degraded` problem that carries the source's own reason.

### Interpretation limits

- A temperature spread between stations also reflects elevation, surface and exposure. It is not on its own evidence of an urban heat island.
- Water levels are relative to the gauge zero and are raw, unchecked source values. Gauges on different waters are not comparable by absolute level.

## Relationships

`derive_relations` produces evidence-backed edges for the knowledge graph from discovered entities:

| Predicate | Subject → object | State | Evidence |
|---|---|---|---|
| `located_in` | any entity → `discovery_area` of the city | derived | the entity's location record |
| `on_water_body` | river gauge → `water_body` named by the source | reference | the gauge record |
| `nearest_weather_station` | river gauge → nearest weather station (great circle, with distance) | derived | both location records |

Nearest is a spatial fact, not a statement that the station represents the weather at the gauge. Relationships project into RDF through the existing [bounded projection](../ontology/rdf-projection.md); gauges and stations map to `sosa:Platform`, areas and water bodies to `geo:Feature`.
