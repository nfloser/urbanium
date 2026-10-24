# Provider evidence in component inputs

A provider read and a component invocation have different contracts. Providers return
canonical numeric observations with source-level health and quality metadata;
deterministic components accept versioned JSON-safe capability inputs. The
`urbanium.analysis.observation_inputs.observation_input` handoff connects these
boundaries without interpreting a source's domain or changing its health state.

## Use

```python
from datetime import UTC, datetime

from urbanium.analysis.observation_inputs import observation_input

# city is a validated CityDefinition; provider implements ObservationProvider.
result = provider.read()
input_value = observation_input(city, provider.descriptor, result, prepared_at=datetime.now(UTC))
```

The helper checks that the provider is bound to a configured capability and
verified source in the selected city, then validates every observation against
that provider descriptor. The resulting `CapabilityInput.version` comes from
the city's capability contract, not the adapter's implementation version.

Its JSON-safe payload contains a timezone-aware UTC `prepared_at` timestamp
(the input preparation time, **not** the upstream observation time) and two objects:

- `provider`: the complete `ProviderDescriptor` (city, source, capability and
  adapter version).
- `read`: the complete canonical `ProviderResult` (availability, freshness,
  observations, and typed error). Observations retain entity identity, quantity,
  decimal value as a string, unit, observed/received timestamps and quality.

Preparation must not precede the `received_at` time of **any** observation in
that read. The handoff compares timezone-aware instants (so equivalent UTC and
local-offset timestamps are accepted) and rejects impossible chronology before
any component consumes the input. An unavailable read contains no observations,
so its preparation timestamp remains valid independently of source receipt.
This guard is not a cross-source temporal-alignment check: it says nothing about
whether weather and transport measurements cover the same interval.

The payload is an **evidence envelope**, not a new weather or mobility schema.
It contains no provider-specific wire formats. A degraded read remains degraded
with its observations and error. An unavailable read has an empty observation
list and retains its error; no value is synthesized. The preparation timestamp
remains available even when the upstream provider returned no observations.
A numeric zero remains a
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
