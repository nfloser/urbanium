# Development roadmap

The GitHub issues are the executable roadmap. Dependencies are intentional; dates are not promised.

## P0: prove the abstraction

- **#1 Bootstrap architecture and engineering baseline** — completed.
- **#2 First vertical slice: city and capability registry** — implemented; shared contracts and Berlin/Mainz deployment definitions prove the first portability boundary.
- **#3 Provider adapter contracts and shared contract tests** — implemented; numeric observation sources now share binding, outcome, provenance and reusable contract-test semantics.
- **#4 Shared weather vertical slice** — implemented for DWD CDC 10-minute air temperature in Berlin and Mainz.

## P1: semantics and reusable intelligence

- **#5 Semantic projection and relationship model** — implemented through #14's canonical relationship contracts and #16's bounded RDF/SHACL projection.
- **#6 Versioned machine-to-machine platform API** — implemented as the /api/v1 discovery and canonical observation surface with generated OpenAPI contract checks.
- **#7 Generic agent/model capability framework** — implemented through #18 (descriptors/resolution), #20 (run outcomes/provenance) and #22 (deterministic invocation).

## P2: prove cross-domain value

- **#8 First evidence-backed cross-domain demonstrator** — depends on #4, #5 and #7. Provider evidence-to-component input conversion (#29), a deterministic weather/transport source-readiness snapshot (#31) and the reusable evidence/answerability pre-flight (#77) establish a bounded integration path. A descriptive nearest-observation timestamp gap (#37) is a diagnostic, not temporal alignment. A defensible real-data impact analysis, temporal/spatial alignment and an operational decision rule remain outstanding; the readiness snapshot does not close #8.

## P2b: any city, derived knowledge, usable demo

- **Area-based discovery** — implemented. Cities declare a search area; DWD and PEGELONLINE discover their entities inside it (ADR 0004).
- **PEGELONLINE water level** — implemented as a shared nationwide adapter; Berlin's `river_level` is now configured.
- **Agents** — `temperature_spread@1`, `water_level_trend@1` and spatial relations, all deterministic and evidence-backed.
- **Twin snapshot and Twin Explorer** — implemented; published on GitHub Pages from live sources on a schedule.
- **Hamburg and Köln** — added through configuration only.

Next candidates, each as its own vertical slice: persistent observation history (longer trends, last-known-good state), Umweltbundesamt air quality as a third nationwide source, DWD weather warnings, and a first cross-domain agent that combines water level and precipitation with an explicit decision rule.

## Planned sequence

#1 -> #2 -> #3 -> #4
      |     |      \
      |     +----> #6
      |     +----> #7 --+
      +---------> #5    |
                   \    /
                     #8

The sequence may evolve as evidence changes, but dependency direction should stay explicit. New domains should be added as vertical slices with real decision/analysis value rather than as a catalogue of disconnected datasets.
