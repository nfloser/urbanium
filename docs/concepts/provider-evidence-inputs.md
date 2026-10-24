# Provider evidence in component inputs

A provider read and a component invocation have different contracts. Providers return
canonical numeric observations with source-level health and quality metadata;
deterministic components accept versioned JSON-safe capability inputs. The
`urbanium.analysis.observation_inputs.observation_input` handoff connects these
boundaries without interpreting a source's domain or changing its health state.

## Use

```python
from urbanium.analysis.observation_inputs import observation_input

# city is a validated CityDefinition; provider implements ObservationProvider.
result = provider.read()
input_value = observation_input(city, provider.descriptor, result)
```

The helper checks that the provider is bound to a configured capability and
verified source in the selected city, then validates every observation against
that provider descriptor. The resulting `CapabilityInput.version` comes from
the city's capability contract, not the adapter's implementation version.

Its JSON-safe payload contains two objects:

- `provider`: the complete `ProviderDescriptor` (city, source, capability and
  adapter version).
- `read`: the complete canonical `ProviderResult` (availability, freshness,
  observations, and typed error). Observations retain entity identity, quantity,
  decimal value as a string, unit, observed/received timestamps and quality.

The payload is an **evidence envelope**, not a new weather or mobility schema.
It contains no provider-specific wire formats. A degraded read remains degraded
with its observations and error. An unavailable read has an empty observation
list and retains its error; no value is synthesized. A numeric zero remains a
real observation, not a missing-value marker.

## Responsibility of the component

Capability resolution checks whether a city *can* supply a capability. It does
not assert that a live read succeeded. A component consuming this envelope must
check `read.availability` and `read.freshness`, validate the quantities and
units it needs, and decide whether to return an available, degraded or
unavailable execution outcome. The generic executor does not silently filter
failed reads or turn source outages into component outputs.

This handoff is a prerequisite for #8's cross-domain demonstrator. It does
not establish temporal alignment, spatial overlap, disruption severity,
weather/transport causation, or an operational decision rule. Those require
separate evidence-backed tests and a domain-specific output contract.
