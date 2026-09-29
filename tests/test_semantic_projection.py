from datetime import UTC, datetime

import pytest
from rdflib import PROV, RDF, XSD, Literal, URIRef

from urbanium.core.entity import (
    EntityReference,
    EvidenceReference,
    RelationshipAssertion,
    StateCategory,
)
from urbanium.semantics.rdf import (
    GEO,
    SOSA,
    URBANIUM,
    SemanticValidationError,
    entity_iri,
    evidence_iri,
    project_relationships,
    relationship_iri,
    validate_relationship_graph,
)

NOW = datetime(2026, 9, 29, 20, tzinfo=UTC)


def assertion() -> RelationshipAssertion:
    return RelationshipAssertion(
        subject=EntityReference(
            city_id="berlin",
            entity_type="weather_station",
            entity_id="dwd_station_00433",
        ),
        predicate="located_in",
        object=EntityReference(
            city_id="berlin",
            entity_type="district",
            entity_id="tempelhof",
        ),
        state_category=StateCategory.REFERENCE,
        asserted_at=NOW,
        evidence=(
            EvidenceReference(
                city_id="berlin",
                source_id="dwd_open_data",
                record_id="stations/00433",
                retrieved_at=NOW,
            ),
        ),
    )


def test_relationship_projection_uses_standard_vocabularies_and_preserves_provenance() -> None:
    value = assertion()
    graph = project_relationships((value,))
    subject = entity_iri(value.subject)
    object_ = entity_iri(value.object)
    relationship = relationship_iri(value)
    evidence = evidence_iri(value.evidence[0])

    assert (subject, RDF.type, SOSA.Platform) in graph
    assert (object_, RDF.type, GEO.Feature) in graph
    assert (subject, GEO.sfWithin, object_) in graph
    assert (relationship, RDF.type, RDF.Statement) in graph
    assert (relationship, RDF.type, PROV.Entity) in graph
    assert (relationship, RDF.subject, subject) in graph
    assert (relationship, RDF.predicate, GEO.sfWithin) in graph
    assert (relationship, RDF.object, object_) in graph
    assert (relationship, URBANIUM.stateCategory, URBANIUM["state/reference"]) in graph
    assert (
        relationship,
        PROV.generatedAtTime,
        Literal(NOW, datatype=XSD.dateTime),
    ) in graph
    assert (relationship, PROV.wasDerivedFrom, evidence) in graph
    assert (evidence, RDF.type, PROV.Entity) in graph
    assert (evidence, RDF.type, URBANIUM.Evidence) in graph
    assert (evidence, URBANIUM.sourceId, Literal("dwd_open_data")) in graph
    assert (evidence, URBANIUM.recordId, Literal("stations/00433")) in graph
    assert (evidence, URBANIUM.retrievedAt, Literal(NOW, datatype=XSD.dateTime)) in graph


def test_projection_identifiers_and_graph_are_deterministic() -> None:
    value = assertion()

    first = project_relationships((value,))
    second = project_relationships((value,))

    assert entity_iri(value.subject) == entity_iri(value.subject.model_copy())
    assert relationship_iri(value) == relationship_iri(value.model_copy())
    assert evidence_iri(value.evidence[0]) == evidence_iri(value.evidence[0].model_copy())
    assert set(first) == set(second)


def test_projected_graph_conforms_to_packaged_shacl_shape() -> None:
    validate_relationship_graph(project_relationships((assertion(),)))


def test_missing_relationship_provenance_fails_shacl_validation() -> None:
    value = assertion()
    graph = project_relationships((value,))
    graph.remove((relationship_iri(value), PROV.wasDerivedFrom, None))

    with pytest.raises(SemanticValidationError, match="wasDerivedFrom"):
        validate_relationship_graph(graph)


def test_unknown_canonical_terms_stay_in_the_urbanium_namespace() -> None:
    value = assertion().model_copy(
        update={
            "subject": EntityReference(
                city_id="berlin",
                entity_type="water_pump",
                entity_id="pump_1",
            ),
            "predicate": "feeds",
        }
    )

    graph = project_relationships((value,))

    assert (
        entity_iri(value.subject),
        RDF.type,
        URIRef(f"{URBANIUM}entity-type/water_pump"),
    ) in graph
    assert (
        entity_iri(value.subject),
        URIRef(f"{URBANIUM}predicate/feeds"),
        entity_iri(value.object),
    ) in graph
