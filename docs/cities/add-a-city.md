# Add a city

Adding a city should normally be an integration task, not a fork of Urbanium.

## 1. Create the deployment definition

Add:

~~~text
cities/<city-id>/city.yaml
~~~

The identifier uses lowercase letters, digits and underscores and must start with a letter.

A minimal example:

~~~yaml
schema_version: "1"
id: hamburg
name: Hamburg
country_code: DE
timezone: Europe/Berlin
capabilities:
  - id: weather
    support: candidate
    notes: Source boundary still requires verification.
sources:
  - id: example_weather
    provider: Example Provider
    domain: weather
    protocol: https
    status: candidate
    authority: unknown
    capabilities: [weather]
    endpoint: https://example.invalid/
    license:
      redistribution: unknown
      notes: Terms have not yet been verified.
~~~

A candidate source does not make the capability configured. To declare `configured`, at least one associated source must be `verified`.

## 2. Declare only evidence-backed capabilities

Use the same capability vocabulary used by existing deployments when the semantics match. Do not create city-prefixed capabilities such as `hamburg_weather`.

Do not copy Berlin or Mainz capability values merely for symmetry. Use `candidate`, `unknown` or `unavailable` when the evidence does not support `configured`.

## 3. Isolate provider-specific details

Provider parsing, authentication, URL construction and payload schemas belong behind provider adapters. City files bind deployments to providers; they must not move source-specific schemas into the core.

If an existing adapter supports the provider, reuse it. If a new adapter is required, implement it against shared provider contracts and contract tests.

## 4. Preserve terms and provenance

Record provider identity, authority classification, endpoint/protocol, update expectations and licence/terms metadata. Never infer redistribution rights from public accessibility.

## 5. Run portability checks

At minimum run:

~~~bash
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
mypy src
pytest
~~~

The architecture test must continue to prove that `src/urbanium/core` has no city-specific imports.

## 6. Decide whether core changes are justified

Adding a city should not normally require editing core contracts. If it does, ask whether:

1. the abstraction is incomplete for all cities,
2. the behavior belongs in the city/provider integration layer, or
3. a genuinely new generic capability is required.

Core changes should be justified by generic semantics, not by one city's source schema.
