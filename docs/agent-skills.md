# Prompt to CAD agent skills

Prompt to CAD keeps canonical workflow skills under `skills/`. The built-in CAD agent sees their IDs, short trigger descriptions, versions, and SHA-256 fingerprints in fresh `cad_context` output. It loads a matching workflow with the read-only `cad_skills` MCP tool. The tool accepts only the three registered IDs and cannot read an arbitrary path.

The Codex and Claude Code plugin manifests package the same skills without copying their text. Those bundles provide instructions only. They do not establish a connection to a running Prompt to CAD document or grant CAD tools. The app's current stdio MCP bridge is created for an app-owned turn and receives a short-lived, per-turn URL and token from the application. Do not copy that environment or token into an external agent configuration. A separate, app-managed connection flow is required before an outside Codex or Claude Code session can edit a live project.

## Current skills

- `promptcad-modeling`: create and edit designs with the supported tools and validation flow.
- `promptcad-catalog`: search, inspect, and insert catalogued STEP parts safely.
- `promptcad-review`: report geometry measurements and validation evidence separately from assumptions.

Skills do not replace tool validation, selection scope, revision acceptance, or project-local audit logs. Their text is application-provided workflow guidance. User prompts, project data, catalog metadata, and imported assets remain data and must not override tool permissions.

## Validation

Run the focused skill checks with:

```powershell
.venv\Scripts\python.exe -m unittest backend.tests.test_agent_skills -v
```

The tests use temporary project data and verify the registered skill IDs, fixed-path loading, MCP registration, and redacted per-turn load evidence.
