# Urbanium

[![CI](https://github.com/nfloser/urbanium/actions/workflows/ci.yml/badge.svg)](https://github.com/nfloser/urbanium/actions/workflows/ci.yml)
[![Browser demo](https://github.com/nfloser/urbanium/actions/workflows/pages.yml/badge.svg)](https://nfloser.github.io/urbanium/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](#license)

**Live city data from official sources in one API – with the source of every value attached.**

Urbanium reads live data such as air temperatures from the German Weather Service (DWD), water levels from PEGELONLINE and public-transport alerts from the Berlin-Brandenburg transport association (VBB), translates it into one common format and serves it through a versioned REST API and a map-based explorer. Every value keeps where it came from and when it was read. If a source is down, Urbanium says so instead of filling the gap.

The core knows no city. Berlin and Mainz were the first deployments; Hamburg and Köln were added through configuration alone.

*Auf Deutsch:* Urbanium liest Live-Daten wie Lufttemperaturen des Deutschen Wetterdienstes, Pegelstände und Störungsmeldungen des VBB, bringt sie in ein gemeinsames Format und zeigt sie über eine REST-API und eine Karte. Zu jedem Wert bleibt erhalten, woher er stammt und wann er gelesen wurde.

**Python 3.12 · FastAPI · Pydantic · RDF/SHACL · GeoSPARQL · Leaflet · REST/OpenAPI**

[Twin Explorer](https://nfloser.github.io/urbanium/) · [Run locally](#run-locally) · [API reference](docs/api/v1.md) · [Documentation](#documentation)

## Twin Explorer

[Open the Twin Explorer](https://nfloser.github.io/urbanium/) – a map-first view of Berlin, Hamburg, Köln and Mainz, rebuilt from live sources twice an hour:

- **Map**: every discovered weather station and gauge with its latest value; hover for time, freshness and source
- **Findings**: agent results in plain language, each with how it was calculated
- **Knowledge graph**: stations, gauges, water bodies and their relationships, measured and derived kept apart, with a Turtle export
- **Cities**: capabilities, sources and coverage per city, with a comparison export

The previous catalogue view remains under `/catalog/`. See [demo/README.md](demo/README.md) to run it locally or offline.

## Current status

- **Sources**: DWD air temperature (10-minute stations), PEGELONLINE water levels, VBB GTFS-Realtime alerts, each behind its own adapter with provenance
- **Cities**: Berlin, Mainz, Hamburg and Köln; nationwide sources discover their stations and gauges inside each city's search area
- **Agents**: temperature spread across stations at one shared time, six-hour water-level trends, gauges against their long-term characteristic values, spatial links between entities
- **Outputs**: REST API (`/api/v1`) with OpenAPI, versioned twin snapshots as JSON and RDF/Turtle, 30-day observation histories
- **Not yet**: a persistent last-known-good state store, scheduling and orchestration beyond the snapshot workflow

<details>
<summary>Status in detail</summary>

The architecture/engineering baseline is established. The first executable vertical slice adds a versioned city/capability/source registry in which Berlin and Mainz validate through the same core contracts while retaining different evidence-backed capability sets.

The registry describes static deployment support. The provider layer includes a shared [DWD CDC air-temperature adapter](docs/providers/dwd-air-temperature.md) for Berlin and Mainz and a Berlin [VBB GTFS-Realtime adapter](docs/providers/vbb-gtfs-realtime.md) that counts active Alert entities without inventing disruption causes. Both use the shared [provider contract](docs/concepts/provider-contracts.md) for canonical outcomes and provenance, including typed [entity identities](docs/concepts/entities-and-relationships.md). A separate [DWD station inventory reader](docs/providers/dwd-station-locations.md) produces sourced station points without claiming weather coverage.

Evidence-backed relationships have a bounded [RDF/SHACL projection](docs/ontology/rdf-projection.md) while canonical execution remains independent of RDF storage. The reusable-intelligence layer has a complete minimal [deterministic component framework](docs/concepts/components.md) with exact-version capability resolution, explicit runtime outcomes, JSON-safe contract payloads, framework-owned provenance and guarded component invocation.

The [v1 machine API](docs/api/v1.md) exposes city/capability/source discovery and canonical observation reads through application-independent /api/v1 contracts. Provider degradation remains explicit in the response body, unavailable upstream reads use HTTP 503 without losing the typed provider result, and the generated OpenAPI surface is covered by contract tests.

The first [weather/transport source-readiness component](docs/concepts/weather-transport-readiness.md) consumes canonical provider evidence and reports whether the two independent sources are usable for further analysis. It deliberately does not infer weather-related transport disruptions or claim spatial/temporal alignment.

Cities can declare a search area. Nationwide sources then [discover their entities inside it](docs/concepts/area-discovery.md): every DWD 10-minute temperature station and every [PEGELONLINE](docs/providers/pegelonline-water-level.md) gauge on federal waterways. [Agents](docs/concepts/agents.md) derive evidence-backed knowledge from these reads (temperature difference across stations at one shared time, six-hour water-level trends) and link entities in the knowledge graph (gauge to water body, gauge to nearest weather station). The [twin snapshot](docs/concepts/twin-snapshot.md) bundles all of it per city as versioned JSON and an RDF/Turtle projection with GeoSPARQL points and SOSA observations (see [ADR 0004](docs/adr/0004-area-discovery-and-twin-read-model.md)).

A persistent last-known-good state store is not implemented yet. Scheduling, plugin discovery, persistence and higher-level orchestration remain intentionally separate concerns.

</details>

## Run locally

Requires Python 3.12 or newer.

```bash
git clone https://github.com/nfloser/urbanium.git
cd urbanium
```

On Windows (with the Python Launcher `py.exe`):

```powershell
.\scripts\start-windows.ps1
```

If PowerShell blocks local scripts, allow them for the current session first with `Set-ExecutionPolicy -Scope Process RemoteSigned`.

On Linux or macOS:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install .
URBANIUM_CITIES=cities python -m urbanium.api
```

Then open:

- [the dashboard](http://127.0.0.1:8000/) to choose a city and see live weather and transit alerts where supported
- [the interactive API](http://127.0.0.1:8000/api/v1/docs) – try city discovery, then the observation route with `mainz`, `dwd_open_data` and `weather` for a real DWD reading

For component runs and semantic projections, see the Python examples in the [component documentation](docs/concepts/components.md) and the [semantic projection guide](docs/ontology/rdf-projection.md).

## How Urbanium works

Urbanium provides shared infrastructure for federated urban digital twins across different cities. City adapters and agents connect data sources without tying the platform core to any one deployment.

Urbanium is designed as platform infrastructure, not as a dashboard application. Dashboards, command-line tools, research notebooks and municipal integrations are clients of its stable contracts; the core runs independently of them.

Berlin and Mainz are the first reference deployments used to prove portability. Neither city is allowed to define the platform core. Hamburg and Köln were added through configuration only, using area-based discovery of nationwide sources.

### Goals

Urbanium connects urban assets, sensors, observations, datasets, models, simulations and agents through versioned interfaces. Data retains its provenance, uncertainty and quality metadata; reference, live, historical, forecast, scenario and simulated states remain distinct.

The long-term goal is to connect information across urban domains so relationships between systems can support analysis and decisions.

### Architecture principles

- city-independent core with explicit city adapters;
- capability-based behavior instead of assumed data parity;
- provider adapters isolate external schemas;
- canonical contracts are the runtime interoperability boundary;
- semantic/knowledge-graph representations are introduced where they add interoperability or reasoning value;
- provenance and epistemic state are first-class;
- agents and models declare requirements rather than hard-coding cities;
- applications consume platform interfaces and do not own core behavior;
- modular monorepo first, distributed deployment only when evidence justifies it;
- no fabricated production data or hidden fallback semantics.

## Documentation

- [Documentation index](docs/index.md)
- [Architecture overview](docs/architecture/overview.md)
- [API v1](docs/api/v1.md)
- [Twin Explorer](demo/README.md)
- [Architecture decisions (ADRs)](docs/adr/)
- [Roadmap](docs/development/roadmap.md)
- [Contributing](CONTRIBUTING.md) and [security policy](SECURITY.md)

## Development

Urbanium uses an issue-driven workflow:

Issue -> branch -> tests -> implementation -> documentation -> pull request -> CI -> review -> corrections -> merge

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Urbanium source code is licensed under the Apache License 2.0. External datasets, APIs, ontologies and other third-party resources retain their own licensing and attribution requirements.
