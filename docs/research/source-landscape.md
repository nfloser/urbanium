# Initial Berlin and Mainz source landscape

Status: preliminary architecture research, 2026-09-29. Every source must be verified again when an adapter is implemented; public accessibility does not imply redistribution permission.

## Common or reusable candidates

| Capability | Candidate | Coverage | Current assessment |
|---|---|---|---|
| weather / meteorology | Deutscher Wetterdienst (DWD) Open Data | Germany, including both reference cities | Strong first shared-provider candidate. Product/station selection, cadence and terms must be fixed in the provider issue. |
| road/reference topology | OpenStreetMap | both | Useful non-authoritative optional reference source; ODbL/provenance and quality limitations must remain explicit. |

## Berlin

Berlin has a mature open-data landscape. daten.berlin.de exposes thousands of datasets across WFS, WMS, CSV, JSON and other formats and documents a CKAN API for catalogue metadata. VBB publishes static GTFS and a GTFS-Realtime feed. Berlin Urban Intelligence already demonstrates working patterns for DWD, VBB, air quality and selected WFS/reference sources.

Candidate early capabilities: weather, transport/reference transit, realtime transport, air quality, public facilities, selected geospatial layers and later energy/reference infrastructure where licensing and semantics are clear.

## Mainz

Mainz currently has a less uniform public-data surface. The city's existing online Stadtplan/WebGIS is being modernized during 2026; the city states that the renewed geodata platform is intended as a foundation for its digital twin and is based on modern connected geodata infrastructure. The current public Stadtplan notes that the replacement system is expected toward the end of 2026, so Urbanium must not hard-code assumptions about its future API surface.

A strong live-data candidate already exists independently of city WebGIS: the federal PEGELONLINE service exposes the official Mainz/Rhein gauge with water level and discharge metadata. DWD provides a shared meteorological route. Public-transport coverage and machine interfaces usable under clear terms require dedicated verification before being declared a Mainz capability.

## Architecture consequence

The platform must expose capability differences honestly. A missing Mainz equivalent for a Berlin source is not an error in the core and must not be filled by synthetic data. Source entries should carry authority, licence/terms, update expectations, spatial/temporal coverage, provenance and known limitations.

## Primary research links

- Berlin Open Data: https://daten.berlin.de/
- VBB open datasets: https://unternehmen.vbb.de/digitale-services/datensaetze/
- DWD Open Data information: https://www.dwd.de/DE/leistungen/opendata/opendata.html
- Mainz geodata platform announcement: https://www.mainz.de/pressemeldungen/Mainz/2026/maerz/relaunch-webgis
- Mainz online Stadtplan: https://internet.mainz.de/stadtplan
- PEGELONLINE Mainz/Rhein: https://pegelonline.wsv.de/
