"""Deterministic relationships between discovered entities of one city.

Three kinds of edges are produced, each with the evidence it rests on:

* `located_in` — an entity's sourced point lies in the city's discovery area
  (derived; the area is a search envelope, not a city boundary);
* `located_near` — the point lies in the optional surroundings ring;
* `on_water_body` — the gauge's water body as stated by the source
  (reference state, taken from the source record);
* `nearest_weather_station` — the great-circle nearest discovered weather
  station to each gauge (derived; nearness is not representativeness).
"""

from collections.abc import Iterable
from datetime import datetime
from re import sub

from pydantic import BaseModel, ConfigDict, Field

from urbanium.core.city import CityDefinition
from urbanium.core.discovery import DiscoveredEntity, DiscoveryResult, DiscoveryStatus
from urbanium.core.entity import EntityReference, RelationshipAssertion, StateCategory
from urbanium.core.spatial import distance_km


class DerivedRelation(BaseModel):
    """A relationship assertion plus how it was derived."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    assertion: RelationshipAssertion
    method: str = Field(min_length=1)
    distance_km: float | None = None
    object_label: str | None = None


def derive_relations(
    city: CityDefinition,
    discoveries: Iterable[DiscoveryResult],
    *,
    asserted_at: datetime,
) -> tuple[DerivedRelation, ...]:
    if city.area is None:
        return ()
    entities: list[DiscoveredEntity] = []
    for result in discoveries:
        if result.city_id != city.id:
            raise ValueError("discovery result does not belong to the city")
        if result.status is DiscoveryStatus.AVAILABLE:
            entities.extend(result.entities)

    area = EntityReference(city_id=city.id, entity_type="discovery_area", entity_id=city.id)
    relations: list[DerivedRelation] = []
    for item in entities:
        inside = city.area.contains(item.location.point)
        if inside or city.area.in_surroundings(item.location.point):
            relations.append(
                DerivedRelation(
                    assertion=RelationshipAssertion(
                        subject=item.location.entity,
                        predicate="located_in" if inside else "located_near",
                        object=area,
                        state_category=StateCategory.DERIVED,
                        asserted_at=asserted_at,
                        evidence=item.location.evidence,
                    ),
                    method="point_in_area" if inside else "point_in_surroundings",
                    object_label=city.name,
                )
            )

    gauges = [item for item in entities if item.location.entity.entity_type == "river_gauge"]
    stations = sorted(
        (item for item in entities if item.location.entity.entity_type == "weather_station"),
        key=lambda item: item.location.entity.entity_id,
    )
    for gauge in gauges:
        water = gauge.attributes.get("water")
        slug = water_body_id(water) if isinstance(water, str) else None
        if isinstance(water, str) and slug:
            relations.append(
                DerivedRelation(
                    assertion=RelationshipAssertion(
                        subject=gauge.location.entity,
                        predicate="on_water_body",
                        object=EntityReference(
                            city_id=city.id, entity_type="water_body", entity_id=slug
                        ),
                        state_category=StateCategory.REFERENCE,
                        asserted_at=asserted_at,
                        evidence=gauge.location.evidence,
                    ),
                    method="source_attribute",
                    object_label=water,
                )
            )
        if stations:
            nearest = min(
                stations,
                key=lambda station: round(
                    distance_km(gauge.location.point, station.location.point), 9
                ),
            )
            relations.append(
                DerivedRelation(
                    assertion=RelationshipAssertion(
                        subject=gauge.location.entity,
                        predicate="nearest_weather_station",
                        object=nearest.location.entity,
                        state_category=StateCategory.DERIVED,
                        asserted_at=asserted_at,
                        evidence=gauge.location.evidence + nearest.location.evidence,
                    ),
                    method="nearest_by_great_circle",
                    distance_km=round(distance_km(gauge.location.point, nearest.location.point), 3),
                    object_label=nearest.label,
                )
            )
    return tuple(sorted(relations, key=lambda relation: relation.assertion.canonical_id))


def water_body_id(name: str) -> str | None:
    """Stable, city-scoped identifier for a water body name stated by a source."""

    text = name.casefold()
    for source, target in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(source, target)
    text = sub(r"[^a-z0-9]+", "_", text).strip("_")
    return f"water_{text}" if text else None
