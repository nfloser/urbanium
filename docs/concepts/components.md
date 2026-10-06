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

## Run outcome and provenance contracts

After capability resolution, a deterministic run can report one of three states:

- `available`: at least one declared output was produced and no problem is present;
- `degraded`: declared output is present together with one or more explicit problems;
- `unavailable`: no output is present and at least one explicit problem explains the failure.

Every run records the city deployment, exact component id/version, exact capability-contract input versions and a caller-supplied timezone-aware execution timestamp. A run is validated against both the descriptor and the resolution that authorized it. Undeclared outputs, output version/category mismatches, input-provenance mismatches and outputs from an unresolved component are rejected.

`DerivedOutput` deliberately identifies the declared output contract rather than inventing one universal payload schema. Domain-specific result values belong to the corresponding versioned output contract; provider payloads must not leak into this core envelope.

## Boundary of the current implementation

The core now defines descriptors, city capability resolution, run-state invariants and reconstructable run provenance. It still does **not** invoke component code.

There is no scheduler, plugin loader, workflow engine, LLM planner or city-specific dispatch in this layer. The next execution slice must bind deterministic component implementations to these contracts without weakening the resolution and provenance guarantees.
