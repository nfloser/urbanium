# DWD CDC air-temperature adapter

Urbanium's first live provider adapter reads the Deutscher Wetterdienst (DWD) Climate Data Center `now` archives for 10-minute air-temperature observations. The product is updated at least hourly and has not completed final quality control. It is suitable for current state, not silently interchangeable with the quality-controlled historical product.

## Deployment bindings

The adapter is provider-specific and reusable. Station selection stays in city deployment configuration:

| City | Station | DWD station ID | Configuration |
|---|---|---:|---|
| Berlin | Berlin-Tempelhof | `00433` | `cities/berlin/providers/dwd_air_temperature.yaml` |
| Mainz | Mainz-Lerchenberg (ZDF) | `03137` | `cities/mainz/providers/dwd_air_temperature.yaml` |

Changing or adding a city does not require a core-code change. A deployment supplies a five-digit station ID, source binding and freshness threshold. The adapter constructs only the fixed DWD CDC endpoint and imposes compressed and extracted size limits.

## Normalization

Only the latest valid `TT_10` record is emitted in this slice. It maps to canonical quantity `air_temperature` and UCUM unit `Cel`. `MESS_DATUM` is interpreted as UTC, while `QN` is preserved without reinterpretation as quality scheme `dwd_qn` and its original code. The DWD station becomes a typed `weather_station` [entity reference](../concepts/entities-and-relationships.md), and the configured city/source/capability binding supplies provenance.

Missing values (`-999`) are omitted. A mixture of valid and malformed records yields a `degraded` result with the latest valid observation. A malformed archive with no valid records is `unavailable`. Network errors and timeouts become typed provider results rather than platform exceptions. Freshness is assessed separately from availability.

## Tests and operation

Deterministic CI builds in-memory ZIP archives from source-format CSV fixtures and applies the shared provider contract to success, partial-failure and outage cases. It performs no network access.

An optional smoke test checks the current Berlin and Mainz archives:

```bash
URBANIUM_LIVE_DWD=1 pytest tests/live/test_dwd_air_temperature_live.py
```

Provider availability can change independently of the platform. The smoke test is therefore intentionally excluded from correctness CI.

## Source and licence

The selected dataset is DWD's “10-minute station observations of air temperature for Germany” (`urn:x-wmo:md:de.dwd.cdc::obsgermany-climate-10min-air_temperature`). Its dataset description specifies UTC timestamps for `now`, the relevant columns and units, incomplete quality control, update cadence and CC BY 4.0. Dataset attribution and licence notices must be retained when observations are redistributed.
