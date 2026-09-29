# Bounded RDF projection

Urbanium can project canonical `RelationshipAssertion` values into an in-memory RDF graph. The projection is an interoperability view: canonical Pydantic contracts remain the authoritative execution representation, and no triplestore or RDF synchronization process is required.

## Stable identities

Entity and relationship IRIs are deterministic transformations of their canonical identifiers beneath `https://w3id.org/urbanium/`. Evidence IRIs are SHA-256 content identifiers over city, source, upstream record identifier and retrieval time. Identical canonical input therefore produces identical graph identifiers without relying on database-generated keys.

## Vocabulary mapping

| Canonical concept | RDF mapping |
|---|---|
| every entity | `urb:Entity` plus `urb:cityId`, `urb:entityType` and `urb:entityId` |
| `weather_station` | `sosa:Platform` |
| `district` | `geo:Feature` |
| `located_in` | `geo:sfWithin` |
| relationship assertion | direct triple plus an `rdf:Statement` / `prov:Entity` resource |
| assertion time | `prov:generatedAtTime` |
| assertion evidence | `prov:wasDerivedFrom` |
| evidence record | `urb:Evidence` / `prov:Entity` with city, source and record identifiers |
| evidence retrieval time | `urb:retrievedAt` |
| state category | IRI below `urb:state/` |

SOSA is used because a weather station is a platform that can host sensing systems. GeoSPARQL is used only for the qualitative spatial relationship represented by `located_in`. PROV-O connects each projected assertion to the evidence entities from which Urbanium formed it. Retrieval time intentionally remains an Urbanium property: it does not claim to be the upstream entity's PROV generation time.

Unknown canonical entity types and predicates remain usable through deterministic `urb:entity-type/` and `urb:predicate/` IRIs. This preserves Urbanium extensibility without claiming that a custom term belongs to an external ontology.

The mapping follows the official [PROV-O](https://www.w3.org/TR/prov-o/), [SOSA/SSN](https://www.w3.org/TR/vocab-ssn-2023/), [GeoSPARQL](https://www.ogc.org/standards/geosparql/) and [SHACL](https://www.w3.org/TR/shacl/) specifications.

## Validation

`project_relationships()` validates every emitted graph against the packaged SHACL Core shape before returning it. The shape requires complete entity identity, reified relationship endpoints, state, assertion time and at least one PROV evidence link. Evidence nodes require their city/source/record identity and retrieval time. `validate_relationship_graph()` can also validate an externally modified projection and raises `SemanticValidationError` with the SHACL report when it does not conform.

The shape validates export structure, not factual truth. Urbanium does not infer relationships, invent source evidence or treat successful SHACL validation as proof that an asserted relationship is correct.

## Non-goals

This slice does not project numeric observations, define a complete urban ontology, perform reasoning, persist graphs or provide SPARQL services. Those capabilities require separate evidence and use cases. RDF libraries remain confined to `urbanium.semantics`; architecture tests prevent them from becoming core dependencies.
