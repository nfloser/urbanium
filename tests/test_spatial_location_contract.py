"""Evidence-backed locations are points, not inferred coverage areas."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from urbanium.core.entity import EntityReference, EvidenceReference, StateCategory
from urbanium.core.spatial import EntityPointLocation, Wgs84Point

NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


def location(**changes: object) -> EntityPointLocation:
    fields = {
        "entity": EntityReference(
            city_id="berlin", entity_type="weather_station", entity_id="dwd_station_00433"
        ),
        "point": Wgs84Point(latitude=52.5, longitude=13.4),
        "state_category": StateCategory.REFERENCE,
        "asserted_at": NOW,
        "evidence": (
            EvidenceReference(
                city_id="berlin",
                source_id="dwd_open_data",
                record_id="station-metadata/00433",
                retrieved_at=NOW,
            ),
        ),
    }
    return EntityPointLocation.model_validate({**fields, **changes})


def test_point_location_preserves_identity_coordinates_and_provenance() -> None:
    asserted = location()

    assert asserted.entity.canonical_id == "berlin:weather_station:dwd_station_00433"
    assert asserted.point.latitude == 52.5
    assert asserted.point.longitude == 13.4
    assert asserted.evidence[0].record_id == "station-metadata/00433"
    assert EntityPointLocation.model_validate_json(asserted.model_dump_json()) == asserted


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(-90, -180), (90, 180), (0, 0)],
)
def test_coordinate_boundaries_are_valid(latitude: float, longitude: float) -> None:
    assert Wgs84Point(latitude=latitude, longitude=longitude).latitude == latitude


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(90.0001, 0), (-90.0001, 0), (0, 180.0001), (0, -180.0001)],
)
def test_out_of_range_coordinates_are_rejected(latitude: float, longitude: float) -> None:
    with pytest.raises(ValidationError):
        Wgs84Point(latitude=latitude, longitude=longitude)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_coordinates_are_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        Wgs84Point(latitude=value, longitude=13.4)
    with pytest.raises(ValidationError):
        Wgs84Point(latitude=52.5, longitude=value)


def test_location_requires_a_source_evidence_record() -> None:
    with pytest.raises(ValidationError):
        location(evidence=())


def test_location_rejects_evidence_from_another_city() -> None:
    unrelated = location().evidence[0].model_copy(update={"city_id": "mainz"})
    with pytest.raises(ValidationError, match="evidence city"):
        location(evidence=(unrelated,))


def test_location_rejects_future_evidence() -> None:
    future = location().evidence[0].model_copy(
        update={"retrieved_at": NOW + timedelta(seconds=1)}
    )
    with pytest.raises(ValidationError, match="postdate"):
        location(evidence=(future,))


def test_location_rejects_duplicate_source_records() -> None:
    original = location().evidence[0]
    with pytest.raises(ValidationError, match="duplicate"):
        location(evidence=(original, original))


def test_location_rejects_naive_assertion_time() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        location(asserted_at=NOW.replace(tzinfo=None))


def test_equivalent_instants_with_different_offsets_are_valid() -> None:
    local = NOW.astimezone(timezone(timedelta(hours=2)))
    assert location(asserted_at=local).evidence[0].retrieved_at == NOW
