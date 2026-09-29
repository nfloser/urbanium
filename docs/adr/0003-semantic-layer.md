# ADR 0003: Canonical runtime contracts with a semantic projection layer

- Status: Accepted
- Date: 2026-09-29

## Context

Knowledge graphs and ontologies provide strong value for cross-domain identity, relationships, discovery, interoperability and reasoning. They also introduce modelling and operational complexity if every runtime concern is forced through RDF/triplestore access.

## Decision

Use typed canonical contracts as the first executable interoperability boundary and design a semantic projection/relationship layer alongside them. Reuse established vocabularies such as PROV-O, SOSA/SSN, QUDT and GeoSPARQL when they fit. Do not create RDF merely for appearance, and do not make a triplestore mandatory before a use case requires persistent graph querying.

## Consequences

Urbanium can adopt The World Avatar's strongest semantic ideas while keeping deterministic application state testable and simple. Semantic and canonical representations require explicit synchronization/version rules once persistent graph storage is introduced.
