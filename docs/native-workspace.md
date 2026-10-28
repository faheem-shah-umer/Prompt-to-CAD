# Native CAD workspace

The native workspace is the Windows application built on C++20, Qt 6 and OCCT 7.8.1. A Python document service handles commands and conversations; an isolated CadQuery/OCP process constructs geometry. The original React/pywebview application remains available through its existing launcher.

## Run it

On the configured development machine, double-click **Prompt to CAD Native.vbs**. The compiled application is in `.native-build/PromptToCAD.exe`. The launcher supplies the SDK runtime paths. Opening the executable directly from that build directory requires those paths in the environment.

A packaged installation includes its own Python, Qt and CAD runtime. Start **Prompt to CAD Native** from the Start menu after installation. Source builds and packaged installations both save projects under the user's local application-data directory, in `PromptToCAD/projects/`.

Use **Settings → Model connection** to choose an OpenAI-compatible API base URL, model and optional API key. Blank keys retain the current key only for the same endpoint. Settings are stored locally in `%LOCALAPPDATA%/PromptToCAD/model.json`; they are excluded from packages. Existing development `backend/.env` settings continue to work when no native model configuration overrides them. Geometry construction and viewing do not require a model connection.

## Editing workflow

1. Choose **File → Open STEP / editable CAD** for a solid STEP model or an existing `.cad.json` recipe. **Open native project directory** reopens a saved version-2 project.
2. Orbit with left-drag, pan with the middle button or Shift-drag, and zoom with the wheel. Use the selection list for bodies, faces, edges or vertices. Ctrl-click selects multiple edges.
3. Describe a change in the conversation panel and press **Run** or Ctrl+Enter. A selection scopes the request to that component instance.
4. The agent inspects current geometry, calls typed tools, reads the new geometry and continues. Tool messages show progress. The completed request becomes one accepted revision after solid and STEP round-trip checks.
5. **Undo / Redo** restores accepted geometry. **Export STEP / STL** writes outside the project directory. **Save project copy** creates a portable project directory without overwriting its source.

The **Model** menu exposes the same tools used by the agent:

| Tool | Behaviour |
| --- | --- |
| Holes | Positive bounding-face drilling along local X/Y/Z, with explicit centres; zero depth in the dialog means through. |
| Fillet / chamfer | Selected current-revision edges; invalid sizes leave the accepted solid unchanged. |
| Extrude / cut | A closed planar polygon at an explicit local origin; the dialog uses the local XY plane. The agent tool also accepts arbitrary plane axes. |
| Patterns | Linear or circular copies including a new hole/extrusion seed; the manual dialog patterns holes. |
| Boolean | Union, cut or intersection with another component; the tool component is retained. |
| Transform | World-origin XYZ rotation followed by world translation, applied to one instance. |
| Parameters | Existing named parameters of generated recipes. Undo downstream direct edits before changing an earlier parameter. |

Imported STEP bodies retain geometry and available assembly structure, names, colours, instances and placements. Their original sketches and feature history are not reconstructed. Subsequent direct edits are recorded by this application.

## Build and package

Use Python 3.11 and an x64 Microsoft C++ developer environment. The native build needs a Qt 6 MSVC SDK and an OCCT **7.8.1** SDK matching `cadquery-ocp==7.8.1.1.post1`. The current machine's SDKs are already configured. Override their paths with `--qt-prefix` / `--occt-prefix` or `CAD_QT_PREFIX` / `CAD_OCCT_PREFIX`.

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-native.txt -r native\requirements-build.txt
.\.venv\Scripts\python.exe tools\build_native.py --test
.\.venv\Scripts\python.exe -B -m unittest discover -s backend\tests -v
.\.venv\Scripts\python.exe -B -m tools.verify_native --benchmark
```

Opt-in live acceptance, using the configured provider:

```powershell
.\.venv\Scripts\python.exe -B -m tools.verify_native --live
```

Create a new package output directory and a per-user NSIS installer:

```powershell
.\.venv\Scripts\python.exe -B -m tools.package_native --smoke-test --installer "path\to\makensis.exe"
```

Packaging collects the required Python distributions, native DLL dependencies, source and licence files. It excludes credentials and user projects. The packaged smoke test runs with only Windows System32 on PATH. The installer is unsigned; it installs for the current user and does not require a development environment. Uninstall removes the installed file inventory and preserves user project/model settings.

## Document and process contracts

Version-2 projects are directories containing `project.json`, immutable revision manifests, content-addressed BREP assets, the original import, a conversation file and an interrupted-task journal. Save copies preserve relative asset references. Existing version-1 recipes are imported into new projects.

Both process boundaries use JSON-RPC 2.0 over standard input/output. Protocol version 1 is checked at startup. Native OCCT output is redirected to the geometry log so it cannot corrupt RPC frames. The interface and worker use the same persisted BREP traversal for revision-scoped body/face/edge/vertex references.

The public service methods are:

- `workspace.hello`, `workspace.model`, `workspace.configure`, `workspace.cancel`, `workspace.shutdown`
- `document.import`, `document.open`, `document.current`, `document.save_as`
- `document.inspect`, `document.command`, `document.generate`, `document.export`
- `document.undo`, `document.redo`, `agent.run`

Mutating existing documents requires `base_revision_id`. Optional selections include revision, instance, topology kind and index. Progress events report planning/modelling/verification; final responses distinguish completion, clarification and unsupported requests. Failed tasks do not partially commit. Invalid/stale references and unexpected new component intersections are rejected.

Geometry work has a configurable 120-second operation timeout (`CAD_GEOMETRY_TIMEOUT`). Agent tasks have a 24-request and ten-minute budget. Provider waits are cancellable. Geometry cancellation terminates the actual worker process, with a two-second kill fallback. The native application owns the service process tree through a Windows Job Object.

## Validation and limits

The acceptance fixture is an 80 × 60 × 8 mm STEP plate. The task adds four Ø6 mm through-holes on a centred 60 × 40 mm pattern and R2 outside vertical-edge fillets. Tests check analytical volume, dimensions, history, reopening and verified export.

`artifacts/native-validation/report.json` records live acceptance and representative 1/25/100-component benchmarks. `tmp/native-smoke-report.json` records actual native mouse-based face picking, topology maps and synthetic orbit rendering. The screenshot is `tmp/native-workspace.png`.

The current target is solid mechanical parts and modest assemblies. The 100-component measurements use simple solids and do not establish performance for every model with 100 parts. Recipe generation retains the existing 32-component/256-feature bounds. Model responses remain probabilistic; passing checks does not establish design intent, mechanical safety or manufacturing suitability.

Mesh editing, proprietary native CAD formats, original-feature reconstruction, a full sketch/constraint solver, drawings and collaborative/cloud editing are outside this release. Geometry inspection supplied to the agent is limited to the first 256 faces/edges per inspected component; complicated models may need manual selection or a smaller task.

References: [OpenCascade visualization](https://occt3d.com/dev/doc/overview/html/occt_user_guides__visualization.html), [FreeCAD architecture overview](https://github.com/FreeCAD/FreeCAD), [REA capabilities](https://github.com/faheem-shah-umer/rea). REA is an optional investigation tool; the implementation does not depend on decompiling AutoCAD.

### Recorded validation — 28 October 2026

The full backend suite passed 76 tests; the subsequent model-connection/worker-restart regression also passed. Native smoke checks passed on 1-, 25- and 100-component STEP scenes with actual mouse-based face picking and rendered screenshots. The configured model completed the imported plate task in 14.6 seconds; the final dimensions and analytical volume matched after STEP re-import. This is one successful model task, not a success-rate benchmark.

On this Windows machine (8 logical CPUs, 7.83 GB RAM), representative simple-solid fixtures measured:

| Instances | Import + STEP verification | Edit + STEP verification | Geometry-process RSS | Synthetic orbit |
| --- | ---: | ---: | ---: | ---: |
| 1 | 2.735 s | 0.172 s | 353 MB | 30 fps |
| 25 | 0.937 s | 0.860 s | 355 MB | 30 fps |
| 100 | 2.860 s | 2.687 s | 357 MB | 30 fps |

The first import includes cold worker startup; subsequent rows use a warm worker. RSS measures the actual interpreter rather than the Windows venv launcher. Orbit measurements cover 60 synchronous rendered frames and depend on the display/driver timing. Raw reports and fixture screenshots are retained under artifacts/native-validation.
