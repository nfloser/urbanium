# Urbanium

Urbanium is a city-agnostic, agent-extensible infrastructure for federated urban digital twins and cross-domain urban intelligence.

The project is designed as long-lived platform infrastructure, not as a dashboard application. Applications such as dashboards, command-line tools, research notebooks and municipal integrations are clients of stable platform contracts.

Berlin and Mainz are the first reference deployments used to prove portability. Neither city is allowed to define the platform core.

## Goals

Urbanium aims to connect heterogeneous urban assets, sensors, observations, datasets, models, simulations and agents through explicit, versioned interfaces while preserving provenance, uncertainty, quality and the distinction between reference, live, historical, forecast, scenario and simulated state.

The long-term differentiator is cross-domain reasoning: understanding how otherwise separate urban systems relate and what decisions become possible because those relationships are represented explicitly.

## Architecture principles

- city-independent core with explicit city adapters;
- capability-based behavior instead of assumed data parity;
- provider adapters isolate external schemas;
- canonical contracts are the runtime interoperability boundary;
- semantic/knowledge-graph representations are introduced where they add interoperability or reasoning value;
- provenance and epistemic state are first-class;
- agents and models declare requirements rather than hard-coding cities;
- applications consume platform interfaces and do not own core behavior;
- modular monorepo first, distributed deployment only when evidence justifies it;
- no fabricated production data or hidden fallback semantics.

See [documentation](docs/index.md), [architecture](docs/architecture/overview.md), [ADRs](docs/adr/) and the [roadmap](docs/development/roadmap.md).

## Current status

The repository is in architecture/bootstrap stage. Issue #1 establishes the engineering baseline. Issue #2 will implement the first executable vertical slice: one shared city/capability registry used by both Berlin and Mainz.

## Development

Urbanium uses an issue-driven workflow:

Issue -> branch -> tests -> implementation -> documentation -> pull request -> CI -> review -> corrections -> merge

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Urbanium source code is licensed under the Apache License 2.0. External datasets, APIs, ontologies and other third-party resources retain their own licensing and attribution requirements.
