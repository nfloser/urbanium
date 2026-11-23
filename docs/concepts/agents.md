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
| `water_level_class@1` | `river_level@1` with reference context | `water_level_class@1` | Latest level per gauge against the gauge's own published long-term values: `below_mnw`, `mnw_to_mw`, `mw_to_mhw`, `above_mhw`. Gauges without all of MNW, MW and MHW are `no_reference`; with none at all the run is unavailable (`no_characteristic_values`). |
| `transit_near_high_water@1` | `realtime_transport@1` and `river_level@1`, both with reference context | `transit_near_high_water@1` | First cross-domain agent: for gauges whose latest level is above their own MHW, the stops named in current alerts within 1 km (great circle). The result flags spatial co-occurrence for a person to check; it does not claim that high water caused an alert or that a stop is affected. It resolves only where a city configures both capabilities (Berlin today); elsewhere the resolution says which capability is missing. |
| `water_level_trend@1` | `river_level@1` | `water_level_class@1` | `river_level@1` with reference context | `water_level_class@1` | Latest level per gauge against the gauge's own published long-term values: `below_mnw`, `mnw_to_mw`, `mw_to_mhw`, `above_mhw`. Gauges without all of MNW, MW and MHW are `no_reference`; with none at all the run is unavailable (`no_characteristic_values`). |
| `transit_near_high_water@1` | `realtime_transport@1` and `river_level@1`, both with reference context | `transit_near_high_water@1` | First cross-domain agent: for gauges whose latest level is above their own MHW, the stops named in current alerts within 1 km (great circle). The result flags spatial co-occurrence for a person to check; it does not claim that high water caused an alert or that a stop is affected. It resolves only where a city configures both capabilities (Berlin today); elsewhere the resolution says which capability is missing. |
| `water_level_trend@1` | Per gauge: latest value minus the measured value closest to 6 h earlier (accepted within ±45 min). `rising` ≥ +5 cm, `falling` ≤ −5 cm, otherwise `steady`. Without a reference value the trend is `unknown`. |

### Reference context

`observation_input(..., reference=entities)` adds the read's discovered entities with their attributes and evidence as `reference_entities`. This is sourced reference state (for example the characteristic values PEGELONLINE publishes per gauge), so agents can relate measurements to it without touching a provider. The class agent records the evidence of the values it used per gauge.

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
