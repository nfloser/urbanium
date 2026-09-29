from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from urbanium.core.entity import (
    EntityReference,
    EvidenceReference,
    RelationshipAssertion,
    StateCategory,
)

NOW = datetime(2026, 9, 29, 19, tzinfo=UTC)


def entity(city_id: str = "berlin", entity_id: str = "station_1") -> EntityReference:
    return EntityReference(
        city_id=city_id,
        entity_type="weather_station",
        entity_id=entity_id,
    )


def evidence(record_id: str = "stations/00433") -> EvidenceReference:
    return EvidenceReference(
        city_id="berlin",
        source_id="dwd_open_data",
        record_id=record_id,
        retrieved_at=NOW,
    )


def test_entity_identity_is_stable_and_city_scoped() -> None:
    berlin = entity()
    mainz = entity(city_id="mainz")

    assert berlin.canonical_id == "berlin:weather_station:station_1"
    assert mainz.canonical_id == "mainz:weather_station:station_1"
    assert berlin.canonical_id != mainz.canonical_id


def test_relationship_has_deterministic_directional_identity_and_evidence() -> None:
    subject = entity()
    object_ = EntityReference(
        city_id="berlin",
        entity_type="district",
        entity_id="tempelhof",
    )

    assertion = RelationshipAssertion(
        subject=subject,
        predicate="located_in",
        object=object_,
        state_category=StateCategory.REFERENCE,
        asserted_at=NOW,
        evidence=(evidence(),),
    )

    assert assertion.canonical_id == (
        "berlin:weather_station:station_1:located_in:berlin:district:tempelhof"
    )
    reverse = assertion.model_copy(update={"subject": object_, "object": subject})
    assert reverse.canonical_id != assertion.canonical_id
    assert assertion.evidence[0].source_id == "dwd_open_data"


def test_relationship_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="at least 1 item"):
        RelationshipAssertion(
            subject=entity(),
            predicate="located_in",
            object=entity(entity_id="district_1"),
            state_category=StateCategory.REFERENCE,
            asserted_at=NOW,
            evidence=(),
        )


def test_relationship_rejects_naive_time_and_future_evidence() -> None:
    data = {
        "subject": entity(),
        "predicate": "located_in",
        "object": entity(entity_id="district_1"),
        "state_category": StateCategory.REFERENCE,
        "asserted_at": NOW,
        "evidence": (evidence(),),
    }
    with pytest.raises(ValidationError, match="asserted_at must be timezone-aware"):
        RelationshipAssertion.model_validate({**data, "asserted_at": NOW.replace(tzinfo=None)})
    with pytest.raises(ValidationError, match="must not postdate assertion"):
        RelationshipAssertion.model_validate(
            {
                **data,
                "evidence": (
                    evidence().model_copy(
                        update={"retrieved_at": datetime(2026, 9, 29, 20, tzinfo=UTC)}
                    ),
                ),
            }
        )


def test_evidence_retrieval_time_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError, match="retrieved_at must be timezone-aware"):
        EvidenceReference(
            city_id="berlin",
            source_id="dwd_open_data",
            record_id="stations/00433",
            retrieved_at=NOW.replace(tzinfo=None),
        )


def test_duplicate_evidence_references_are_rejected() -> None:
    duplicate = evidence()
    with pytest.raises(ValidationError, match="duplicate evidence reference"):
        RelationshipAssertion(
            subject=entity(),
            predicate="located_in",
            object=entity(entity_id="district_1"),
            state_category=StateCategory.REFERENCE,
            asserted_at=NOW,
            evidence=(duplicate, duplicate),
        )


def test_relationship_rejects_evidence_from_an_unrelated_city() -> None:
    unrelated = evidence().model_copy(update={"city_id": "mainz"})
    with pytest.raises(ValidationError, match="evidence city must match"):
        RelationshipAssertion(
            subject=entity(),
            predicate="located_in",
            object=entity(entity_id="district_1"),
            state_category=StateCategory.REFERENCE,
            asserted_at=NOW,
            evidence=(unrelated,),
        )
