# Deterministic components and capability resolution

Urbanium components are reusable deterministic agents or models that declare what they need before any execution is attempted. The component layer is city-independent: it depends on canonical capability contracts, not Berlin, Mainz or provider APIs.

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

## Deterministic invocation

`execute_component` is the minimal execution boundary. It resolves the component against the selected city before invoking implementation code. If resolution is unavailable, the implementation is not called and the execution attempt contains only the typed `ComponentResolution`.

For a resolved component, invocation then:

1. rejects duplicate capability inputs;
2. requires the exact capability ids and contract versions declared by the descriptor;
3. orders inputs deterministically before handing them to the implementation;
4. invokes the implementation once;
5. constructs provenance from the city, descriptor, validated input contracts and caller-supplied execution time;
6. validates emitted outputs against the descriptor before returning the run.

Unexpected implementation exceptions propagate rather than being converted into apparently healthy or degraded data. A component must explicitly return a degraded or unavailable outcome when those are legitimate domain/runtime states.

The implementation protocol is intentionally small: a descriptor plus `run(inputs)`. There is no discovery mechanism or implicit global registry of executable code.

## Run outcome and provenance contracts

After successful capability resolution, a deterministic run can report one of three states:

- `available`: at least one declared output was produced and no problem is present;
- `degraded`: declared output is present together with one or more explicit problems;
- `unavailable`: no output is present and at least one explicit problem explains the runtime failure.

Every run records the city deployment, exact component id/version, exact capability-contract input versions and a caller-supplied timezone-aware execution timestamp. An unresolved component does not produce a run envelope; its reason remains in `ComponentResolution`. `RunStatus.UNAVAILABLE` therefore means execution became unavailable only after capability resolution succeeded.

Capability inputs and derived outputs carry JSON-safe payloads. The generic envelope does not define one universal domain schema: payload meaning remains governed by the corresponding versioned capability or output contract. Provider-specific raw payloads must still be normalized before entering this boundary.

## Boundary of the current implementation

The generic agent/model framework now covers deterministic descriptors, registry lookup, city capability resolution, exact input validation, invocation, explicit runtime outcomes and reconstructable provenance.

It still does **not** provide a scheduler, plugin discovery/loader, workflow engine, persistence layer, LLM planner or city-specific dispatch. Those concerns should be introduced only by separate evidence-backed issues rather than being hidden in the core execution path.
