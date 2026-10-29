# Prompt to CAD V2 — text CAD workspace

## Setup and launch

Windows x64, Python 3.11 and the dependencies in requirements.txt are required for a source checkout. Native rendering uses Qt 6.9 and OpenCascade 7.8.1. The geometry worker uses CadQuery 2.7 / cadquery-ocp 7.8.1.1.post1. Keep these OCCT versions aligned so face and edge maps match the viewer.

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe tools\build_native.py --test
.venv\Scripts\python.exe native-app.py
```

The launcher detects the configured SDK directories, or accepts CAD_QT_PREFIX and CAD_OCCT_PREFIX. This checkout retains the current OCCT SDK under .native-runtime and the portable MSVC/NSIS tools under .build-tools. A standard x64 Visual Studio developer environment can also be used. Fresh compiler checks explicitly use Release configuration, matching the portable toolchain. An installed Codex CLI is required for agent tasks. The app discovers codex.exe on PATH or the local Codex binary installation; Settings → Diagnostics can select an explicit executable and test the local protocol handshake. A handshake does not verify model inference or account entitlement.

## Connections and billing

Exactly two connection choices are exposed in Settings → AI connection.

**ChatGPT subscription — Codex.** Continue with ChatGPT opens the system browser for this application's OAuth registration and plan-use permission. The flow uses a stable installation host ID, loopback callback, PKCE, state and nonce. The app validates the signed identity, saves its own registration, and requires the granted chatgpt.tokens.use.direct scope before inference. Existing desktop sign-in is not borrowed. Reconnect uses the saved registration. Windows DPAPI protects access/refresh tokens. Refresh is serialized, and a new App Server process receives the renewed access token before resuming its local thread. A terminal refresh failure requires reconnecting; it never selects API billing.

**OpenAI API key — separately billed.** Paste a user-supplied key only into the masked settings field. Validate and connect checks the authenticated model catalogue before storing the key with DPAPI. This check does not spend inference tokens and does not prove that every listed model is usable. A successful inference turn verifies access for that request. This mode uses the same App Server adapter and CAD tools. Invalid credentials preserve the prior selected connection.

Connection actions apply immediately; closing or cancelling Settings does not undo an already completed sign-in or disconnect. Save applies the staged display/runtime preferences once. Cancel or the window close control discards unsaved display/runtime preferences. Repeated settings activation focuses the existing dialog.

Tasks consume the chosen plan allowance or API credits; long tasks may consume more. A provider usage limit stops inference and preserves accepted geometry. Manage usage opens the corresponding provider usage page. Percentages and reset times are not invented: this route currently reports usage unavailable. Workspace names are shown only if reported; otherwise the app labels the saved registration and says the workspace name was not reported.

OpenAI currently documents this plan-use route for open-source and locally hosted applications. Paid or remotely hosted distribution requires following OpenAI's interest/approval process. Eligibility remains subject to the user's plan, workspace and policy; completing a supported turn is the access check. See [plan usage](https://developers.openai.com/siwc/token-sharing-open-source), [App Server configuration](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server), [limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations), and [recovery](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery). No developer inference key or Codex executable is embedded in the package.

## Workspace

The application bar identifies the project/document, exposes document tabs, Save, Undo, Redo and command search. Accepted changes and conversation records save atomically; Save confirms the current saved state. The navigation rail toggles projects, the CAD manager and the conversation. Panels resize with splitters and their layout is retained. Navigation is collapsed by default to prioritize the model, and secondary panes collapse at smaller laptop widths.

Project navigation contains projects and their chats. It is separate from the model tree. Context menus rename/archive items; recoverable trash retains project files. Multiple chats can share one document. Switching chats reads the actual current revision instead of restoring a prior chat's geometry. The model manager contains actual assembly components, visibility, properties, available named parameters and accepted revisions. Imported STEP files do not acquire invented original feature history.

Orbit with left drag; pan with middle drag or Shift+left; zoom with the wheel or right drag. Fit and standard views are above the viewport. Choose Body, Face or Edge selection; Ctrl adds supported edges. Hide/isolate/show and shaded edges are in View. For imported meshes, Face mode selects explicit triangles, not semantic parts. Measurement between two components is available in Inspect; interactive section views remain future scope.

The conversation shows its persisted title/history, a removable selection chip, model selector, Send/Stop and compact observable activity. Expand Activity details for the task log. Internal viewport observations depict the submitted base revision, not regenerated candidate screenshots. Change cards link affected components and accepted revisions. Restoring a revision changes geometry and is undoable according to document history.

## Geometry and task guarantees

The task freezes project/document/revision, instance/body/entity references, units, measurements and coordinate placement. Candidate IDs change after successful writes. Tools reject stale references and writes outside the selected component. Restricted scripts provide CadQuery geometry without arbitrary Python imports, shell, file or network access. They retain source and named parameters where available; direct edits can invalidate parameter regeneration and are guarded.

App Server completion is checked from structured turn status. A successful provider turn with no geometry is labelled no change. Candidate geometry is accepted only after geometry/export validation and unrelated-component checks. Cancellation closes the task's tool boundary and is checked again under the revision acceptance lock. Revision compare-and-swap prevents a delayed task from overwriting a newer revision. Per-document locks serialize writers across windows. One submission ID cannot execute twice. Stream events carry task/conversation/document IDs and the UI ignores mismatched events.

Task timeout and the 32-operation budget are application limits, separate from provider allowance. Failed/cancelled tasks retain their outcome and preserve the accepted revision. Reopening marks abandoned running tasks interrupted when no process owns the document lock. The root process uses a Windows job for descendant cleanup; App Server and geometry workers are also closed explicitly.

## Files and compatibility

Engineering import: STEP/STP and the application's editable JSON recipes. Mesh import: GLB, STL, OBJ, PLY with explicit unit scaling. Solid export: STEP/STL; mesh export: GLB/STL. No DWG, proprietary feature-history reconstruction, full sketch constraint solver or arbitrary mesh-to-solid conversion is promised.

Data defaults to %USERPROFILE%/.promptcad/v2. PROMPTCAD_HOME selects an isolated data directory for testing. Project, document, conversation, task and revision IDs are distinct. Atomic JSON saves, asset hashes and recovery journals are retained. Existing models/reference assets are preserved. The retired image-service credential is removed from the protected vault during migration; active image-generation routes and tool definitions are absent. No image generation dependency was exclusive to that adapter: HTTPX remains needed by OAuth/provider calls and mesh libraries remain needed for existing imported models.

## Build, package and validate

```powershell
.venv\Scripts\python.exe -m tools.validate
.venv\Scripts\python.exe -m tools.validate_ui
.venv\Scripts\python.exe -m tools.package_native --help
```

The packaging tool creates a 0.4.0 runtime with Python, Qt/OCCT libraries, dependency licences and application source. A separate installed Codex executable and user authorization are still required. The installer is unsigned. Current retained evidence lives under artifacts/validation; See validation.md for which current runs passed and which external checks remain pending.
