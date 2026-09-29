# Agent instructions

Urbanium is a long-lived, city-independent urban digital-twin platform. Automated contributors must preserve the architecture rather than optimize for file count or superficial feature breadth.

Before changing code, inspect the relevant issue, architecture docs, ADRs, tests and CI. Work on a branch, add tests, update documentation, and use a pull request.

Core rules:

- never make Berlin, Mainz or another deployment a dependency of generic core code;
- isolate external sources behind adapters;
- represent missing capabilities explicitly;
- preserve provenance and distinguish epistemic/data states;
- keep deterministic computation independent of LLMs;
- keep applications, including dashboards, outside the core architecture;
- prefer a modular monorepo until distributed complexity has demonstrated value;
- do not fabricate infrastructure relationships or operational data.
