# ADR 0004: Area-based discovery, agents and a static twin read model

- Status: Accepted
- Date: 2026-11-23

## Context

Urbanium aims to work for any city that publishes data, with semantics, provenance and derived knowledge in the spirit of knowledge-graph digital twins. Until now each deployment named single station ids by hand, agents had nothing spatial to work on, and the public demo could only list catalogue metadata because GitHub Pages has no backend.

## Decision

1. **Cities declare an area.** A city may define a WGS84 search envelope. Nationwide sources discover their entities inside it through a city-independent discovery contract (`urbanium.core.discovery`). Hand-picked ids remain possible but are no longer required.
2. **Agents derive knowledge.** Derived facts (temperature spread, water-level trend, spatial relations) are produced by deterministic agents on the existing component framework. They consume canonical reads only and keep their inputs and rules explicit.
3. **A versioned snapshot is the twin read model.** `urbanium.twin` composes discovery, reads, relations and agent runs into `urbanium.twin-snapshot/1` JSON plus an RDF/Turtle projection with GeoSPARQL points and SOSA observations. Static clients render it without calling upstream sources.
4. **Snapshots are built on a schedule in CI** from live sources. Responses can be recorded and replayed; every snapshot states its `data_mode` (`live`, `replay`, `synthetic`) so example data is never mistaken for live data.

## Consequences

- Adding a city covered by nationwide sources is configuration only: an area, the sources and their bindings.
- The core gains two small, generic contracts (area, discovery). Adapters, agents and the twin layer stay outside it; architecture tests guard the direction.
- A snapshot is a point-in-time view, not a persistent store. Trends are limited to the history the sources themselves keep (DWD `now` archive, 31 days at PEGELONLINE) until a persistence layer exists.
- Publishing snapshots redistributes source data. Only sources with `redistribution: permitted` are bound for area discovery today (DWD CC BY 4.0, PEGELONLINE DL-DE->Zero-2.0); attribution is shown in the client.
