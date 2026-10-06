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

- **#8 First evidence-backed cross-domain demonstrator** — depends on #4, #5 and #7.

## Planned sequence

#1 -> #2 -> #3 -> #4
      |     |      \
      |     +----> #6
      |     +----> #7 --+
      +---------> #5    |
                   \    /
                     #8

The sequence may evolve as evidence changes, but dependency direction should stay explicit. New domains should be added as vertical slices with real decision/analysis value rather than as a catalogue of disconnected datasets.
