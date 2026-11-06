# Validation

Development policy: run tests only when the user explicitly requests a task-specific test. Do not automatically run these commands after source edits. Historical results below describe earlier runs; generated validation reports/screenshots have been removed as part of the source-only cleanup.

## Pending verification: faster validation, gear generation and background tasks

Implemented without running tests or a rebuild:

- `cad_validate` reuses a passing result while asset hashes, placements, names, colours and assembly structure are unchanged (asset integrity, scope and engineering records are re-checked every time). Full validation defaults to a 180 s budget (`CAD_VALIDATION_TIMEOUT`, or `time_budget_seconds` up to 600); an identical retry after a timeout is refused unless the budget grows. The MCP bridge waits up to 660 s so long results are returned.
- The geometry worker's `verify` checks each unique solid asset once, measures each shape once during the STEP round-trip comparison (same comparisons and tolerances), and reports `step_timing` for solid checks, STEP export, re-import and comparison. Turn logs record them as `validation_*` phases.
- Scripts can call `involute_gear(...)`, `planet_mesh_rotation(...)` and `ring_mesh_rotation(...)`, and place identical copies with `instances`, which share one geometry asset.
- The Working dropdown shows the latest progress line only while collapsed. Agent tasks keep running while other conversations or projects are opened; document edits stay locked until the task finishes or is stopped.

When requested, compare the same saved assembly before and after with identical solid validity, interference, dimension, placement and STEP round-trip checks, using the logged `step_timing`.

## Pending verification: project ordering and conversation polish

Project sorting/timestamps, bulk model visibility/selection, shaded redisplay, per-message copying, provider-aware authors and the compact model trigger have been implemented and included in the explicitly requested local native rebuild. No tests or UI verification were run for these changes.

When specifically requested, validate stable ordering across open/refresh/restart and legacy timestamp initialization; meaningful content changes versus session-only updates; solid/mesh hide/show cycles with colours and edges; visibility/selection synchronization under filtering, revisions and the 256-entity limit; frozen running-task selection; clipboard output during streaming; historical provider identity; and compact layouts in both themes at laptop sizes and Windows scaling. Use synthetic projects and provider metadata, preserving personal data and credentials.

## Pending verification: agentic CAD capabilities

Component restructuring, multi-output definitions, expanded controlled scripting, metadata-aware revisions/scope, component colours, engineering records and image attachment/capability handling are implemented and included in the explicitly requested local native rebuild. No tests, live inference or UI verification were run. See [agentic CAD capabilities](agentic-cad.md) for the API behaviour, limitations and acceptance scenarios to run only when explicitly requested.

## Existing validation commands

Run the automated backend, native UI and tracked-file checks:

```powershell
.venv\Scripts\python.exe -m tools.validate
.venv\Scripts\python.exe -m tools.validate_ui
.venv\Scripts\python.exe -m tools.check_privacy
```

The backend suite checks CAD operations, geometry validity, selection scope, persistence, undo/redo, provider protocol/authentication fixtures and Windows process ownership. It generates fresh synthetic models instead of reading saved user designs. The native UI check creates a synthetic solid assembly and mesh, then exercises topology picking, empty startup with missing project folders omitted, skippable onboarding, the single Send/Stop control, settings lifecycle, project-dialog re-entry, immediate draft clearing, later-draft preservation, collapsed work summaries, reported-token display, and three display layouts/scales. Activity/message fixtures are explicitly labelled in the reports and do not start provider inference.

Reports, screenshots, fixtures and generated models are local outputs under ignored artifacts/ and tmp/ directories. They must not be committed or copied into public source or the release. Previously retained runs and example models were preserved outside the repository with the saved designs.

A live plan-usage check is optional and explicitly consumes the selected account's allowance:

```powershell
.venv\Scripts\python.exe -m tools.validate_live --execute
```

It uses an isolated local project and keeps conversation/task records out of Git. A passing protocol fixture does not establish a successful live sign-in or model request. Review local reports for the exact checks performed. No installer is generated during development.

## Account and lifecycle update

The retained full backend run passed 72 tests with no failures, errors or skips. A subsequent focused run passed 28 account, storage and lifecycle checks, including the final revocation-state and renamed-folder changes. The final native build passed all three real viewport layouts: dark laptop, light at 150% scaling, and a larger light display. Onboarding skip/singleton, empty startup, Send/Stop cancellation state, settings re-entry and conversation opening are asserted by the native checks. Screenshots retain synthetic chat/activity fixtures; no live provider inference was run. Source privacy and staged secret scans passed. Evidence remains under ignored artifacts/validation/account-lifecycle and artifacts/validation/ui.json.

## Workspace polish, selection and account cleanup

The full backend run passed 79 tests with no failures, errors or skips. A final focused run passed 16 geometry, copy, lifecycle and authentication checks after reference-asset validation and repeated-restore changes; a separate retained-branch copy test also passed. Tests use temporary projects and synthetic credentials. No live model inference, account replacement or revocation of a personal account was performed.

The final executable passed the laptop solid, scaled light mesh and large solid UI scenarios. Native assertions cover Enter/Shift+Enter, IME/autorepeat handling, multi-component picking and individual context removal, separate Archive/Trash views, account details distinct from Settings, searchable model choice, usage cards, notifications outside chat, and reader-controlled scrolling with the latest-message button. A bounded triangle-ray fallback resolves mesh face picks that the native detector misses. Activity and token displays in screenshots are fixtures; geometry, picking and rendering are real. Reports and screenshots remain under ignored artifacts/validation. No installer was generated.
