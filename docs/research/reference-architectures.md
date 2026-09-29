# Reference architecture analysis

This document records concepts worth carrying forward, not implementations to copy.

## Berlin Urban Intelligence

Useful lessons from the existing Berlin project:

- typed canonical contracts are an effective boundary between providers and domain logic;
- epistemic/data state, quality, freshness and availability must remain distinct;
- provenance needs to survive acquisition, derivation and presentation;
- live/reference/model/scenario state should have explicit boundaries;
- deterministic agents/orchestration work without making an LLM a runtime dependency;
- provider acquisition should be separated from request serving;
- external live-source checks should be separated from deterministic CI;
- a dashboard can remain a client of the API rather than the architecture center.

Urbanium intentionally differs by moving the city boundary outward: Berlin-specific source adapters and assumptions become one deployment alongside Mainz and future cities.

## The World Avatar

The World Avatar demonstrates several relevant principles:

- dynamic knowledge graphs can connect heterogeneous domains through shared semantics;
- autonomous computational agents can update/derive knowledge and compose workflows;
- ontologies provide machine-readable meaning across otherwise isolated datasets;
- provenance-aware derived-information workflows matter when inputs update independently;
- distributed/federated data ownership can coexist with a coherent logical model;
- visualization is a separate capability rather than the definition of the platform.

The older monorepo now points core development to more focused repositories including stack, ontology and visualization. Urbanium should learn from that separation of responsibilities while avoiding premature repository/service fragmentation.

## Deliberate Urbanium choices

Urbanium does not assume that every fact belongs permanently in one knowledge graph. Spatial, time-series, object, relational and external/federated stores may coexist behind stable logical contracts. Semantic graph representation is used where relationships, interoperability or reasoning justify it.

Urbanium also treats agents as typed software components first. LLM-based agents may later consume platform capabilities, but deterministic computation should not be replaced by generative inference where exact algorithms exist.
