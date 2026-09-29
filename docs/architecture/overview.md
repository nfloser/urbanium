# Architecture overview

## Purpose

Urbanium is infrastructure for integrating urban digital twins, physical assets, observations, models and agents across arbitrary cities. Berlin and Mainz are portability tests, not architecture owners.

## Logical architecture

~~~mermaid
flowchart TB
    Sources[External sources and systems] --> Providers[Provider adapters]
    Providers --> Contracts[Canonical contracts]
    Contracts --> State[Reference / live / historical / forecast / scenario / simulated state]
    State --> Semantics[Semantic projection and relationships]
    State --> Agents[Agents and models]
    Semantics --> Agents
    Agents --> Derived[Derived state + provenance]
    State --> API[Versioned platform API]
    Derived --> API
    API --> Apps[Applications / dashboard / CLI / external systems]

    Cities[City deployments] --> Providers
    Cities --> Capability[Capability registry]
    Capability --> Agents
~~~

The diagram is logical, not a commitment to one physical deployment topology.

## Architectural layers

1. **Core contracts** define stable city-independent identities, state categories, provenance, quality, time, geometry and capability metadata.
2. **Provider adapters** isolate REST, streams, files, databases, OGC services and other provider-specific schemas.
3. **City deployments** configure providers, semantic mappings and geographic/source details without duplicating platform logic.
4. **State/runtime** separates reference, live, historical, forecast, scenario and simulated state.
5. **Semantic layer** represents cross-domain relationships and exports/queryable graph structures where useful.
6. **Agent/model layer** declares required capabilities and produces explicit derived results with provenance.
7. **Platform interfaces** expose machine-readable APIs independent of applications.
8. **Applications** are replaceable clients; no core behavior belongs only in a dashboard.

## Initial invariants

- core must not import Berlin, Mainz or other city deployments.
- agents/models depend on capabilities and canonical types, not source-specific APIs.
- external schemas terminate at provider-adapter boundaries.
- unavailable data remains unavailable; graceful degradation is explicit.
- reference/live/historical/forecast/scenario/simulated state is never mixed implicitly.
- provenance survives normalization and derivation.
- an RDF/knowledge-graph representation may enrich interoperability, but does not silently become the only source of execution truth.
- LLMs may later plan or interpret workflows, but deterministic queries/models remain authoritative for deterministic tasks.

## Initial technology direction

The first executable slices use Python 3.12 because Berlin Urban Intelligence already provides useful, tested lessons in typed canonical contracts and Python geospatial/data tooling. This is a starting implementation choice, not a requirement that every future Urbanium component use Python.

The repository begins as a modular monorepo. Service boundaries, message brokers, dedicated graph stores, time-series databases and spatial databases should be introduced only when a concrete workload or deployment requirement justifies them.

## Portability test

A generic feature is acceptable only if adding a third city primarily requires configuration, source adapters and semantic mapping rather than edits to the platform core. City-specific exceptions must be justified at the adapter/deployment boundary.
