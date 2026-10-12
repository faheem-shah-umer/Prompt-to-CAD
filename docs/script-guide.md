Start here: editable CAD projects
=================================

The app now stores **how a design is built**: parameters, ordered features, separate component IDs, placements and assembly relationships. STEP/STL are exports of that state. Start with [Architecture](architecture.md), then follow a request through the files below.

The table below maps the interface, API, planner, modelling engine and desktop launcher. Styles, configuration, tests and examples support these modules.

There are 24 main source files: 18 backend modules, five React/TypeScript modules and the desktop launcher. Read the generation planner, job routes and modeller together when following the new workflow.

| File | Role |
| --- | --- |
| `backend/app/main.py` | Creates FastAPI, registers project and legacy routes, serves the built interface. |
| `backend/app/project_api.py` | Create, open, edit, undo/redo, editable-JSON import and export endpoints. |
| `backend/app/design_schema.py` | Pydantic schemas for components, feature operations, placements, relationships and edit changes. |
| `backend/app/assembly_schema.py` | Plans component metadata and dependencies separately from local construction recipes. |
| `backend/app/design_planner.py` | Plans assemblies, requests component batches and repairs rejected JSON/geometry using measured feedback. |
| `backend/app/design_jobs.py` | Runs generation in a background worker; exposes progress, results and local diagnostics. |
| `backend/app/llm_client.py` | One configurable OpenAI-compatible chat request, backend-only credentials, timeout/quota errors, no provider fallback. |
| `backend/app/design_edits.py` | Applies a typed change list while protecting component IDs and selected-part scope. |
| `backend/app/parameters.py` | Resolves arithmetic and cross-part parameter dependencies; rejects cycles and executable expressions. |
| `backend/app/modelling.py` | Rebuilds feature histories, derives face attachments and checks actual component/assembly geometry. |
| `backend/app/projects.py` | STEP/STL exports, STEP re-import, atomic project commits, persistent revisions and undo/redo. |
| `backend/app/project_lock.py` | Prevents two native application windows from overwriting the same project concurrently. |
| `backend/app/config.py` | Workspace paths and local development origins. |
| `frontend/src/api.ts` | TypeScript contracts and relative API requests. |
| `frontend/src/components/PromptForm.tsx` | One Create/Apply action, idea/change editor and Ctrl+Enter. |
| `frontend/src/components/CadViewer.tsx` | Separate component meshes, raycast selection, highlighting, visibility and camera controls. |
| `frontend/src/App.tsx` | Project controls, selected editing scope, parts tree, inspector, revisions and exports. |
| `frontend/src/main.tsx` | React entry point and stylesheet loading. |
| `desktop-app.py` | Native window/icon and ownership of its private FastAPI backend. |
| `backend/app/schemas.py`, `planner.py`, `generation.py`, `service.py`, `cad.py` | Original plate exercises and shared prompt/CAD-lock utilities. |

What happens after Create
-------------------------

```text
PromptForm → App → api.ts → POST /api/design-jobs → HTTP 202 + job ID
  → design_planner: assembly brief → batches of up to three local feature recipes
  → React polls GET /api/design-jobs/{id} for progress
  → Parameters: resolve dimensions and dependencies
  → Builder: rebuild each component's ordered features
  → Verify solids, expected extents, relationships and interference
  → On rejected JSON/geometry: send feedback to the same model within a bounded budget
  → Export named STEP parts + per-component STL previews
  → Re-import STEP and check each part's volume and bounds
  → Atomically save the accepted revision
  → React displays selectable components and read-only inspection
```

For an edit, React sends the project ID, selected component ID and current revision ID to the same job endpoint. The configured LLM proposes typed changes. Dependent parts rebuild from their existing expressions. An invalid plan or geometry leaves the saved revision available; a stale revision returns HTTP 409. The synchronous project creation/edit routes remain available for API exercises.

FastAPI learning exercises
-------------------------

1. Start the backend and open [interactive API documentation](http://127.0.0.1:8000/docs).
2. Try `GET /api/health`, `GET /api/llm` and `GET /api/projects`.
3. Paste `examples/gaming-controller.generated.cad.json` into `POST /api/projects/from-spec`. This builds real geometry without inference.
4. Open the returned project's component preview URLs, STEP export and editable JSON.
5. Submit `POST /api/design-jobs` with `{"prompt":"Create a 40 mm diameter, 20 mm tall cylindrical knob"}`. Inspect its 202 response, then poll `GET /api/design-jobs/{id}`. Download the diagnostics after completion.
6. Try Undo/Redo and deliberately supply an old revision ID to see the 409 response.
7. Run the tests and read `backend/tests/test_projects.py` to see successful and rejected operations.

All dimensions in the current engine use mm. Rotations use degrees; trigonometric expressions use radians. The inspector shows measured extents and evaluated parameter values. Parameters can also represent angles, counts or ratios, so they are not all labelled mm.

For request validation, read [FastAPI request bodies](https://fastapi.tiangolo.com/tutorial/body/). Routes use synchronous `def` endpoints, which FastAPI runs in its thread pool; see [FastAPI concurrency](https://fastapi.tiangolo.com/async/). The job POST returns quickly after submitting work to a separate single-worker `ThreadPoolExecutor`. The polling GET does not run CAD or inference. CAD work is serialised. This is a local in-process worker, with no external queue service or restart recovery.

Launch and development
----------------------

See the [README](../README.md#quick-start) for a fresh installation, desktop launch, browser development and test commands. Run those commands from the project root. The launcher prefers the project `.venv` when available, and its desktop dependencies live in `.desktop-runtime`.

For everyday use, double-click **Prompt to CAD.vbs** or your local desktop shortcut. The built interface opens in a native WebView2 window. Closing it stops that window's backend. Each launch owns its local port and browser profile. After frontend changes, rebuild with `npm.cmd run build` in `frontend/` and reopen the application.

Tests mock provider responses and construct real CadQuery geometry. See `backend/tests/test_projects.py` for operation, editing, assembly and revision examples. The earlier plate API uses `backend/tests/fixtures/plate.json` as its test input.

Storage
-------

- `projects/<id>/project.json` holds the accepted revision cursor.
- `projects/<id>/revisions/<revision-id>/` holds the immutable specification, report, STEP, assembly STL and separate part previews.
- **Open** retains the saved project's revision timeline. **Editable project** saves the current construction specification; opening it creates a new project at revision 1.
- Creating a revision after Undo starts a new forward branch. Earlier branch files remain available, although Redo follows the active branch.
- A failed candidate never updates the accepted cursor. Its partial export files may remain for diagnosis.
- Earlier plate models remain in `runs/`.
- `generation-jobs/<id>/diagnostics.json` records candidate responses and validation feedback, including failed actions. It contains prompts/design context, but no API credentials. The directory is ignored by Git.

Read [Generation pipeline](generation-pipeline.md) next, then `backend/tests/test_design_jobs.py` for staged construction, failed-plan repairs and revision protection. Broader geometry assertions, face/edge references, a full assembly constraint solver and STEP import remain future work. CAD runs on the CPU. Hosted inference uses the provider's hardware; local inference hardware requirements depend on the chosen model.
