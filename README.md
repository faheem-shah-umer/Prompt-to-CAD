<img src="frontend/public/app-icon.svg" width="88" alt="Purple pyramid icon">

# Prompt to CAD

**Describe a design. Build editable CAD. Select a part and refine it.**

Prompt to CAD is a Windows desktop prototype that turns natural-language descriptions into parametric parts and assemblies. It combines a user-configured LLM with a local CadQuery engine, saves the construction history, and exports STEP and STL files.

## What it does

- Creates separate, selectable components with named parameters and ordered feature histories.
- Plans assemblies in stages, constructs small groups of components, and repairs rejected plans using schema and geometry feedback.
- Supports sketches, extrusions, revolutions, lofts, sweeps, drilling, boolean operations, fillets, chamfers, patterns, mirrors and geometric helical threads.
- Applies conversational edits to a selected part or the whole assembly, then rebuilds parameter dependencies.
- Keeps parts attached to a parent's bounding face through dimension edits, with actual contact and overlap verification.
- Checks solids, expected dimensions, assembly relationships and STEP re-import before accepting a revision.
- Saves projects with undo/redo and exports STEP, STL, editable `.cad.json` and verification reports.
- Runs in a native WebView2 window with an animated startup screen and a hidden local backend.

This is an engineering learning project and an extensible CAD prototype. It does **not** guarantee correct interpretation of every prompt. General assembly constraint solving, face/edge selection and STEP import are not implemented. Geometry checks do not establish strength, manufacturability or standards compliance; the thread tool is a geometric demonstration.

## Quick start — Windows

### Requirements

- Python **3.11** with pip.
- Node.js **24** and npm.
- Microsoft Edge [WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/).
- Your own OpenAI-compatible chat API or local inference server for natural-language creation and editing. Opening the supplied CAD examples does not require inference.

From the root of a **fresh clone**, open PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
Copy-Item backend\.env.example backend\.env
```

Edit `backend/.env` with your own connection. No endpoint, model or credentials are supplied with this repository:

```dotenv
LLM_BASE_URL=https://your-provider.example/v1
LLM_MODEL=your-model-id
LLM_API_KEY=your-own-key
LLM_PROVIDER=custom
LLM_JSON_MODE=false
LLM_TIMEOUT_SECONDS=90
```

Install the frontend and build the desktop interface:

```powershell
Push-Location frontend
npm.cmd ci
Pop-Location
& '.\Setup desktop.cmd'
```

Then double-click **`Prompt to CAD.vbs`**. The application opens without a command window or browser tab. Closing the window stops its own backend. You can also run the desktop entry point with `.\.venv\Scripts\pythonw.exe -B desktop-app.py` or create your own shortcut to it.


`LLM_BASE_URL` is the API base path; the app appends `/chat/completions`. `LLM_PROVIDER` is an optional display label. Set `LLM_JSON_MODE=true` only if the endpoint supports JSON-object response formatting. Responses are always checked as JSON and validated against the CAD schema. The model must follow structured instructions reliably.

For a local [Ollama server](https://docs.ollama.com/api/openai-compatibility), use `LLM_BASE_URL=http://localhost:11434/v1`, set `LLM_MODEL` to a model you installed, and leave `LLM_API_KEY` blank. Other servers must expose a compatible chat-completions endpoint; APIs with a different protocol need an adapter.

Keep real settings in `backend/.env`, which Git ignores. Keys and endpoint URLs stay on the backend. Hosted requests send the prompt and relevant design context to your chosen service; local inference uses your local server. Provider fees and model licences are your responsibility. Creation uses an assembly brief followed by component batches. Invalid plans can be repaired by the same configured model, with at most three attempts per stage and 24 requests per action. Quota, authentication, network and timeout failures stop the action; there is no model or provider fallback.

## Try the workflow

1. Choose **Open → Open .cad.json file** and open an example:
   - [Spindle assembly](examples/spindle-assembly.cad.json): separate parts, patterned holes, a lofted grip and dependent placements.
   - [Threaded bolt](examples/threaded-bolt.cad.json): a hexagonal head, swept helical thread and chamfer.
   - [Gaming controller reference](examples/gaming-controller.cad.json): ten separate components, elliptical grips and a parameterised button diamond. This example was authored as a geometry regression fixture.
   - [Model-generated controller](examples/gaming-controller.generated.cad.json): the live model result from the detailed [controller prompt](examples/gaming-controller.prompt.txt), with ten parts and editable construction history.
2. Click a component in the viewport or parts tree to inspect its dimensions and features.
3. With your LLM configured, select the spindle and ask: **“Make this spindle 48 mm tall and keep its diameter unchanged.”**
4. Inspect the result, try Undo/Redo, and export STEP or an editable project.

For a new design, describe its parts, dimensions, positions and connections in **Explain Our Idea**, then choose **Create**. The interface shows planning, component construction and verification progress. Review any questions or assumptions. Failed actions offer a generation-details download and preserve the accepted revision. Selected-part edits protect other component definitions; an existing dependency may still move or resize a dependent part. Assembly mode permits broader changes.

## How it works

```text
Description or selected-part edit
  → Assembly brief or selected-part edit
  → Small component recipes from the configured LLM
  → Pydantic validation and typed changes
  → Parameter and dependency resolution
  → CadQuery feature construction
  → Solid and assembly checks → bounded repair on failure
  → STEP export and re-import checks
  → Saved revision and selectable Three.js preview
```

The LLM proposes structured operations. The application executes its own modelling tools; it does not execute model-generated Python. CAD construction runs locally on the CPU. Inference uses the endpoint you configure.

| Layer | Technology |
| --- | --- |
| Desktop window | pywebview + Microsoft WebView2 |
| Interface and selection | React, TypeScript, Three.js |
| API and input validation | FastAPI, Pydantic |
| Geometry | CadQuery / OpenCascade |
| Inference | Your own OpenAI-compatible endpoint and model |
| Storage | Local JSON revisions and STEP/STL files |

See [Generation pipeline](docs/generation-pipeline.md) for the staged workflow and comparison with Meshra and Yo.Town, [Architecture](docs/architecture.md) for the construction format and supported operations, and [Script guide](docs/script-guide.md) for file roles and API exercises.

## Development and tests

Run the API from the project root:

```powershell
.\.venv\Scripts\python.exe -B -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
Set-Location frontend
npm.cmd run dev
```

Open [the development interface](http://127.0.0.1:5173) or [API documentation](http://127.0.0.1:8000/docs). After frontend changes, run `npm.cmd run build` in `frontend/` and reopen the desktop app.

```powershell
# From the project root; provider calls are mocked in the test suite.
.\.venv\Scripts\python.exe -B -m unittest discover -s backend\tests -v
Push-Location frontend
npm.cmd run build
Pop-Location
```

Tests exercise actual CAD construction, STEP exchange, editing scope, dependencies, revision handling and desktop lifecycle. They do not establish success on arbitrary natural-language requests.

## Repository layout

```text
backend/               API, planner, geometry, tests and dependency files
frontend/              React interface, original icon artwork and npm lockfile
examples/              Editable CAD example specifications
docs/                  Architecture and script guide
desktop-app.py         Native desktop launcher and private backend
Prompt to CAD.vbs      Double-click Windows entry point
Setup desktop.cmd     Desktop dependency installation and frontend build
requirements-desktop.txt
LICENSE
```

Saved designs (`projects/`), earlier exports (`runs/`), generation journals (`generation-jobs/`), diagnostics (`tmp/`), API keys, installed dependencies and build output are local data and ignored by Git. An exported `.cad.json` contains the current design; reopening it creates a new project, while reopening a locally saved project retains its revision timeline.

## Licence

Source code, documentation and the newly drawn pyramid artwork are provided under the [MIT licence](LICENSE). Third-party dependencies retain their own licences. See [Third-party notices](THIRD_PARTY_NOTICES.md).
