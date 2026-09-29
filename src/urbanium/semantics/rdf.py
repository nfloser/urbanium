"""Bounded RDF projection and SHACL validation for canonical relationships."""

from collections.abc import Iterable
from hashlib import sha256
from importlib.resources import files
from urllib.parse import quote

from pyshacl import validate
from rdflib import PROV, RDF, XSD, Graph, Literal, Namespace, URIRef

from urbanium.core.entity import EntityReference, EvidenceReference, RelationshipAssertion

URBANIUM = Namespace("https://w3id.org/urbanium/")
SOSA = Namespace("http://www.w3.org/ns/sosa/")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")

ENTITY_CLASS_MAPPINGS: dict[str, URIRef] = {
    "district": GEO.Feature,
    "weather_station": SOSA.Platform,
}
PREDICATE_MAPPINGS: dict[str, URIRef] = {
    "located_in": GEO.sfWithin,
}


class SemanticValidationError(ValueError):
    """Raised when a projected RDF graph violates Urbanium's SHACL shape."""


def entity_iri(entity: EntityReference) -> URIRef:
    """Map a canonical entity identity to a deterministic Urbanium IRI."""

    return URIRef(f"{URBANIUM}entity/{quote(entity.canonical_id, safe='')}")


def relationship_iri(assertion: RelationshipAssertion) -> URIRef:
    """Map a directed relationship identity to a deterministic Urbanium IRI."""

    return URIRef(f"{URBANIUM}relationship/{quote(assertion.canonical_id, safe='')}")


def evidence_iri(evidence: EvidenceReference) -> URIRef:
    """Identify one immutable evidence snapshot by its complete canonical content."""

    content = "\x00".join(
        (
            evidence.city_id,
            evidence.source_id,
            evidence.record_id,
            evidence.retrieved_at.isoformat(),
        )
    )
    digest = sha256(content.encode("utf-8")).hexdigest()
    return URIRef(f"{URBANIUM}evidence/{digest}")


def project_relationships(assertions: Iterable[RelationshipAssertion]) -> Graph:
    """Project canonical assertions into a validated, in-memory RDF graph."""

    graph = Graph()
    _bind_namespaces(graph)
    for assertion in assertions:
        _add_assertion(graph, assertion)
    validate_relationship_graph(graph)
    return graph


def validate_relationship_graph(graph: Graph) -> None:
    """Validate an RDF projection with the packaged SHACL Core shape."""

    shape_text = files("urbanium.semantics.shapes").joinpath("relationships.ttl").read_text("utf-8")
    shapes = Graph().parse(data=shape_text, format="turtle")
    conforms, _, report_text = validate(
        data_graph=graph,
        shacl_graph=shapes,
        inference="none",
        advanced=False,
        meta_shacl=False,
    )
    if not conforms:
        raise SemanticValidationError(str(report_text))


def _add_assertion(graph: Graph, assertion: RelationshipAssertion) -> None:
    subject = _add_entity(graph, assertion.subject)
    object_ = _add_entity(graph, assertion.object)
    predicate = _predicate_iri(assertion.predicate)
    relationship = relationship_iri(assertion)

    graph.add((subject, predicate, object_))
    graph.add((relationship, RDF.type, RDF.Statement))
    graph.add((relationship, RDF.type, PROV.Entity))
    graph.add((relationship, RDF.subject, subject))
    graph.add((relationship, RDF.predicate, predicate))
    graph.add((relationship, RDF.object, object_))
    graph.add(
        (
            relationship,
            URBANIUM.stateCategory,
            URIRef(f"{URBANIUM}state/{assertion.state_category.value}"),
        )
    )
    graph.add(
        (
            relationship,
            PROV.generatedAtTime,
            Literal(assertion.asserted_at, datatype=XSD.dateTime),
        )
    )
    for evidence in assertion.evidence:
        evidence_node = _add_evidence(graph, evidence)
        graph.add((relationship, PROV.wasDerivedFrom, evidence_node))


def _add_entity(graph: Graph, entity: EntityReference) -> URIRef:
    node = entity_iri(entity)
    graph.add((node, RDF.type, URBANIUM.Entity))
    graph.add(
        (
            node,
            RDF.type,
            ENTITY_CLASS_MAPPINGS.get(
                entity.entity_type,
                URIRef(f"{URBANIUM}entity-type/{entity.entity_type}"),
            ),
        )
    )
    graph.add((node, URBANIUM.cityId, Literal(entity.city_id)))
    graph.add((node, URBANIUM.entityType, Literal(entity.entity_type)))
    graph.add((node, URBANIUM.entityId, Literal(entity.entity_id)))
    return node


def _add_evidence(graph: Graph, evidence: EvidenceReference) -> URIRef:
    node = evidence_iri(evidence)
    graph.add((node, RDF.type, PROV.Entity))
    graph.add((node, RDF.type, URBANIUM.Evidence))
    graph.add((node, URBANIUM.cityId, Literal(evidence.city_id)))
    graph.add((node, URBANIUM.sourceId, Literal(evidence.source_id)))
    graph.add((node, URBANIUM.recordId, Literal(evidence.record_id)))
    graph.add(
        (
            node,
            URBANIUM.retrievedAt,
            Literal(evidence.retrieved_at, datatype=XSD.dateTime),
        )
    )
    return node


def _predicate_iri(predicate: str) -> URIRef:
    return PREDICATE_MAPPINGS.get(predicate, URIRef(f"{URBANIUM}predicate/{predicate}"))


def _bind_namespaces(graph: Graph) -> None:
    graph.bind("urb", URBANIUM)
    graph.bind("prov", PROV)
    graph.bind("sosa", SOSA)
    graph.bind("geo", GEO)
