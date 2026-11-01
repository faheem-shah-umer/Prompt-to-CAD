# Prompt to CAD — CAD workspace

The agentic-capabilities branch adds restructuring, colours, engineering records and image reference inputs in source. See [agentic CAD capabilities](agentic-cad.md) for the contracts and pending checks. The local executable now includes these native UI changes after an explicitly requested rebuild. Tests, live inference and UI verification remain pending.

## Source-only development

Keep this checkout focused on source. Do not build, package, generate launchers or run automated/UI/live tests unless the user explicitly requests that work. When testing is requested, target the named task rather than automatically running every suite. Runtime CAD validation remains part of modelling operations.

Windows x64, Python 3.11 and requirements.txt are the source dependencies. Native rendering requires Qt 6.9 Widgets/SVG and OpenCascade 7.8.1. Geometry uses CadQuery 2.7 / cadquery-ocp 7.8.1.1.post1. Matching SDKs and a Visual Studio x64 toolchain must be configured separately when a native build is requested; repository-local SDK/toolchain downloads have been removed.

Double-click **Prompt to CAD.lnk** at the repository root to open the local app. Its **Prompt to CAD.vbs** launcher runs **../Prompt-to-CAD-build/bin/PromptToCAD.exe** against this repository's backend and existing **.venv/**. The build-folder name follows the checkout folder name with a -build suffix. The shortcut uses our original logo. The earlier .app-runtime files are preserved but are no longer the launcher target. Toolchain, generated build output and runtime dependencies remain outside the checkout. This explicitly requested rebuild does not enable automatic tests. There is no installer.

The build script remains available for an explicitly requested future build and accepts CAD_QT_PREFIX and CAD_OCCT_PREFIX. It does not generate launchers or shortcuts. An installed Codex CLI is required for agent tasks; account and project storage remain separate from generated build outputs.

## Connections and billing

First launch explains Codex and offers Continue with ChatGPT or Skip for now. Skipping keeps local CAD tools available and can be followed by connection setup later. Returning users enter an empty workspace; select a project and conversation explicitly. An explicit file-opening launch still opens the requested file.

Exactly two connection choices are exposed in Settings → AI connection.

**ChatGPT subscription — Codex.** Continue with ChatGPT opens the system browser for this application's OAuth registration and plan-use permission. The flow uses a stable installation host ID, loopback callback, PKCE, state and nonce. The app validates the signed identity, saves its own registration, and requires the granted chatgpt.tokens.use.direct scope before inference. Existing desktop sign-in is not borrowed. The main connection action reuses the preferred registration, including after disconnect. Previous registrations remain separate under Advanced; identical emails never cause credentials to be merged. Revoke session reports whether remote revocation was confirmed and retains the client mapping for reconnecting. Manage ChatGPT access opens the provider settings; revoking a renewable session does not remove the app registration there. Windows DPAPI protects access/refresh tokens. Refresh is serialized, and a new App Server process receives the renewed access token before resuming its local thread. A terminal refresh failure requires reconnecting; it never selects API billing.

**OpenAI API key — separately billed.** Paste a user-supplied key only into the masked settings field. Validate and connect checks the authenticated model catalogue before storing the key with DPAPI. This check does not spend inference tokens and does not prove that every listed model is usable. A successful inference turn verifies access for that request. This mode uses the same App Server adapter and CAD tools. Invalid credentials preserve the prior selected connection.

Connection state is updated from authorization events without background status polling. Model discovery is coalesced and cached for ten minutes per account, with explicit Refresh models. Connection checks do not run inference.

Connection actions apply immediately; closing or cancelling Settings does not undo an already completed sign-in or disconnect. Save applies the staged display/runtime preferences once. Cancel or the window close control discards unsaved display/runtime preferences. Repeated settings activation focuses the existing dialog.

Tasks consume the chosen plan allowance or API credits; long tasks may consume more. A provider usage limit stops inference and preserves accepted geometry. Manage usage opens the corresponding provider usage page. Percentages and reset times are not invented: this route currently reports usage unavailable. Workspace names are shown only if reported; otherwise the app labels the saved registration and says the workspace name was not reported.

OpenAI currently documents this plan-use route for open-source and locally hosted applications. Paid or remotely hosted distribution requires following OpenAI's interest/approval process. Eligibility remains subject to the user's plan, workspace and policy; completing a supported turn is the access check. See [plan usage](https://developers.openai.com/siwc/token-sharing-open-source), [App Server configuration](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server), [limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations), and [recovery](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery). No developer inference key or Codex executable is embedded in the package.

## Workspace

The application bar shows the project name once, document tabs, icon-only Undo/Redo and command search. File → Save (Ctrl+S) checkpoints the accepted state without adding a revision. File → Save As (Ctrl+Shift+S) creates an independent named project copy inside Projects, including its documents, revisions, chats, tasks and reference assets. Identifiers and structured links are rewritten; provider sessions are cleared. Only a validated copy becomes active. Accepted changes and conversation records save atomically; Save confirms the current saved state. The navigation rail toggles projects, the CAD manager and the conversation. Panels resize with splitters and their layout is retained. Navigation is collapsed by default to prioritize the model, and secondary panes collapse at smaller laptop widths.

Project navigation contains projects and their chats. It is separate from the model tree. Context menus rename/archive items; recoverable trash retains project files. Multiple chats can share one document. Switching chats reads the actual current revision instead of restoring a prior chat's geometry. The model manager contains actual assembly components, visibility, properties, available named parameters and accepted revisions. Imported STEP files do not acquire invented original feature history.

Sort projects beside navigation search offers Recently changed (the default), Name A–Z, Name Z–A, Newest created and Recently opened. The choice is retained. Opening a project updates only its last-opened time; it does not reorder the underlying catalogue or count as a content change. Geometry edits/imports, undo/redo, restored revisions, messages, renames and conversation lifecycle changes update content-change time. Connection/session refresh, unchanged Save, visibility and selection do not. Older healthy projects receive missing timestamps once from existing creation and document/conversation file dates.

The model tree has separate Show all/Hide all and Select all visible/Clear selection controls. They operate across the current document even when tree filtering hides rows. Select all visible switches to Body mode, excludes hidden components and leaves the selection unchanged if more than 256 visible components would exceed the task context limit. Hide and Isolate synchronize with the checkboxes; hiding a selected component removes it from pending task context. Running tasks retain their submitted selection. Visibility is retained per document for the current application session, including surviving component IDs across revisions. Showing a model restores its shaded presentation, colours and current solid-edge setting.

Orbit with left drag; pan with middle drag or Shift+left; zoom with the wheel or right drag. Fit and standard views are above the viewport. Choose Body, Face or Edge selection; Ctrl adds supported edges. Hide/isolate/show and shaded edges are in View. For imported meshes, Face mode selects explicit triangles, not semantic parts. Measurement between two components is available in Inspect; interactive section views remain future scope.

The conversation shows its persisted title/history, a removable selection chip, model selector, Send/Stop and compact observable activity. Expand Activity details for the task log. Internal viewport observations depict the submitted base revision, not regenerated candidate screenshots. Change cards link affected components and accepted revisions. Restoring a revision changes geometry and is undoable according to document history.

Loads lasting more than about 200 ms show a small labelled spinner. Conversation loads appear inside the chat panel; project/document loads and other workspace operations appear in the status bar. Fast operations show no spinner, and completed/failed operations hide it immediately. The indicator follows the Windows animation preference and keeps a static loading ring/text when client-area animations are disabled.

## Geometry and task guarantees

The task freezes project/document/revision, instance/body/entity references, units, measurements, coordinate placement and submitted images. Candidate IDs change after successful writes. Tools reject stale references and writes outside the authorized component set. Explicit restructuring transactions can consume selected bodies and create authorized outputs. Controlled scripts provide CadQuery geometry without arbitrary Python imports, shell, file or network access. Versioned project definition tools retain editable source and named parameters; direct edits can invalidate regeneration and are guarded. Colours, dimensions, tolerances and annotations have separate revision-owned metadata and validation paths.

App Server completion is checked from structured turn status. A successful provider turn with no geometry is labelled no change. Candidate geometry is accepted only after geometry/export validation and unrelated-component checks. Cancellation closes the task's tool boundary and is checked again under the revision acceptance lock. Revision compare-and-swap prevents a delayed task from overwriting a newer revision. A project-root lock serializes geometry and lifecycle writes across windows, alongside per-document geometry locks. One submission ID cannot execute twice. Stream events carry task/conversation/document IDs and the UI ignores mismatched events.

Task timeout and the 32-operation budget are application limits, separate from provider allowance. Failed/cancelled tasks retain their outcome and preserve the accepted revision. Reopening marks abandoned running tasks interrupted when no process owns the document lock. The root process uses a Windows job for descendant cleanup; App Server and geometry workers are also closed explicitly.

## Files and compatibility

Engineering import: STEP/STP and the application's editable JSON recipes. Mesh import: GLB, STL, OBJ, PLY with explicit unit scaling. Solid export: STEP/STL; mesh export: GLB/STL. No DWG, proprietary feature-history reconstruction, full sketch constraint solver or arbitrary mesh-to-solid conversion is promised.

Projects default to Projects/<project name>/ in the repository, or beside a packaged application. Duplicate names receive a numeric suffix; Windows-reserved filename characters are sanitized. Documents use project-relative paths so a project folder can be moved with its conversations. Runtime preferences and provider state use the ignored .promptcad/ folder. Existing account credentials remain protected by Windows in user storage; existing older project locations are preserved. PROMPTCAD_HOME selects an isolated data directory for testing, and PROMPTCAD_PROJECTS_DIR can explicitly override the project root. Project, document, conversation, task and revision IDs are distinct. Atomic JSON saves, asset hashes and recovery journals are retained. Existing models/reference assets are preserved. The retired image-service credential is removed from the protected vault during migration; active image-generation routes and tool definitions are absent. No image generation dependency was exclusive to that adapter: HTTPX remains needed by OAuth/provider calls and mesh libraries remain needed for existing imported models.

## Explicitly requested native build

The local restoration uses the existing Qt SDK at %USERPROFILE%/anaconda3/envs/occenv/Library, isolated compiler at ../Prompt-to-CAD-toolchain/msvc/VC/Tools/MSVC/14.40.33807/bin/Hostx64/x64/cl.exe, Windows SDK 10.0.22621.0, and exact OCCT 7.8.1 SDK at ../Prompt-to-CAD-toolchain/occt-7.8.1/Library. The installed OCCT 7.9.0 SDK is preserved and is not used for this build. No existing toolchain was deleted or moved.

```powershell
.venv\Scripts\python.exe -m tools.build_native `
  --qt-prefix "$env:USERPROFILE/anaconda3/envs/occenv/Library" `
  --occt-prefix "../Prompt-to-CAD-toolchain/occt-7.8.1/Library" `
  --toolchain-env "../Prompt-to-CAD-toolchain/environment.json" `
  --build-dir "../Prompt-to-CAD-build"
```

Use absolute SDK paths or resolve them from the checkout when configuring another build directory. The build script defaults to a sibling build folder and runs application tests only with the explicit --test flag. Runtime Qt plugins and matching OCCT libraries/shaders must be deployed beside the executable; the build command does not package or download them.

## Separately requested packaging and validation

```powershell
.venv\Scripts\python.exe -m tools.validate
.venv\Scripts\python.exe -m tools.validate_ui
.venv\Scripts\python.exe -m tools.package_native --help
```

The packaging tool creates a 0.4.0 runtime with Python, Qt/OCCT libraries, dependency licences and approved application source. User projects, chats, CAD files, screenshots and account data are excluded. A separate installed Codex executable and user authorization are still required. Installer tooling uses an explicit approved file inventory and excludes Projects/, .promptcad/, chats and user assets. No installer is built during development; installer creation is reserved for the final release. Validation generates ignored local evidence under artifacts/validation; see validation.md.

## Workspace preferences

Settings uses separate AI connection, Appearance, Projects, CAD display and Advanced pages. Select Dark or Light in Appearance and save. Theme, text size and panel preferences persist. The logo is shown during startup and in the Windows icon; the workspace navigation rail contains controls rather than a logo.

The conversation panel places rounded user bubbles on the right and unboxed Codex replies on the left. Enter sends, Shift+Enter inserts a newline, and Enter autorepeat or active IME composition does not submit. Reading older messages suspends automatic scrolling; the down-arrow returns to the latest response. Application notices use deduplicated icon notifications outside the chat. Model choice uses a searchable popover and reported usage opens an information card. The avatar opens account details; the gear opens Settings. A single control changes from Send to a square Stop icon during agent work and disables while cancellation completes. Enter only sends when idle. Sent text clears immediately; a draft typed during a task is retained. Activity appears inline while a task runs and collapses into a persisted Worked for duration afterward. The badge shows reported tokens, or an allowance window only when actually reported. It stays hidden when neither exists; no unavailable allowance or refresh control is shown. Provider billing links remain in Settings. See the official [App Server usage interface](https://learn.chatgpt.com/docs/app-server) and [authorized plan-provider configuration](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server).

Each nonempty user or assistant message has a copy icon that copies its original text/Markdown without activity or revision controls; streaming replies copy the text currently shown. The header and assistant author labels use runtime/task provider metadata. Persisted replies retain the provider identity captured for that task; historical replies without metadata remain labelled Codex, and unknown provider metadata falls back to Assistant. This adds no second provider integration. The model trigger sizes to its name with an adjacent dropdown arrow, caps its width at 240 logical pixels, elides longer labels and exposes the full name in its tooltip; search and refresh remain in its popover.

Use Open project to copy an older project folder into Projects/ with its chats and documents. The original is preserved. New project folders use their creation name; the Projects settings page and project context menu reveal their actual locations.

The Projects folder is the source of truth. Startup and window activation reconcile valid project folders with the catalogue: added projects appear, renamed folders retain their IDs and chats, and externally removed folders disappear. Corrupt metadata is reported in Settings → Projects without blocking healthy projects. The catalogue is a rebuildable cache, not a second copy of project content.

Move to trash hides a project or conversation while retaining its local files. Tools → Manage archived and deleted items provides Restore and Delete permanently. Permanent deletion requires a named confirmation: a project removes its local folder, while a conversation removes its transcript and task records but preserves shared CAD geometry and revisions. Restoring does not open a project automatically. Deleting or trashing the active project clears the workspace; removing the active chat clears its panel. A document can have no chats until the user starts one.

New conversation (Ctrl+Shift+N) opens and focuses the chat panel even when it was hidden or collapsed. Selecting an existing conversation also reveals the panel. With no active project, New conversation opens the named-project dialog first. Conversations within a project continue to reference the same CAD document.

## Selection and conversation library

Ctrl+click toggles supported CAD entities across components; model-tree Ctrl/Shift selection selects multiple bodies. The selection context menu removes individual entities or clears the set. The task receives every selected entity with a revision-bound reference and local/world context. Body selections authorize supported component edits. Face, edge and mesh-region selections constrain tool target references. A script cannot silently broaden a face selection. Atomic face batches support planar offsets and holes resolved before editing; modified sub-entity references require fresh selection when no verified mapping exists. Other components are checked before acceptance.

Ctrl/Shift-select conversation rows to archive or trash a batch without opening another conversation. Tools → Archive and Tools → Trash have separate views. Restoring a trashed archived conversation returns it to Archive; restoring it again from Archive returns it to active navigation. Bulk results report failures individually. Permanent chat deletion preserves shared documents and accepted geometry.

Settings → AI connection offers an explicit Connect a new account action. It creates a new **Prompt to CAD** registration only after the user chooses it; the existing connection remains active until validation succeeds. Routine startup and tasks reuse and refresh the current client. Settings → Advanced lists only previous registrations, with Use and delete controls. Deleting an old saved connection attempts session revocation and removes its local protected record, while preserving the primary connection. Local deletion/revocation cannot delete an app registration or rename an old label in ChatGPT; manage those entries in ChatGPT Settings. Cross-window authorization is serialized.
