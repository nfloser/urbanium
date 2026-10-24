# Urbanium

Urbanium provides shared infrastructure for federated urban digital twins across different cities. City adapters and agents connect data sources without tying the platform core to any one deployment.

Urbanium is designed as platform infrastructure, not as a dashboard application. Dashboards, command-line tools, research notebooks and municipal integrations are clients of its stable contracts; the core runs independently of them.

Berlin and Mainz are the first reference deployments used to prove portability. Neither city is allowed to define the platform core.

## Goals

Urbanium connects urban assets, sensors, observations, datasets, models, simulations and agents through versioned interfaces. Data retains its provenance, uncertainty and quality metadata; reference, live, historical, forecast, scenario and simulated states remain distinct.

The long-term goal is to connect information across urban domains so relationships between systems can support analysis and decisions.

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

The architecture/engineering baseline is established. The first executable vertical slice adds a versioned city/capability/source registry in which Berlin and Mainz validate through the same core contracts while retaining different evidence-backed capability sets.

The registry describes static deployment support. The provider layer includes a shared [DWD CDC air-temperature adapter](docs/providers/dwd-air-temperature.md) for Berlin and Mainz and a Berlin [VBB GTFS-Realtime adapter](docs/providers/vbb-gtfs-realtime.md) that counts active Alert entities without inventing disruption causes. Both use the shared [provider contract](docs/concepts/provider-contracts.md) for canonical outcomes and provenance, including typed [entity identities](docs/concepts/entities-and-relationships.md).

Evidence-backed relationships have a bounded [RDF/SHACL projection](docs/ontology/rdf-projection.md) while canonical execution remains independent of RDF storage. The reusable-intelligence layer has a complete minimal [deterministic component framework](docs/concepts/components.md) with exact-version capability resolution, explicit runtime outcomes, JSON-safe contract payloads, framework-owned provenance and guarded component invocation.

The [v1 machine API](docs/api/v1.md) exposes city/capability/source discovery and canonical observation reads through application-independent /api/v1 contracts. Provider degradation remains explicit in the response body, unavailable upstream reads use HTTP 503 without losing the typed provider result, and the generated OpenAPI surface is covered by contract tests.

A persistent last-known-good state store is not implemented yet. Scheduling, plugin discovery, persistence and higher-level orchestration remain intentionally separate concerns.

## Development

Urbanium uses an issue-driven workflow:

Issue -> branch -> tests -> implementation -> documentation -> pull request -> CI -> review -> corrections -> merge

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Urbanium source code is licensed under the Apache License 2.0. External datasets, APIs, ontologies and other third-party resources retain their own licensing and attribution requirements.
