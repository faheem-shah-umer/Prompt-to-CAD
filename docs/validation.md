# Validation

Run the automated backend, native UI and tracked-file checks:

```powershell
.venv\Scripts\python.exe -m tools.validate
.venv\Scripts\python.exe -m tools.validate_ui
.venv\Scripts\python.exe -m tools.check_privacy
```

The backend suite checks CAD operations, geometry validity, selection scope, persistence, undo/redo, provider protocol/authentication fixtures and Windows process ownership. It generates fresh synthetic models instead of reading saved user designs. The native UI check creates a synthetic solid assembly and mesh, then exercises topology picking, settings lifecycle, project-dialog re-entry, immediate draft clearing, later-draft preservation, collapsed work summaries, reported-token display, and three display layouts/scales. Activity/message fixtures are explicitly labelled in the reports and do not start provider inference.

Reports, screenshots, fixtures and generated models are local outputs under ignored artifacts/ and tmp/ directories. They must not be committed or copied into public source or the release. Previously retained runs and example models were preserved outside the repository with the saved designs.

A live plan-usage check is optional and explicitly consumes the selected account's allowance:

```powershell
.venv\Scripts\python.exe -m tools.validate_live --execute
```

It uses an isolated local project and keeps conversation/task records out of Git. A passing protocol fixture does not establish a successful live sign-in or model request. Review local reports for the exact checks performed. The installer remains unsigned.
