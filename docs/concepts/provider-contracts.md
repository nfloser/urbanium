# Numeric observation provider contracts

The first provider boundary covers **numeric observations** such as weather readings and river levels. It does not claim to model assets, geometry, commands or arbitrary provider payloads. Later record types can have distinct contracts while retaining the same source and capability boundaries.

`ObservationProvider` declares a descriptor and `read()` operation. A descriptor binds one adapter instance to a city, source and capability and records its adapter version. `validate_provider_descriptor()` checks this binding against the city registry, including configured capability and verified source status. An observation carries the same binding, an entity and quantity identifier, a decimal value and unit, plus separate observation and receipt times. Adapter implementations translate external schemas before returning `ProviderResult`. `validate_provider_result()` checks each observation against the adapter descriptor. Both validators are intended for adapter contract tests and the runtime boundary.

## Availability and freshness

Availability describes the **outcome of a read**; freshness describes the returned observations under the product's own documented cadence policy. They are independent: an available result can contain stale observations. The core does not assume a universal timeout or freshness threshold.

| Availability | Required result |
|---|---|
| `available` | At least one observation, no error |
| `degraded` | At least one observation and a typed error explaining partial failure |
| `unavailable` | No observations, a typed error, freshness `unknown` |

Errors have stable categories (`timeout`, `unauthorized`, `invalid_response`, `upstream`, `unknown`) and a diagnostic message. Callers must not infer a healthy live provider from static `configured` support in the [city registry](capabilities.md).

## Last known good

This contract returns only the current read outcome. A future state store may retain a last known good observation set with its original timestamps and provenance. If a subsequent read fails, the runtime must expose the failed read and cached state separately. It must not relabel cached observations as fresh or use them to turn an unavailable read into an available one.

## Contract test pattern

Each adapter test supplies a fixture-backed `ObservationProvider`, calls `read()` and passes its descriptor and result to `validate_provider_result()`. The shared validation rejects cross-city, cross-source and cross-capability records; model validation rejects impossible availability/error combinations and naive timestamps. Provider-specific tests must additionally verify schema mapping, units, entity identity, freshness policy and upstream error mapping. External-network smoke tests remain separate from deterministic CI.
