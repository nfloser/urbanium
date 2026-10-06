# Deterministic components and capability resolution

Urbanium components are reusable deterministic agents or models that declare what they need before any execution is attempted. The descriptor layer is city-independent: it depends on canonical capability contracts, not Berlin, Mainz or provider APIs.

## Descriptor contract

A component descriptor declares:

- a component `kind` (`agent` or `model`);
- a stable component identifier and version;
- exact-version capability inputs;
- versioned outputs;
- an allowed derived-state category for every output.

The currently allowed output categories are `derived`, `forecast`, `scenario` and `simulated`. Raw `live` or `historical` provider state is not a component output category because a deterministic component must not relabel source observations as newly derived state.

Descriptors reject duplicate capability requirements and duplicate output identifiers. The component registry also rejects duplicate kind/id/version entries and exposes descriptors in deterministic order.

## City resolution

Resolution compares one descriptor with one validated city deployment.

A requirement is satisfied only when:

1. the city declares the capability;
2. support is `configured`; and
3. the capability contract version exactly matches the required version.

Failures are explicit and machine-readable:

- `missing_capability`: the city does not declare the requested capability;
- `not_configured`: the capability exists but is candidate, unavailable or unknown;
- `version_mismatch`: a configured capability exists under a different contract version.

This makes portability observable rather than fabricated. A component that requires `weather@1` and `realtime_transport@1` resolves for Berlin in the current reference deployments but not for Mainz, where realtime transport remains a candidate integration.

## Boundary of the current implementation

This layer does **not** execute components. It does not contain an LLM planner, workflow scheduler, plugin runtime or city-specific dispatch. It also does not yet define the provenance envelope for produced derived results.

Those concerns remain part of the broader agent/model framework. Keeping descriptor resolution separate means later execution can only start after deterministic capability compatibility has already been established.
