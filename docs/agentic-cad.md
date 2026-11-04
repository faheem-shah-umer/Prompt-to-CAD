# Agentic CAD capabilities — source implementation

These changes are implemented on `agentic-cad-capabilities`. At the user’s request, the native executable was rebuilt and deployed behind the existing local shortcut. No tests, live inference, UI verification or installer were run. See the [local build record](runtime-update.md). The acceptance scenarios below remain pending; they are not validation results.

## Component transactions

`cad_restructure` operates on the current `candidate_id` with `source_instance_ids` and `operation`:

| Operation | Behaviour |
| --- | --- |
| `split` | One solid, split using `plane: {origin, normal}` in source-local mm or a different `tool_instance_id`. Every resulting solid becomes a component. Optional `names` correspond to pieces sorted by local centroid X/Y/Z. Volume and shape conservation are checked. |
| `merge` | At least two bodies are unioned and consumed. The result must be one valid connected solid. A disconnected union fails without accepting a partial transaction. Optional `name` and `color` control its presentation. |
| `replace` | A controlled script or staged definition replaces one or more bodies with one or more output solids. One-to-one replacement keeps its instance ID; multi-output restructuring uses application-generated IDs. |

The tool returns the new candidate token and a source/output mapping. Ownership is recorded by trusted application code, not by script-supplied metadata. All consumed bodies must be within submitted body scope. Resulting descendants can be edited in the same task. Unselected geometry, placement, appearance, parameters, engineering data and assembly groups remain protected. Selecting only a face or edge does not authorize whole-body restructuring.

Single-source operations retain the source frame and assembly parent. Multiple-source operations use assembly/world coordinates and their nearest common assembly ancestor. Each output contains one valid positive-volume solid; disconnected results must be represented as separate components. Imported feature history is not reconstructed.

`cad_script` keeps its legacy `instance_id` entry point and also accepts `source_instance_ids` or a staged `definition_id`. `selected` and `inputs[id]` contain local geometry for one source. Multiple input shapes and outputs use world coordinates. Scripts return `parts={name: solid, ...}` and can return `colors={name: '#RRGGBB'}` or normalized RGB values.

The interpreter supports approved CadQuery constructors/methods, branching, comparisons, tuple assignment, bounded list/dictionary construction and loops, simple literal f-strings, scalar conversions and numeric helpers. Typed Solid/Compound/Face/Wire/Edge constructors, splitting, topology collections, tags, tagged workplanes, profile offsets and text geometry are exposed. General functions, imports, reflection, arbitrary file access, shell and network access remain unavailable. Text geometry uses installed font names, not font file paths. Each turn has a 45-minute deadline and a normal 32-operation budget. The agent can explicitly declare a genuinely complex design through `cad_capabilities(complex_design=true)` to raise that turn's bounded ceiling to 64; capabilities and candidate responses expose used/remaining operations. A script counts as one operation, catalog insertions count separately, batches count contained edits, and read-only calls are free. Failed mutations leave both candidate state and accounting unchanged; reaching the limit leaves the saved design available for continuation in a later turn. Scripts have a 45-second timeout, 100 outputs, 1,000 collection entries/loop iterations and the worker's process/memory controls.

Named-parameter regeneration retains script/recipe inputs and updates the associated output set. Downstream shape edits or changes to the output component set require an explicit replacement. Regeneration that changes unselected dependent outputs is rejected with their IDs instead of silently changing them.

## Project definitions and acceptance

`cad_files` lists project CAD assets and definitions, reads a definition by ID, or stages a new `.cad.py`/`.cad.json` version with named numeric defaults. It does not accept agent-selected filesystem paths. Staging alone does not execute the definition. `cad_script`/`cad_restructure` execute staged versions through the existing geometry worker. Script execution uses retained defaults unless parameters are explicitly supplied. Recipe parameters remain inside their JSON definition and can also be changed through named-parameter commands.

Accepted definitions live in immutable, hashed files inside each CAD document's `definitions/` directory. Revisions reference those assets; prior versions remain available for undo and project copying. Accepted project files, application source and credentials are not directly writable through these tools.

Geometry, appearance and engineering metadata have distinct change/validation paths. Geometry changes receive solid/interference/STEP checks. Appearance/metadata-only edits verify retained asset hashes and reuse prior accepted geometry verification where available; they still receive schema, target and scope checks. Successful tasks commit all accepted candidate changes as one revision. Cancellation/provider failure discards the candidate. Change cards include created, updated and consumed component IDs.

`cad_capabilities` reports implemented operations and limits. Assembly verification uses a conservative world-space bounding-box broad phase to skip only definitely separated pairs, while touching, overlapping or uncertain bounds still run the existing exact solid check. Active mutation checks also report candidate/skipped/exact pair counts when benchmarked; final validation and STEP round-trip remain separate work. Reports include candidate, skipped and exact pair counts and timing. Agent instructions require fresh inspection and specific failure explanations. Valid geometry and successful execution do not establish general engineering correctness, full sketch constraints or a mechanical simulation capability.

`cad_decision` records concise public decision summaries for private [project turn logs](turn-logs.md): the chosen CAD approach, alternatives and the reason for using or skipping cq_warehouse. Actual tool attempts/results and final acceptance are logged independently, including failures. These explanations are stated reasons rather than hidden reasoning; omitted explanations remain explicitly marked as not provided. Decision logging does not create a geometry revision or consume the modelling-operation budget.

## Colours and engineering records

`cad_appearance` changes normalized RGB component colours, including multiple selected bodies. Creation scripts can colour each output separately. Modify → Colour and Properties expose the same operation. Mesh overrides change presentation/export without modifying the original mesh asset; Use source mesh colours removes the override. Colour changes create undoable revisions.

STEP exports encode solid component colours; GLB encodes solid tessellation colours and mesh overrides/source colours. STL has no component colour preservation. Export responses report this distinction.

`cad_engineering` upserts/removes revision-owned `dimension`, `label` and `note` records. Modify → Engineering information and Properties expose an editor. Records contain their owner, a body or revision-bound entity anchor, text and optional dimension/tolerance data. Non-body anchors and measured topology carry the current `asset_hash` from inspection or a fresh submitted selection. Saved notes appear under **Saved design notes** in the conversation and in Properties; document Properties also lists records without requiring a geometry selection. Notes, labels and dimensions stay hidden in the viewport by default, including legacy records without a visibility setting. Enable **Show in viewport** in the annotation editor, or explicitly request a viewport annotation through chat, to display a current record. This stores the boolean `viewport_visible` with the record. Existing text and anchors remain editable; stale anchors remain marked in Properties and are never rendered against guessed face/edge indices.

Dimensions bind to an existing named parameter, a measured entity pair, or an explicitly declared nominal value. Declared dimensions remain unverified. Supported units are mm, deg and unitless; measured minimum distances use mm. Tolerances support symmetric/asymmetric plus/minus magnitudes or lower/upper limits. Limits can report that the current nominal is outside the recorded interval. Metadata edits never resize geometry. Use parameter/modelling tools for nominal shape changes.

Full GD&T, datum systems, drawing sheets, leader-layout editing and STEP PMI export are not implemented. Engineering records remain in the project's revisions, not STEP/STL/GLB geometry exports.

## Image references

The composer supports attachment selection, clipboard images and local-file drag/drop. Pending previews are removable and separate from an active task's frozen images. A failed capability preflight preserves the draft. Later drafts are not overwritten by failed submissions; failed images can be restored separately. Draft copies are local ignored data under `.promptcad/draft-images/`; submitted originals are immutable project `references/` assets.

Limits are eight PNG/JPEG/WebP images, 20 MB each, 50 MB combined and 40 million decoded pixels per image. Animated/multi-frame images are rejected. Backend validation decodes images and checks hashes/containment before model input. New persisted references are project-relative. UI-only absolute preview paths are not persisted in transcripts. Missing or corrupt images are shown as unavailable rather than silently omitted. Save As copies and verifies attachment assets and resets provider sessions while retaining local history.

The existing account model catalogue is reconciled with App Server `model/list` input modalities. Selected-model provider bounds are queried where the runtime exposes them. Results are cached for ten minutes per account/runtime configuration. Missing declarations remain **unknown**, even where older runtime catalogues assume compatibility. Unknown/unsupported image capability blocks attachment submission and offers refresh/model choice. Capability metadata is not account entitlement; only a completed real image turn establishes observed access for that request. No inference probes, browser registrations, model substitutions or billing switches are used.

Current attachments use App Server `localImage` input. Original images remain with user messages and tasks. Clicking a historical image reattaches its original. When the user explicitly refers to an earlier image, `cad_reference_image` can retrieve that conversation asset; its MCP observation is downsampled to 1,200 pixels per side to bound transport size. Reattach the original for full-resolution turn input. Resumed conversations include reference availability and actual current CAD context. Base viewport screenshots remain labelled as submitted-revision observations.

See the official [App Server model and input interfaces](https://learn.chatgpt.com/docs/app-server), [ChatGPT plan-use configuration](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server) and [input/preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations). Reference-guided editable CAD reconstruction is distinct from a separately supplied image-to-3D generation service; no such generation service is integrated. Scale and essential dimensions still require user information, and a single photo does not establish hidden geometry.

## Pending acceptance scenarios

When specifically requested, use synthetic projects/images/credentials to validate:

- Fused-vase splitting, connected merging, one-to-many replacement and multi-source script regeneration, with unrelated components preserved and full undo/redo/reopen.
- Scope violations, stale face/annotation references, disconnected/invalid outputs, failed transaction rollback, cancellation and resource-limit reporting.
- Colour-only and engineering-only revisions; independent dimensions versus tolerances; parameter dependencies; solid/mesh colour persistence and STEP/GLB exports.
- Definition versioning, asset integrity, project copies with remapped definition/annotation/revision links and reset provider sessions.
- Known/unknown/unsupported image models, cache isolation, bounds conflicts, image-only turns, failed preflight, draft isolation, history reuse, provider errors and all attachment limits/containment checks.
- Native labels, colour/editor dialogs, clipboard/drop/previews, change cards and compact composer layouts in dark/light themes and Windows scaling.

No personal project, account, registration or reference image should be used for these checks without an explicit request.

## STEP assemblies with reference geometry

STEP import retains solid-bearing XCAF definitions, their assembly groups, instance placements, names and colours. Surface-only, curve-only and empty reference definitions are skipped with an import warning. Loose auxiliary faces/edges/vertices alongside solids are removed at the import boundary; the remaining solids still pass the normal validity and positive-volume checks. Modelling operations continue to reject loose non-solid topology. A file containing no solid bodies is still rejected. Warnings are stored with the imported revision and shown as native notifications. No original sketches, constraints or editable surface history are inferred.
