# Numeric observation provider contracts

The first provider boundary covers **numeric observations** such as weather readings and river levels. It does not claim to model assets, geometry, commands or arbitrary provider payloads. Later record types can have distinct contracts while retaining the same source and capability boundaries.

`ObservationProvider` declares a descriptor and `read()` operation. A descriptor binds one adapter instance to a city, source and capability and records its adapter version. `validate_provider_descriptor()` checks this binding against the city registry, including configured capability and verified source status. An observation carries the same binding, a complete [entity reference](entities-and-relationships.md), a quantity identifier, a decimal value and unit, plus separate observation and receipt times. The entity and observation must belong to the same city. Adapter implementations translate external schemas before returning `ProviderResult`. `validate_provider_result()` checks each observation against the adapter descriptor. Both validators are intended for adapter contract tests and the runtime boundary.

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

Each adapter supplies three deterministic, fixture-backed instances to `ProviderContractCases`: one successful read, one partial/degraded read and one unavailable read. Its tests call `assert_provider_contract()` from `tests.contracts.provider`. The shared suite verifies that all cases use one descriptor, checks the binding against city configuration, requires the expected explicit outcome and rejects cross-city, cross-source and cross-capability observations.

Provider-specific tests must additionally verify schema mapping, units, entity identity, freshness policy and upstream error mapping. External-network smoke tests remain separate from deterministic CI. A minimal adapter test has this shape:

```python
def test_provider_contract() -> None:
    assert_provider_contract(
        ProviderContractCases(
            city=city,
            available=provider_with_fixture("success.json"),
            degraded=provider_with_fixture("partial.json"),
            unavailable=provider_with_timeout(),
        )
    )
```
