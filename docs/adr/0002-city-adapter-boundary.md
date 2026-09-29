# ADR 0002: Cities are deployments behind capability and adapter boundaries

- Status: Accepted
- Date: 2026-09-29

## Context

Cities expose different datasets, schemas, update frequencies and legal constraints. Treating Berlin's source landscape as the platform model would make later cities forks of Berlin.

## Decision

The core knows generic city identity, capability and source contracts but does not know Berlin/Mainz provider implementations. City deployments bind source adapters and configuration to generic capabilities. Agents and models request capabilities rather than city names or provider APIs.

## Consequences

Berlin and Mainz may expose unequal capability sets without fake parity. Adding a city is primarily an integration task. Shared provider adapters may be reused when the same upstream source covers multiple cities.
