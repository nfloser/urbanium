# Evidence assessment and answerability

Urbanium separates **evidence coverage** from domain conclusions.

A deterministic analysis should first establish whether its required provider evidence is present, contract-valid and usable. Only then should domain-specific logic interpret or combine that evidence.

## Evidence requirements

`EvidenceRequirement` declares the minimum measurement contract needed by an analysis:

- capability and contract version;
- quantity identifier;
- expected unit;
- a small deterministic numeric constraint when the quantity needs one.

The generic `assess_evidence()` boundary validates the existing canonical provider envelope. It checks city/provider binding, capability contract identity, receipt/preparation/execution chronology, provider availability and freshness, quantity/unit compatibility and the declared numeric rule.

It does not read provider wire formats and does not infer missing values.

Malformed evidence is reduced to an explicit invalid assessment. Unvalidated provider payloads are not copied into the assessment snapshot.

## Answerability

`assess_answerability()` combines evidence assessments for a declared requirement set.

The result is intentionally small:

| Status | Meaning |
|---|---|
| `available` | every required evidence item is usable |
| `degraded` | some validated evidence survives, but the full requirement set is not usable |
| `unavailable` | no required validated measurement is available |

Each requirement receives an item containing its capability identity, whether validated measurements exist, whether they are usable and stable problem codes. Missing evidence is reported explicitly instead of being treated as an empty successful result.

The report is deterministic: requirements are ordered by contract identity and duplicate capability requirements or assessments are rejected.

## What answerability does not prove

An `available` report means only that the declared evidence requirements are currently satisfied. It does **not** establish:

- factual truth beyond the supplied source evidence;
- spatial overlap or representative coverage;
- temporal alignment beyond the explicitly validated chronology;
- correlation or causation;
- an operational decision rule;
- semantic equivalence between unrelated quantities.

Those claims require their own evidence-backed contracts and analysis.

## Current use

The weather/transport readiness component now uses this shared pre-flight instead of maintaining its own provider-envelope validation path. Its existing `source_readiness@1` output remains unchanged: the generic layer decides evidence coverage, while the component keeps the domain-specific nearest-observation diagnostic and the explicit warning that independent source observations are not an impact claim.

Future deterministic analyses can reuse the same pre-flight without depending on weather, transport, a specific city or provider implementation.
