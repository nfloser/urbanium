# Evidence-backed entity point locations

A canonical `EntityPointLocation` associates one complete `EntityReference`
with a **sourced point assertion**, independently of provider observations,
city deployment configuration and RDF projection. The contract lives in
`urbanium.core.spatial`; it does not fetch or infer locations.

## Coordinate and provenance contract

`Wgs84Point` stores **latitude** and **longitude**, in that order, as
decimal-degree numbers in WGS84 (EPSG:4326). Latitude must be between -90
and 90; longitude between -180 and 180. Both must be finite. Invalid values
are rejected, never clamped. The point is a position, not a polygon, a
measurement footprint or a transport service area.

An `EntityPointLocation` includes:

- the city-scoped entity reference to which the point applies;
- the point and explicit state category (for example, `reference`);
- a timezone-aware assertion time;
- at least one `EvidenceReference` with city, source, upstream record ID and
  retrieval time.

Evidence must belong to the same city as the entity, must not have been
retrieved after the assertion, and must not repeat a source record within
the same assertion. Different timezone offsets denoting the same instant
are valid. The contract checks structural provenance; it does **not**
verify that the provider's coordinates are correct or that an assertion
is currently valid.

## Example with synthetic data

```python
from datetime import UTC, datetime

from urbanium.core.entity import EntityReference, EvidenceReference, StateCategory
from urbanium.core.spatial import EntityPointLocation, Wgs84Point

at = datetime(2026, 10, 25, 9, tzinfo=UTC)
assertion = EntityPointLocation(
    entity=EntityReference(
        city_id="example_city",
        entity_type="weather_station",
        entity_id="synthetic_station",
    ),
    point=Wgs84Point(latitude=50.0, longitude=8.0),
    state_category=StateCategory.REFERENCE,
    asserted_at=at,
    evidence=(
        EvidenceReference(
            city_id="example_city",
            source_id="synthetic_metadata",
            record_id="synthetic_station_record",
            retrieved_at=at,
        ),
    ),
)
```

All identifiers and coordinates above are **synthetic**. This example
does not assert a real station location or license any upstream dataset.

## Boundaries for the weather/transport demonstrator

This contract is a prerequisite for assessing spatial evidence in #8,
not a spatial join. In particular:

- A weather station's point does not specify the geographic area to which
  its air-temperature measurement applies.
- The VBB adapter's network-wide alert count has no defensible point
  location or affected-route geometry. It must **not** be assigned an
  arbitrary network centroid.
- Neither a small distance between two points nor matching city IDs
  establish common coverage, exposure, causation or an impact.
- Missing location evidence remains missing. Existing `Observation`,
  `ProviderResult` and `source_readiness@1` contracts are unchanged.

The [DWD station inventory reader](../providers/dwd-station-locations.md)
now produces these point assertions from the upstream station listing for
configured stations. It does not establish a measurement footprint or
validate historical station movement. The [offline VBB static stop lookup](../providers/vbb-static-stop-points.md)
can resolve explicitly named Alert stop IDs to reference points from a
caller-supplied, compatible `stops.txt`. A matched stop ID does not
establish that an Alert disrupts that stop, and point proximity does not
establish overlapping coverage. Suitable transport-event geometry and a
separate, evidence-backed spatial relationship or coverage assessment
remain future work.
