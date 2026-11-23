# Berlin and Mainz reference deployments

Berlin and Mainz are the first portability tests for Urbanium. The current files describe **static integration metadata only**; they do not perform live acquisition.

## Current registry state

| Capability | Berlin | Mainz |
|---|---|---|
| weather | configured | configured |
| realtime_transport | configured | candidate |
| river_level | configured | configured |
| open_data_catalog | configured | candidate |

The asymmetry is intentional. A configured capability means the deployment has a verified source boundary in the registry, not that a current observation exists.

## Berlin

The registry records DWD weather, PEGELONLINE water levels, VBB GTFS-Realtime and the Berlin Open Data catalogue as verified source boundaries. Weather stations and Spree/Havel gauges are discovered inside the declared city area. Dataset-specific licences and live provider health remain separate concerns.

## Mainz

The registry records DWD weather and PEGELONLINE water levels as verified source boundaries; the Rhine gauge at Mainz is found through area discovery rather than hard-coded. Realtime transport remains a candidate pending dedicated interface/terms verification. The Mainz WebGIS/geodata modernization is recorded as a candidate integration rather than treated as a stable API contract before verification.

## Portability criterion

A third city should be addable through its deployment configuration and provider bindings while the city-independent core remains unchanged unless a genuinely generic abstraction is missing.
