# ADR 0001: Start as a modular monorepo

- Status: Accepted
- Date: 2026-09-29

## Context

Urbanium is expected to span many urban domains and could eventually require independently scalable runtime components. Beginning with microservices would force distributed-system complexity before contracts and domain boundaries are proven.

## Decision

Start as a modular monorepo with explicit package/module boundaries. Physical deployment may still use multiple processes or stores when required, but repository modularity and stable contracts come before service count.

## Consequences

One CI surface and one architecture are easier to evolve while Berlin/Mainz portability is being proven. Architecture tests must prevent the monorepo from becoming a logical monolith. Distributed messaging and independently versioned services remain future options once justified by scale, ownership or deployment constraints.
