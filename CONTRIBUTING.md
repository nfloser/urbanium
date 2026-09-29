# Contributing to Urbanium

## Development workflow

Changes should normally follow this sequence:

1. Create or select a GitHub issue with acceptance criteria.
2. Create a branch from main; do not develop directly on main.
3. Add or update tests before or with implementation changes.
4. Keep provider-specific and city-specific logic behind explicit boundaries.
5. Update architecture, API and operational documentation together with code.
6. Run the available local checks.
7. Open a pull request that links the issue and explains design choices, tests and risks.
8. Let GitHub Actions complete and independently review the diff.
9. Correct findings on the same branch and rerun checks before merge.

## Branches and commits

Use descriptive branches such as feat/city-registry, fix/source-freshness, or docs/ontology-strategy. Prefer small, coherent commits that leave the branch in a usable state.

## Architectural rules

- urbanium.core must not import city-specific packages.
- generic agents/models must depend on capabilities and canonical contracts, not provider APIs.
- provider payload schemas must not become public platform contracts.
- dashboard/frontend code must not be required for core execution.
- missing source data must remain missing or degraded; never synthesize production values merely to make a capability appear available.
- reference/live/historical/forecast/scenario/simulated states must not be conflated.
- source and transformation provenance must remain reconstructable.

## Tests

Tests should match the risk of the change. Prefer reusable contract tests for providers and architecture tests for dependency boundaries. Real external-source smoke checks should be separated from deterministic correctness CI so provider outages cannot make core tests nondeterministic.

Reusable helpers under `tests/contracts` are part of the checked test infrastructure and must pass strict Mypy together with production code.
