# Standard components through chat

The cq_warehouse adapter supplies 34 registered physical generators across five families: 22 fasteners (nuts, screws and washers), five bearings, a sprocket, a chain and five thread generators. The registry covers every public concrete generator class in those modules at [the pinned upstream revision](https://github.com/gumyr/cq_warehouse/tree/a57bb7a24762d367d66369f280a24c38a64e73dd). Abstract classes, drafting and arbitrary extension APIs are excluded.

This is a generator integration, not a searchable database. SQLite, STEP datasets and a manual component picker are deferred. Chat use requires the application's existing AI connection. The adapter and its synthetic checks run locally without an AI account.

## Chat workflow

1. Ask for a standard component, including the dimensions/standard you need. For example: “Add an ISO 4762 M6 × 1 socket-head cap screw, 20 mm long, with detailed threads, at world X=50, Y=0, Z=0.”
2. The agent uses `cad_standard_parts` to list families or describe a generator's exact standards, sizes, parameters and defaults. It must use reported catalog entries rather than inventing a size.
3. `cad_standard_part` creates one component or regenerates an existing standard component. It validates typed parameters and applies placement before checking new intersections with other components.
4. The normal candidate validation and revision acceptance flow still applies. Failed tools preserve the prior candidate; the accepted document changes only after the turn succeeds.

Discovery example:

```json
{"generator_id":"fastener.SocketHeadCapScrew","standard":"iso4762"}
```

Creation arguments (the agent supplies the current candidate token):

```json
{
  "candidate_id":"CURRENT_TOKEN",
  "generator_id":"fastener.SocketHeadCapScrew",
  "parameters":{"size":"M6-1","fastener_type":"iso4762","length":20},
  "placement":{"translation":[50,0,0],"rotation":[0,0,0]}
}
```

Placement is absolute world translation in millimetres and Euler rotation in degrees. Omitting placement during regeneration preserves the existing placement. New components preserve all existing components, including under restricted selection. Selection supplies context; it does not authorize replacement of an existing part. Updating a part requires body permission.

Threads are detailed by default. Where a fastener supports `simple`, simplification requires an explicit `true`; the adapter never falls back silently. Standalone thread generators reject `simple=true` because upstream produces no physical solid in that mode. Catalog size strings may use imperial notation; upstream converts their geometry to millimetres.

## Editing and storage

Bearings retain their races, caps/rollers and optional cage as separate solids. Chains retain their member solids. Both use one component ID, one BREP asset, one placement and one uniform appearance. Inspection/verification reports logical component count separately from solid count.

Supported direct operations retain their normal limits: holes, fillet/chamfer, planar-face offset/holes, transforms, colors and body booleans. Face/edge operations resolve an unambiguous owning solid and preserve the others. Body operations may affect several members. Invalid results fail atomically. Restricted scripts still require one connected solid per output; this does not open arbitrary compound/script APIs.

Each component's revision-owned `standard_part` metadata records:

- `generator_id` and `dependency_revision`;
- typed `parameters`, including strings/booleans/arrays;
- `generated_asset_hash`, used to detect downstream topology changes.

`cad_definition` exposes this record and whether regeneration is allowed. Generator parameters are separate from the ordinary numeric-only parameter map. Regeneration preserves component identity, parent, placement and appearance. Undo topology edits before regenerating; changing color or placement alone remains compatible with regeneration. Native saving, reopening, undo/redo and Save As retain the record. STEP preserves the logical compound geometry, names, uniform colors and placement, but does not carry generator history.

Existing single-solid projects remain supported without this metadata. No SDK or generator dependency is needed merely to inspect an already-saved BREP; regeneration requires the pinned dependency.

## Runtime and compatibility

Use the source setup in [setup.md](setup.md). Both requirements files pin cq_warehouse 0.8.0 to commit `a57bb7a24762d367d66369f280a24c38a64e73dd`. CadQuery stays at 2.7.0 and OCP at 7.8.1.1.post1. Git is required by pip for the immutable source reference. [Apache-2.0 attribution](licenses/cq-warehouse.md) applies to upstream and the adapted sections.

All library operations run in disposable geometry processes because upstream extends CadQuery classes globally. Ordinary CAD workers do not import these extensions. The adapter avoids duplicate washer profile wires on CadQuery 2.7, copies native topology without the incompatible pickle path, and retains bearing members instead of fusing them. It does not alter installed upstream source or expose arbitrary Python imports/execution to the agent.

Current cancellation, 120-second default geometry timeout, two-GiB worker memory cap, 32-operation budget and ten-minute task limit remain in force. Large detailed models may hit those limits. Upstream dimensions/models and internal contacts are not engineering certification, clearance/load verification or manufacturing guarantees. Chain closure warnings are retained in the project.

## Focused synthetic checks

Keep experimental environments inside ignored repository folders. For an isolated compatibility environment on Windows x64:

```powershell
py -3.11 -m venv .local/cq-warehouse-check
.local\cq-warehouse-check\Scripts\python.exe -m pip install -r requirements-runtime-lock.txt
.local\cq-warehouse-check\Scripts\python.exe -B -m unittest backend.tests.test_standard_parts -v
```

The generator sweep takes several minutes. It covers all 34 generators with detailed fasteners, each thread class, internal/left-handed thread variants, typed-input rejection, placement before collision checking, selection scope, regeneration guards, native persistence/history and compound STEP round-tripping. Compound edit fixtures check owning-solid edits, unrelated-member preservation and failed-operation rollback. No private projects or paid model requests are used.

To build and run only the focused native viewer check, using the configured development SDK/toolchain:

```powershell
.venv\Scripts\python.exe -m tools.build_native --viewer-check --build-dir .local/cq-warehouse-check/viewer-build
.local\cq-warehouse-check\Scripts\python.exe -m tools.check_standard_parts_viewer
```

This separate target verifies real OpenCascade rendering plus face and whole-component selection for synthetic bearings/chains. Screenshots and reports stay under `.local/cq-warehouse-check/`. It does not rebuild or replace the installed desktop executable.

Validation for this integration on Windows: all 34 representative generators, the eight focused integration/compound checks (including targeted reruns after fixes), 40 ordinary CAD regression checks, the launcher check and both focused native viewer fixtures passed. Reviewed source privacy/secret scans and local documentation link checks passed. The existing broader desktop smoke test stopped at “Searchable model popover did not open”; that full UI check is not claimed as passing. Live AI inference and a fresh CI runner were not exercised for this branch.
