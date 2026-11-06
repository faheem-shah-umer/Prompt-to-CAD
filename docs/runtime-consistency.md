# Runtime consistency and standard-part tool delivery

The desktop, main Python service, MCP server and geometry workers must load the same checkout. Updating files does not hot-reload a running Python service. In particular, the service retains its imported tool definitions and CAD instruction text until restarted.

## Launcher and interpreter chain

`Run-PromptToCAD.cmd` is the only launcher. It runs `tools.run_native`, which starts `build/bin/PromptToCAD.exe --workspace <checkout>` with the runtime library paths. The desktop service defaults to `<checkout>/.venv/Scripts/python.exe -B -m backend.v2.service`. On Windows that venv executable can delegate to its base Python interpreter; the venv's package configuration still applies.

The native RPC launcher pins the working directory, `PYTHONPATH` and `PROMPTCAD_WORKSPACE` to that checkout and disables user-site imports. MCP uses the real windowless interpreter with an explicit source/package search path. Geometry workers use the real interpreter where needed, with the same source root and package search paths. No SDK, CadQuery or OCP version change is required.

## Checks before execution

The main service records its loaded instruction/tool identities and a SHA-256 fingerprint over production backend sources. Before a new AI turn, it checks that those files and instructions still match. Source changes require closing and reopening the app; stale code is not silently used or reloaded into an active design task.

MCP checks the source root, source fingerprint and actual tool-schema fingerprint expected by the parent service. On `tools/list`, it verifies its identity with the authenticated application bridge before returning the registry. Calls without that handshake are rejected. A modelling turn cannot be accepted without verified MCP tool delivery. The required registry includes `cad_standard_parts` and `cad_standard_part`.

Geometry responses carry a runtime identity that the caller verifies. Workers reject drift from the parent's source/instruction identity. This also applies to disposable cq_warehouse workers. A mismatch reports `runtime_mismatch` and requires restart rather than falling back to a stale library-less toolset.

The provider receives the current CAD instruction text on both thread start and resume. This is separate from MCP registry delivery: a prompt cannot compensate for a missing tool.

## Inspecting a running service

Each service writes a private startup identity to `.promptcad/runtime/backend-<pid>.json` (or the configured app-data folder). It includes process IDs, source/module paths, interpreter paths, search paths, loaded instruction hash and tool names. Old identity files can remain after a process exits; check the PID/start time before treating one as live evidence.

The internal `workspace.runtime` RPC returns and compares the current backend and geometry identities. AI `cad_capabilities` responses carry a public runtime fingerprint. Project turn logs record `backend_runtime_verified` and `mcp_tools_delivered` evidence without raw machine paths. These records show what was delivered, rather than assuming the checkout reflects a running session.

Startup identity files contain local paths and are private diagnostics. Do not publish them, account state, raw provider sessions or private project data. Use a reviewed, redacted excerpt for issue reports.

## Focused verification

```powershell
.venv\Scripts\python.exe -B -m unittest backend.tests.test_runtime_identity backend.tests.test_v2_provider -v
```

The checks cover stale in-memory instructions, an old or mutated registry, wrong source roots, parent/child mismatches, actual MCP standard-tool advertisement, and instruction delivery on start/resume. They use synthetic fixtures without paid inference. A live end-to-end check must separately confirm the model's tool responses and saved developer instructions, using a disposable synthetic project rather than changing an existing model.

Restart all copies of the app after source updates. Preserve accepted projects and conversations; restarting is not a reason to delete projects, runtime sessions or credentials. A prior session with an old registry proves what it received, but does not by itself prove whether an old process or an alternate source installation supplied it.
