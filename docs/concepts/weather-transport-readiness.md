# Weather and transport source-readiness snapshot (v1)

The deterministic `WeatherTransportReadiness` component is a first, deliberately
bounded cross-domain execution slice for #8. It answers a narrow operational
question: **do the independently reported weather and transport observations
provide usable evidence for further analysis?** It does **not** answer whether
weather affected transport. In particular, the two sources are not spatially
joined, time-aligned or correlated, and the result is not a disruption forecast.

## Contracts and invocation

`assess_weather_transport_readiness(city, weather=..., transport=..., executed_at=...)`
uses the existing `execute_component` boundary. Both inputs must be produced
through `observation_input` (or conform to its documented evidence contract):

- `weather@1`: canonical `air_temperature` observations in `Cel`;
- `realtime_transport@1`: canonical `active_service_alerts` in unit `1`,
  expressed as non-negative whole numbers.

The component checks the source binding against the **selected city**,
validates the canonical provider result, and rejects a missing or malformed
evidence envelope, including a preparation time earlier than any observation's
receipt time **or later than the component's execution time**. The boundary is
inclusive: equivalent instants with different timezone offsets are accepted.
Invalid evidence is excluded from validated observations and cannot contribute
to `both_sources_usable`. These checks establish receipt/preparation/execution
provenance order only; they do not establish overlapping observation windows
between weather and transport. It does not import DWD/VBB wire formats.
Only observations with the required quantity, unit and numeric semantics are
marked validated.
Zero temperature and zero active alerts are both legitimate readings.

The declared output is `source_readiness@1`, category `derived`. Its payload
contains `independent_observations_only: true`, `both_sources_usable`, and
separate `weather` and `realtime_transport` objects. Each valid evidence
object retains the provider descriptor, full canonical read (including
availability, freshness, error, observations and quality), preparation time,
and a deterministically ordered `validated_observations` list. The boolean
only means **both sources returned fresh, available and contract-valid
measurements**; it does not establish overlapping time or location.

`closest_observation_gap_seconds` reports the smallest absolute separation
between any two **validated** `observed_at` instants, one from each source,
expressed in seconds. It is `null` if either side has no validated measurement.
The comparison normalizes timezone offsets and does not depend on input order.
`closest_observation_pair` makes that number auditable. When a pair exists,
it identifies the contributing `weather` and `realtime_transport`
observations by their complete canonical entity references and `observed_at`
instants normalized to UTC (`Z`). It is `null` whenever the gap is `null`.
For equal-distance candidates, the earliest weather instant, then earliest
transport instant, then lexicographically ordered entity identities win. Input
order and equivalent timezone representations do not affect selection. This
adds diagnostic detail to the existing `source_readiness@1` payload without
changing its version, availability rules or provenance envelope.

A zero gap means matching timestamp instants, **not** shared geographic
coverage, matching measurement periods, correlation or causation. A nonzero
gap is descriptive; Urbanium does not impose a universal time-alignment
threshold. Stale or degraded but structurally valid observations may still
contribute to these diagnostics, without becoming `usable` or improving run
status. No observation is interpolated or synthesized.

The execution states are deliberately conservative:

| State | Meaning |
|---|---|
| `available` | Both sources contain valid required measurements and report `available` + `fresh`, with no validation problems. |
| `degraded` | At least one valid measurement survives, but another source is stale, degraded, unavailable, missing the required quantity, or invalid. The output explicitly marks which evidence is usable. |
| `unavailable` | Neither source has any valid required measurements. No derived output is emitted; typed problems explain the missing evidence. |

A provider's own `degraded` status and error are preserved, not silently
converted to healthy observations. A stale reading may be shown as evidence
but is not considered usable. No last-known-good value is substituted.
Malformed envelopes are not echoed as validated source data. As with other
component runs, unexpected programming errors are not converted into healthy
results.

## Reproducible synthetic example

Run from the repository root after `pip install -e ".[dev]"`:

```python
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from urbanium.analysis.observation_inputs import observation_input
from urbanium.analysis.weather_transport_readiness import assess_weather_transport_readiness
from urbanium.core.entity import EntityReference
from urbanium.core.provider import (
    Availability,
    Freshness,
    Observation,
    ProviderDescriptor,
    ProviderResult,
)
from urbanium.registry import CityRegistry

city = CityRegistry.from_directory(Path("cities")).city("berlin")
observed_at = datetime(2026, 10, 24, 9, 10, tzinfo=UTC)
received_at = datetime(2026, 10, 24, 9, 12, tzinfo=UTC)


def source_input(capability: str, source: str, quantity: str, unit: str, value: str):
    descriptor = ProviderDescriptor(
        city_id=city.id, source_id=source, capability_id=capability, adapter_version="1"
    )
    result = ProviderResult(
        availability=Availability.AVAILABLE,
        freshness=Freshness.FRESH,
        observations=(
            Observation(
                city_id=city.id,
                source_id=source,
                capability_id=capability,
                entity=EntityReference(
                    city_id=city.id,
                    entity_type="weather_station"
                    if capability == "weather"
                    else "transport_network",
                    entity_id="synthetic_station"
                    if capability == "weather"
                    else "synthetic_network",
                ),
                quantity_id=quantity,
                value=Decimal(value),
                unit=unit,
                observed_at=observed_at,
                received_at=received_at,
            ),
        ),
    )
    return observation_input(city, descriptor, result, prepared_at=received_at)


weather = source_input("weather", "dwd_open_data", "air_temperature", "Cel", "0.0")
transport = source_input("realtime_transport", "vbb_gtfs_rt", "active_service_alerts", "1", "0")
attempt = assess_weather_transport_readiness(
    city,
    weather=weather,
    transport=transport,
    executed_at=datetime(2026, 10, 24, 9, 15, tzinfo=UTC),
)
assert attempt.run is not None
assert attempt.run.status.value == "available"
assert attempt.run.outputs[0].payload["both_sources_usable"] is True
```

All values, station/network identifiers and times in this example are
**synthetic**. They demonstrate contracts, not real Berlin conditions or
real-time source availability. Production source attribution and data
redistribution must follow the provider-specific terms.

## Portability and remaining work

- **Berlin:** both required capabilities are configured and verified in the
  reference registry, so the component can execute. Runtime source health is
  still checked independently.
- **Mainz:** weather is configured but realtime transport is only a candidate.
  Capability resolution therefore prevents execution rather than pretending
  Mainz has VBB coverage.
- **Hypothetical third city:** the same code can execute only after a deployment
  declares both `@1` capabilities with verified, contract-compliant source
  bindings. Otherwise resolution is explicit and unavailable. No third-city
  observation is fabricated.

This readiness slice is not the complete #8 demonstrator. A useful
weather-to-mobility impact claim would additionally need defensible spatial
coverage, temporal alignment, validated transport impact semantics, an
evidence-backed relation/decision rule, and a reproducible real-data study.
