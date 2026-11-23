"""Versioned, self-describing snapshot of one city's digital-twin state.

A snapshot is an application-level read model. It bundles the city contract,
discovered entities with their sourced locations, the latest value and recent
series per entity, evidence-backed relationships and every agent run, so that
static clients can render the twin without calling Urbanium or any upstream.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from rdflib import RDF, RDFS, XSD, Graph, URIRef
from rdflib import Literal as RdfLiteral

from urbanium.agents import DerivedRelation, default_agents, derive_relations
from urbanium.analysis.observation_inputs import observation_input
from urbanium.core.city import CityDefinition, Identifier
from urbanium.core.component import UnavailableCapability, resolve_component
from urbanium.core.discovery import DiscoveryResult, DiscoveryStatus, validate_discovery_result
from urbanium.core.entity import EntityReference, EvidenceReference
from urbanium.core.execution import (
    CapabilityInput,
    ComponentRunResult,
    DeterministicComponent,
    execute_component,
)
from urbanium.core.geometry import CityArea
from urbanium.core.provider import (
    Observation,
    ProviderDescriptor,
    ProviderResult,
    validate_provider_descriptor,
    validate_provider_result,
)
from urbanium.semantics.rdf import GEO, SOSA, URBANIUM, entity_iri, project_relationships
from urbanium.twin.bindings import AreaBinding, Clock

# Values from an earlier snapshot are kept at most this long after their measurement.
CARRY_WINDOW = timedelta(hours=48)
SNAPSHOT_SCHEMA: Literal["urbanium.twin-snapshot/1"] = "urbanium.twin-snapshot/1"
INDEX_SCHEMA: Literal["urbanium.twin-index/1"] = "urbanium.twin-index/1"


class DataMode(StrEnum):
    """Where the snapshot's upstream responses came from."""

    LIVE = "live"
    REPLAY = "replay"  # recorded real responses, played back later
    SYNTHETIC = "synthetic"  # hand-made example data, never real measurements


class DailyStat(BaseModel):
    """One local calendar day of archived values for one entity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    day: date
    min: str
    max: str
    mean: str
    count: int


class LatestValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quantity_id: Identifier
    value: str
    unit: str
    observed_at: datetime


class TwinEntity(BaseModel):
    """A discovered entity with its sourced location and recent values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    entity_type: Identifier
    entity_id: Identifier
    label: str
    capability_id: Identifier
    source_id: Identifier
    latitude: float
    longitude: float
    attributes: dict[str, str | int | float | bool]
    evidence: list[EvidenceReference]
    freshness: Literal["fresh", "stale", "no_data", "last_known"]
    latest: LatestValue | None = None
    series: list[tuple[datetime, str]] = Field(default_factory=list)
    # Set when the values come from an earlier snapshot because this run got none.
    carried_over_from: datetime | None = None
    # In the optional ring around the city area rather than in the area itself.
    in_surroundings: bool = False
    # Daily summaries from the observation archive, oldest first (may be empty).
    daily: list[DailyStat] = Field(default_factory=list)


class TwinLayer(BaseModel):
    """Outcome of one area binding: discovery plus measurement read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: Identifier
    source_id: Identifier
    quantity_id: Identifier
    discovery_status: Literal["available", "unavailable"]
    availability: Literal["available", "degraded", "unavailable"]
    freshness: Literal["fresh", "stale", "unknown"]
    freshness_minutes: int
    entity_count: int
    error: str | None = None
    carried_over: int = 0
    carried_over_from: datetime | None = None


class AgentRun(BaseModel):
    """Resolution and, when possible, the run of one agent for the city."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    component_id: Identifier
    version: str
    kind: str
    inputs: list[Identifier]
    resolved: bool
    unresolved: list[UnavailableCapability] = Field(default_factory=list)
    run: ComponentRunResult | None = None
    skipped_reason: str | None = None


class TwinSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["urbanium.twin-snapshot/1"] = SNAPSHOT_SCHEMA
    generated_at: datetime
    data_mode: DataMode
    city: CityDefinition
    layers: list[TwinLayer]
    entities: list[TwinEntity]
    relations: list[DerivedRelation]
    agents: list[AgentRun]


class CitySummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Identifier
    name: str
    area: CityArea | None
    entity_count: int
    layers: list[TwinLayer]
    agents_answered: int
    agents_total: int


class TwinIndex(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["urbanium.twin-index/1"] = INDEX_SCHEMA
    generated_at: datetime
    data_mode: DataMode
    cities: list[CitySummary]


def build_city_snapshot(
    city: CityDefinition,
    bindings: Sequence[AreaBinding],
    *,
    clock: Clock,
    data_mode: DataMode,
    agents: Sequence[DeterministicComponent] | None = None,
    previous: TwinSnapshot | None = None,
) -> TwinSnapshot:
    discoveries: list[DiscoveryResult] = []
    reads: list[
        tuple[AreaBinding, DiscoveryResult, ProviderDescriptor | None, ProviderResult | None]
    ]
    reads = []
    for binding in bindings:
        discovery = binding.discovery.discover(city)
        validate_discovery_result(city, discovery)
        discoveries.append(discovery)
        if discovery.status is DiscoveryStatus.UNAVAILABLE:
            reads.append((binding, discovery, None, None))
            continue
        provider = binding.provider_for(discovery.entities)
        validate_provider_descriptor(city, provider.descriptor)
        read = provider.read()
        validate_provider_result(provider.descriptor, read)
        reads.append((binding, discovery, provider.descriptor, read))

    # Sampled after every upstream response so no evidence postdates it.
    completed_at = clock()

    carry = _Carry(city, previous, data_mode, completed_at)
    layers: list[TwinLayer] = []
    entities: list[TwinEntity] = []
    inputs: dict[str, CapabilityInput] = {}
    for binding, discovery, descriptor, result in reads:
        views = _entities(city, binding, discovery, result, completed_at)
        if discovery.status is DiscoveryStatus.UNAVAILABLE:
            views = carry.layer(binding)
        else:
            views = [carry.entity(view) for view in views]
        carried = [view for view in views if view.carried_over_from is not None]
        layer = _layer(binding, discovery, result)
        if carried:
            layer = layer.model_copy(
                update={
                    "carried_over": len(carried),
                    "carried_over_from": min(
                        view.carried_over_from for view in carried if view.carried_over_from
                    ),
                }
            )
        layers.append(layer)
        entities.extend(views)
        if descriptor is not None and result is not None:
            inputs.setdefault(
                binding.capability_id,
                observation_input(
                    city, descriptor, result, prepared_at=completed_at, reference=discovery.entities
                ),
            )

    runs = [
        _agent_run(city, agent, inputs, completed_at)
        for agent in (default_agents() if agents is None else agents)
    ]
    return TwinSnapshot(
        generated_at=completed_at,
        data_mode=data_mode,
        city=city,
        layers=layers,
        entities=sorted(entities, key=lambda item: item.id),
        relations=carry.relations(
            derive_relations(city, discoveries, asserted_at=completed_at),
            {view.id for view in entities if view.carried_over_from is not None},
        ),
        agents=runs,
    )


class _Carry:
    """Fill gaps of this run with recent values from an earlier snapshot.

    Only snapshots of the same city and data mode qualify, values are kept at
    most CARRY_WINDOW after their measurement, and every carried entity is
    marked `last_known` with the time of the snapshot it came from.
    """

    def __init__(
        self,
        city: CityDefinition,
        previous: TwinSnapshot | None,
        data_mode: DataMode,
        completed_at: datetime,
    ) -> None:
        usable = (
            previous is not None
            and previous.city.id == city.id
            and previous.data_mode == data_mode
            and previous.generated_at <= completed_at
        )
        self._previous = previous if usable else None
        self._completed_at = completed_at
        self._by_id = {item.id: item for item in self._previous.entities} if self._previous else {}

    def _recent(self, entity: TwinEntity) -> bool:
        return entity.latest is not None and (
            self._completed_at - entity.latest.observed_at <= CARRY_WINDOW
        )

    def _mark(self, entity: TwinEntity) -> TwinEntity:
        assert self._previous is not None
        return entity.model_copy(
            update={
                "freshness": "last_known",
                "carried_over_from": entity.carried_over_from or self._previous.generated_at,
            }
        )

    def layer(self, binding: AreaBinding) -> list[TwinEntity]:
        """Whole layer lost (discovery failed): keep its recent entities."""

        return [
            self._mark(item)
            for item in self._by_id.values()
            if item.capability_id == binding.capability_id
            and item.source_id == binding.source_id
            and self._recent(item)
        ]

    def entity(self, view: TwinEntity) -> TwinEntity:
        """Entity discovered now but without values: keep its recent values."""

        if view.latest is not None:
            return view
        earlier = self._by_id.get(view.id)
        if earlier is None or not self._recent(earlier):
            return view
        return self._mark(
            view.model_copy(
                update={
                    "latest": earlier.latest,
                    "series": earlier.series,
                    "carried_over_from": earlier.carried_over_from,
                }
            )
        )

    def relations(
        self, current: Iterable[DerivedRelation], carried_ids: set[str]
    ) -> list[DerivedRelation]:
        merged = {item.assertion.canonical_id: item for item in current}
        if self._previous is not None:
            for item in self._previous.relations:
                if item.assertion.subject.canonical_id in carried_ids:
                    merged.setdefault(item.assertion.canonical_id, item)
        return sorted(merged.values(), key=lambda item: item.assertion.canonical_id)


def build_index(
    snapshots: Iterable[TwinSnapshot], *, generated_at: datetime, data_mode: DataMode
) -> TwinIndex:
    cities = [
        CitySummary(
            id=twin.city.id,
            name=twin.city.name,
            area=twin.city.area,
            entity_count=len(twin.entities),
            layers=twin.layers,
            agents_answered=sum(
                1 for item in twin.agents if item.run and item.run.status.value != "unavailable"
            ),
            agents_total=len(twin.agents),
        )
        for twin in snapshots
    ]
    return TwinIndex(
        generated_at=generated_at,
        data_mode=data_mode,
        cities=sorted(cities, key=lambda item: item.id),
    )


def project_snapshot(twin: TwinSnapshot) -> Graph:
    """RDF view: validated relationships plus labels, WKT points and latest observations."""

    graph = project_relationships(item.assertion for item in twin.relations)
    graph.bind("rdfs", RDFS)
    for relation in twin.relations:
        if relation.object_label:
            graph.add(
                (
                    entity_iri(relation.assertion.object),
                    RDFS.label,
                    RdfLiteral(relation.object_label),
                )
            )
    for entity in twin.entities:
        reference = _reference(entity)
        node = entity_iri(reference)
        graph.add((node, RDFS.label, RdfLiteral(entity.label)))
        geometry = URIRef(f"{node}/geometry")
        graph.add((node, GEO.hasGeometry, geometry))
        graph.add((geometry, RDF.type, GEO.Geometry))
        graph.add(
            (
                geometry,
                GEO.asWKT,
                RdfLiteral(f"POINT({entity.longitude} {entity.latitude})", datatype=GEO.wktLiteral),
            )
        )
        if entity.latest is not None:
            digest = sha256(
                f"{entity.id}\x00{entity.latest.observed_at.isoformat()}".encode()
            ).hexdigest()
            observation = URIRef(f"{URBANIUM}observation/{digest}")
            graph.add((observation, RDF.type, SOSA.Observation))
            graph.add((observation, URBANIUM.observedPlatform, node))
            graph.add((observation, URBANIUM.quantity, RdfLiteral(entity.latest.quantity_id)))
            graph.add((observation, URBANIUM.unit, RdfLiteral(entity.latest.unit)))
            graph.add(
                (
                    observation,
                    SOSA.hasSimpleResult,
                    RdfLiteral(entity.latest.value, datatype=XSD.decimal),
                )
            )
            graph.add(
                (
                    observation,
                    SOSA.resultTime,
                    RdfLiteral(entity.latest.observed_at, datatype=XSD.dateTime),
                )
            )
    return graph


def _reference(entity: TwinEntity) -> EntityReference:
    city_id = entity.id.split(":", 1)[0]
    return EntityReference(
        city_id=city_id, entity_type=entity.entity_type, entity_id=entity.entity_id
    )


def _layer(
    binding: AreaBinding, discovery: DiscoveryResult, result: ProviderResult | None
) -> TwinLayer:
    if result is None:
        return TwinLayer(
            capability_id=binding.capability_id,
            source_id=binding.source_id,
            quantity_id=binding.quantity_id,
            discovery_status="unavailable",
            availability="unavailable",
            freshness="unknown",
            freshness_minutes=binding.freshness_minutes,
            entity_count=0,
            error=discovery.error.message if discovery.error else None,
        )
    return TwinLayer(
        capability_id=binding.capability_id,
        source_id=binding.source_id,
        quantity_id=binding.quantity_id,
        discovery_status="available",
        availability=result.availability.value,
        freshness=result.freshness.value,
        freshness_minutes=binding.freshness_minutes,
        entity_count=len(discovery.entities),
        error=result.error.message if result.error else None,
    )


def _entities(
    city: CityDefinition,
    binding: AreaBinding,
    discovery: DiscoveryResult,
    result: ProviderResult | None,
    completed_at: datetime,
) -> list[TwinEntity]:
    series: dict[str, list[Observation]] = defaultdict(list)
    if result is not None:
        for observation in result.observations:
            if observation.quantity_id == binding.quantity_id:
                series[observation.entity.canonical_id].append(observation)

    views: list[TwinEntity] = []
    for item in discovery.entities:
        reference = item.location.entity
        observations = sorted(series.get(reference.canonical_id, []), key=lambda o: o.observed_at)
        latest = observations[-1] if observations else None
        if latest is None:
            freshness: Literal["fresh", "stale", "no_data"] = "no_data"
        elif completed_at - latest.observed_at <= timedelta(minutes=binding.freshness_minutes):
            freshness = "fresh"
        else:
            freshness = "stale"
        views.append(
            TwinEntity(
                id=reference.canonical_id,
                entity_type=reference.entity_type,
                entity_id=reference.entity_id,
                label=item.label,
                capability_id=binding.capability_id,
                source_id=binding.source_id,
                latitude=item.location.point.latitude,
                longitude=item.location.point.longitude,
                attributes=item.attributes,
                evidence=list(item.location.evidence),
                in_surroundings=bool(city.area and city.area.in_surroundings(item.location.point)),
                freshness=freshness,
                latest=(
                    LatestValue(
                        quantity_id=latest.quantity_id,
                        value=str(latest.value),
                        unit=latest.unit,
                        observed_at=latest.observed_at,
                    )
                    if latest
                    else None
                ),
                series=[(obs.observed_at, str(obs.value)) for obs in observations],
            )
        )
    return views


def _agent_run(
    city: CityDefinition,
    agent: DeterministicComponent,
    inputs: dict[str, CapabilityInput],
    executed_at: datetime,
) -> AgentRun:
    descriptor = agent.descriptor
    resolution = resolve_component(city, descriptor)
    base = AgentRun(
        component_id=descriptor.id,
        version=descriptor.version,
        kind=descriptor.kind.value,
        inputs=[item.capability_id for item in descriptor.inputs],
        resolved=resolution.available,
        unresolved=list(resolution.unavailable),
    )
    if not resolution.available:
        return base
    missing = [item.capability_id for item in descriptor.inputs if item.capability_id not in inputs]
    if missing:
        return base.model_copy(
            update={"skipped_reason": f"no runtime read for capability '{missing[0]}'"}
        )
    attempt = execute_component(
        city,
        agent,
        inputs=tuple(inputs[item.capability_id] for item in descriptor.inputs),
        executed_at=executed_at,
    )
    return base.model_copy(update={"run": attempt.run})


__all__ = [
    "INDEX_SCHEMA",
    "SNAPSHOT_SCHEMA",
    "AgentRun",
    "DataMode",
    "TwinEntity",
    "TwinIndex",
    "TwinLayer",
    "TwinSnapshot",
    "build_city_snapshot",
    "build_index",
    "project_snapshot",
]
