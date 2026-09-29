# Berlin and Mainz reference deployments

Berlin and Mainz are the first portability tests for Urbanium. The current files describe **static integration metadata only**; they do not perform live acquisition.

## Current registry state

| Capability | Berlin | Mainz |
|---|---|---|
| weather | configured | configured |
| realtime_transport | configured | candidate |
| river_level | unknown | configured |
| open_data_catalog | configured | candidate |

The asymmetry is intentional. A configured capability means the deployment has a verified source boundary in the registry, not that a current observation exists.

## Berlin

The initial registry records DWD weather, VBB GTFS-Realtime and the Berlin Open Data catalogue as verified source boundaries. Dataset-specific licences and live provider health remain separate concerns.

## Mainz

The initial registry records DWD weather and the official PEGELONLINE Mainz/Rhein gauge as verified source boundaries. Realtime transport remains a candidate pending dedicated interface/terms verification. The Mainz WebGIS/geodata modernization is recorded as a candidate integration rather than treated as a stable API contract before verification.

## Portability criterion

A third city should be addable through its deployment configuration and provider bindings while the city-independent core remains unchanged unless a genuinely generic abstraction is missing.
