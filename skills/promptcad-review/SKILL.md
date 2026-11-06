---
name: promptcad-review
version: 1.0.0
description: Inspect and validate a Prompt to CAD design, separating measured geometry and validation evidence from assumptions and unverified requirements.
---

# Prompt to CAD geometry review

Use this workflow when checking a generated or edited design, or when preparing a concise validation summary.

If the required inspection tools are unavailable, do not imply that a live model was checked. Explain that Prompt to CAD is not connected and limit the response to guidance based on information the user supplied.

1. Call `cad_context` and `cad_capabilities` to establish the current candidate, components, units, scope, and available checks.
2. Use `cad_inspect` for component and topology facts. Use `cad_measure` for supported entity-to-entity distances. Identify which candidate and entities the measurements refer to.
3. Call `cad_validate` for the application's actual geometry and preservation checks. Report its result accurately; do not substitute a visual impression for a measurement.
4. Separate measured values and validation results from design assumptions, catalog metadata, and requirements that remain unverified. In particular, overall bounds do not prove functional dimensions, fit, strength, or manufacturability.
5. State unavailable checks and the evidence needed to resolve them. Do not claim engineering certification or manufacturing readiness.

Use only registered Prompt to CAD tools. Do not use shell, arbitrary Python, filesystem access, SQL, or credentials.
