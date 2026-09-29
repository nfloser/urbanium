# Capabilities and deployment support

Urbanium uses capabilities to describe what a city deployment can provide without assuming that every city exposes the same data.

## Static support is not runtime health

The city registry describes **deployment support**, not whether an upstream provider is healthy at this instant.

| Support | Meaning |
|---|---|
| `configured` | The deployment has at least one verified source boundary for the capability. This does not guarantee current provider availability or fresh data. |
| `candidate` | A plausible source or integration path has been identified but has not yet been accepted as a verified Urbanium source boundary. |
| `unavailable` | The deployment intentionally declares the capability unavailable and must not bind sources to it. |
| `unknown` | Urbanium has not established whether the deployment can provide the capability. |

Runtime concepts such as availability, freshness, degraded state, last-known-good state and source errors belong to provider/runtime contracts introduced in later issues. A configured capability must never be interpreted as "live and healthy now."

## Source status

A source is either:

- `verified`: its source boundary has been checked sufficiently to back a configured deployment capability; or
- `candidate`: it is recorded for research/integration work but cannot make a capability configured.

Verification here is architectural/integration metadata. It is not a permanent guarantee that a public provider remains reachable or unchanged.

## Licence metadata

Every source records licence/terms metadata and a conservative redistribution classification. `unknown` is preferable to assuming that publicly accessible data may be redistributed. Dataset-specific terms remain authoritative over Urbanium metadata.

## Why this separation matters

Berlin may expose a realtime transport capability while Mainz currently has only a candidate integration. Mainz may expose an official Rhine gauge while no Berlin river-level source has been selected for this slice. Both deployments still validate through the same core contract; the registry reports the difference instead of fabricating parity.
