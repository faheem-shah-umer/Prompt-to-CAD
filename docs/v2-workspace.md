# Prompt to CAD V2

A Windows desktop CAD workspace with application-owned geometry tools and Codex App Server. This is a developing application, not an AutoCAD replacement or a production-grade claim.

## Start and build

Use Python 3.11 on Windows x64. Install the runtime requirements:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-v2.txt
.venv\Scripts\python.exe tools\build_native.py --test
.venv\Scripts\python.exe native-app.py
```

The native build requires an x64 MSVC toolchain, CMake/Ninja, Qt 6.5+ Widgets and the exact OpenCascade 7.8.1 SDK matching cadquery-ocp 7.8.1.1.post1. Supply `--qt-prefix` and `--occt-prefix` to the build script, or set CAD_QT_PREFIX and CAD_OCCT_PREFIX. See [native SDK details](native-workspace.md). The configured development checkout already has these SDKs.

The C++ executable is PromptToCAD.exe. The normal window is **Prompt to CAD V2**. The earlier native window remains available with `--legacy-native`; the earlier web application is retained separately.

## Connect an agent

Install the official [Codex CLI](https://learn.chatgpt.com/docs/cli). In Account, choose its native executable if it is not on PATH, then **Continue with ChatGPT**. Complete consent in your system browser, return to the application and choose **Discover models**. The tested executable was codex-cli 0.165.0-alpha.1.2; a successful handshake alone does not verify model inference.

V2 uses its own dynamic public OAuth registration, stable host identifier, loopback callback, state, nonce and PKCE. It verifies ID-token signatures, issuer, audience, expiry, identity and granted plan scope. It never reads credentials from the Codex desktop application or asks for account session tokens. Saved registrations are separate even when email addresses match. A provider workspace name is not currently reported by this flow; the UI explicitly shows that limitation and a stable registration suffix. Confirm the workspace during browser consent.

Current official documentation allows this integration path for eligible local/open-source applications, with Plus/Pro eligibility described in the quickstart. Eligibility, workspace policy, model access and allowance can still restrict requests. A future paid or hosted product requires the provider's additional approval path; the MIT licence does not grant provider access. See [local/open-source plan usage](https://developers.openai.com/siwc/token-sharing-open-source), [quickstart](https://developers.openai.com/siwc/quickstart) and [App Server connection](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server).

Model discovery uses the supported account-authenticated models endpoint. Catalogue visibility does not prove inference entitlement. Only a completed inference verifies access for that request. Errors, revoked sessions and usage limits stop the task without changing billing.

ChatGPT tasks use the connected plan and any credits the user separately authorizes in ChatGPT settings. Longer tasks can consume more usage. This external-provider connection currently has no reliable allowance percentage, so the badge says **Usage unavailable**. Manage provider usage and access in [ChatGPT Settings → Usage](https://chatgpt.com/settings/usage). This is separate from the application's operation/time budgets.

An optional **Connect API key (separate billing)** action accepts a user-supplied OpenAI API key. Selecting that connection is explicit. There is no automatic subscription-to-API fallback and no developer key in the executable. Access, refresh, retained identity tokens and optional service keys are encrypted with Windows DPAPI under the current Windows user. Disconnect attempts session revocation, clears local tokens and reports when remote revocation could not be confirmed.

## Projects and conversations

Create a project, import a supported model or ask the agent to create a design with essential dimensions. Multiple conversations can target the same document. Switching conversations reads the document's actual accepted revision and does not restore an older chat snapshot. New provider sessions receive recent local conversation context plus fresh document state. Expired provider sessions can be explicitly restarted from Tools; local history remains.

Projects, documents, conversations, task records, references and provider sessions have separate identifiers. Accepted CAD revisions use immutable content-addressed assets and an atomic history cursor. Every geometry writer obtains a per-document OS lock across application windows; revision acceptance also checks its base revision. Interrupted tasks preserve the accepted document. Archive and trash actions retain files and can be reversed in **Tools → Manage archived and deleted items**.

Data defaults to `%USERPROFILE%/.promptcad/v2`. A short path avoids OCCT/Windows path-length failures. PROMPTCAD_HOME overrides this location. The projects directory contains workspace metadata, native documents, conversations, tasks and reference images; identity and runtime state are separate sibling directories. Native document copies are not a portable archive of every V2 conversation or provider session. Keep the whole application data directory for local backup; DPAPI credentials remain tied to the Windows user.

## Geometry and selection

Engineering imports: STEP/STP and the existing editable .cad.json recipes. Visual imports: standalone GLB, STL, OBJ and PLY, up to 100 MB and 200,000 triangles. Confirm mesh source units on import. External OBJ materials and external glTF resources are not resolved.

The viewport supports orbit, pan, zoom, fit, standard views, body/face/edge/vertex selection for solids, Ctrl multi-edge selection, mesh body/triangle-region selection, hide/isolate/show, solid edge display and a coordinate indicator. Panels resize/collapse and retain layout preferences. The CAD manager shows actual assembly structure, measurements, named parameters and accepted revisions. Interactive section planes and semantic mesh segmentation are future scope.

A task freezes project/document/revision, instance/body, entity kind/index, geometry hash, units, placement and useful entity measurements. A highlighted viewport capture accompanies submitted geometry tasks. Each candidate has a new topology epoch; stale tool references are rejected after successful writes. A selected component restricts writes to that instance and explicitly derived mesh separations; unrelated component assets and placements must remain identical. A selected mesh region restricts region operations to its submitted triangle indices. Solid sub-entity context identifies the face/edge accurately; the application boundary for general solid scripting is the selected component, not a geometric proof that all other faces remain unchanged.

Supported modelling includes polygon-profile extrusion/cut, holes, planar face holes/offsets, fillets, chamfers, booleans, patterns, world-axis component transforms and supported named parameters. Imported STEP solids have no invented original sketches or feature history. Recipe parameters retain the existing downstream-edit guard. Script parameters regenerate retained definitions; undo downstream solid edits before regeneration to avoid discarding them.

The restricted CAD language supports CadQuery workplane/solid construction, profiles, lofts, sweeps, shelling and other allowed geometry methods. It is interpreted from an AST without Python exec/eval: imports, files, network, shell, reflection and arbitrary functions are unavailable. Scripts run in the geometry worker with a 45-second operation deadline, a 2 GB process-memory limit, one process and a 30,000-instruction budget. Worker termination preserves the accepted revision. This is a restricted geometry language, not an unrestricted Python sandbox.

Example:

```python
plate = cq.Workplane('XY').box(params['width'], params['depth'], params['thickness'])
parts = {'mounting_plate': plate}
```

Mesh operations include uniform scale, smoothing, explicit region color/move and separation. Region movement keeps vertices shared with unselected triangles fixed; a tiny region may have no movable interior vertices. A single chair mesh does not automatically contain a selectable semantic leg. Use explicit triangle selection/separation or import already separated parts. Original reference assets and generated GLB are retained; native mesh previews and edited exports use sampled face colors rather than a full PBR material editor.

## Validation, revisions and cancellation

Codex uses a required stdio MCP server backed by an authenticated local task bridge. The same CAD implementation is independent of the agent provider. Only these app-owned, scoped candidate tools receive standing approval. App Server shell/browser/apps are disabled and its workspace is read-only. Ordinary modelling never requires application-source edits. Clarification requests appear in the UI; unrelated execution requests are declined. Hidden model reasoning is not displayed.

Geometry is changed in a candidate until the provider turn completes successfully and application verification passes. Failures and cancellation discard the candidate. Verification includes solid validity/count/positive volume, STEP export/reimport dimensions and volume, scope preservation and new solid interference checks. Mesh validation checks finite nondegenerate triangles and GLB round-trip bounds/topology; engineering interference is not claimed for visual meshes. The agent can inspect dimensions, face areas, edge lengths, placements and solid distances/clearances. Semantic intent still requires appropriate constraints and review; generic geometry validity is not proof that every natural-language request was interpreted correctly.

Tasks have a ten-minute local execution budget and at most 32 modelling operations. These limits do not describe provider allowance. Undo/redo and revision restore operate on accepted documents, independently of conversation switching. Export solids as STEP/STL and visual geometry as GLB/STL; STEP export refuses meshes. A no-change agent turn explicitly states that no geometry revision was created.

## Image reconstruction and separate costs

The selected backend is the documented **Tripo v3 API**, using user-supplied credentials, upload, image-to-model, polling, GLB download and local validation. This integration is implemented and its HTTP contract has fixture tests. **A paid live generation has not been run; the user requested that it remain pending.** There is no mock generation button or placeholder model presented as a completed service result.

Attach an image and either use **Image → mesh**, or enable the composer's explicit separate-billing option for one reconstruction in the next agent task. Without that option, the agent image tool refuses before making a paid request. Supply the longest dimension in millimetres. Other dimensions and hidden geometry remain inferred; the result is an approximate visual mesh, not dimensionally exact engineering reconstruction. The reference, scale source, seeds, model settings, provider task ID, output hash and reported consumed credits are retained. Cancelling locally may leave the remote job running and consuming Tripo credits; the task ID is retained for diagnosis. Automatic paid POST retries are disabled. GUI recovery of a remote image job is not yet implemented.

The adapter pins model v3.1-20260211 and a 20,000-face target with texture/PBR enabled. The service documents typical latency in the 10–120 second range, but quality, queue latency and cost have not been measured in this application. Check [Tripo's API documentation](https://developers.tripo3d.ai/en/docs/generation-image-to-model/standard), [files](https://developers.tripo3d.ai/en/docs/files), [task query](https://developers.tripo3d.ai/en/docs/task-query), [pricing](https://developers.tripo3d.ai/en/pricing) and applicable service/output licence terms before use. Tripo credits are separate from ChatGPT/Codex usage and from Tripo Studio subscriptions.

The alternative [TripoSR](https://github.com/VAST-AI-Research/TripoSR) is MIT-licensed, including its published model, and documents about 6 GB default VRAM. The inspected development GPU has 2 GB VRAM, so no unverified local-quality or latency claim is made. No model weights are bundled.

## Additional providers

Claude is research only. Current [Claude Code legal documentation](https://code.claude.com/docs/en/legal-and-compliance) distinguishes an end user authenticating directly through the unmodified Claude Code binary from a third-party product collecting or offering Claude.ai login. The [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview) requires approval for third-party subscription-login offerings; an eventual SDK integration should use documented API-key/cloud-provider authentication unless approved. No Claude credentials, subscription proxy or incomplete provider switch is implemented. Recheck those conditions before adding the provider.

## Checks and distribution

```powershell
.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
.venv\Scripts\python.exe tools\build_native.py --test
.venv\Scripts\python.exe -m tools.package_native --smoke-test
```

The package includes isolated Python/native dependencies, source/build scripts and retained third-party licence texts. The Codex executable is an external user-installed dependency. Credentials, app data, sessions, model weights and developer keys are excluded. Builds are currently unsigned; clean-machine installer signing and broader hardware/performance testing remain release work. See [implementation status](V2_IMPLEMENTATION.md) and [validation evidence](../artifacts/v2-validation/).
