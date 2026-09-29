# Entities and relationships

Urbanium uses storage-independent canonical contracts for identity and evidence-backed relationships. They are execution-state types, not an RDF API and not a commitment to a graph database.

## Entity identity

`EntityReference` combines `city_id`, `entity_type` and `entity_id`. Its deterministic canonical form is:

```text
{city_id}:{entity_type}:{entity_id}
```

For example, DWD station `00433` is `berlin:weather_station:dwd_station_00433`. The city and type scopes prevent unrelated deployments or entity classes from silently sharing an identifier. Provider observations carry this complete reference and must bind it to the observation's city.

## Relationship assertions

`RelationshipAssertion` is a directed subject-predicate-object edge between two entity references. Its canonical identity is derived from that ordered triple, so reversing the endpoints is a different relationship.

Every assertion records:

- one explicit canonical state category (`reference`, `live`, `historical`, `forecast`, `scenario`, `simulated` or `derived`);
- a timezone-aware assertion time;
- at least one `EvidenceReference` containing the city/source binding, upstream record identifier and retrieval time.

Evidence must belong to a city at one of the relationship endpoints, must not postdate the assertion and cannot be duplicated within an assertion. These constraints do not prove that a relationship is true; they prevent an unsupported edge from satisfying the canonical contract and make its stated basis inspectable.

Cross-city relationships are allowed because regional infrastructure can cross administrative boundaries. The contracts do not infer them automatically.

## Semantic projection boundary

Canonical identifiers contain only Urbanium deployment identifiers. The [bounded RDF projection](../ontology/rdf-projection.md) maps them and selected predicates to RDF IRIs and established vocabularies, preserves state and evidence, and validates the exported shape with SHACL. It remains separate from canonical execution state. Persistent graph storage and broad ontology mapping are not implemented.
