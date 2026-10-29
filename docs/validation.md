# Current validation

Run the current backend and native UI checks:

```powershell
.venv\Scripts\python.exe -m tools.validate
.venv\Scripts\python.exe -m tools.validate_ui
```

Reports and screenshots are retained in **artifacts/validation**. The cleaned backend suite passes **45 tests**. The suite covers the current V2 workspace, authentication/protocol fixtures, process ownership, selected-component scope, stale references, persistent revisions, mesh operations and shared CAD feature/geometry checks. Retired HTTP, web-planner, pywebview and earlier custom-agent tests have been removed with those applications; compare the retained capabilities rather than the old total test count.

The native UI check imports real solids/meshes and exercises topology picking, three display layouts, 125 settings activations per case, Cancel/reopen cycles, one Save request and a persisted changed preference. Tests use isolated writable preferences and synthetic projects.

Live checks require an explicit plan-usage choice:

```powershell
.venv\Scripts\python.exe -m tools.validate_live --execute
```

The retained live CAD reports demonstrate text creation, four diameter-6 holes on a selected plate, refinement from 8 to 13 mm thickness, unrelated-post preservation, conversation/session reopening and cancellation after a candidate change. A native UI submission moved only the selected post 20 mm along assembly X; its revision/task records verified one submission and unchanged plate geometry. These live runs preceded the repository-only extraction of shared code; the cleanup is revalidated without spending another model allowance.

A fresh OAuth browser sign-in, live API-billed inference and intentional account exhaustion/revocation were not performed in the retained runs. Those protocol/authentication failure paths use fixtures. Usage percentages are not inferred. The installer is unsigned; the documented capability limits still apply.

The cleanup report records removal of retired applications and preservation of design data. Current build/test/package results, rather than historical release reports, determine the final cleanup acceptance.
