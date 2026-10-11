Generation from detailed descriptions
====================================

The creation path separates assembly planning from component construction. It keeps editable construction history and separate part IDs, and uses actual geometry feedback before accepting a saved revision.

Typed construction and validation
--------------------------------

Placement is a component or feature transform, not a construction operation. Assembly briefs describe component intent separately from the features that build each part.

Invalid JSON and unsupported feature tags receive schema feedback. Invalid solids, dimensions, contacts, anchor distances and interference receive geometry feedback. The configured model can correct its response within a fixed budget.

What the references show
------------------------

| Reference | Publicly documented behaviour | Relevant design choice here |
| --- | --- | --- |
| [Meshra API](https://meshra.ai/docs) | Asynchronous generation with a generation ID and status polling; parameter edits re-execute a model; CAD exports include STEP, STL and GLB. Its documentation does not expose its private generation engine. | A fast job-submission response, visible progress and a separately retrieved final result. |
| [Yo.Town Maker documentation](https://docs.yotown.com/docs/core/cad) | Describes prompt-driven OpenSCAD generation and editable source. Generated designs can require correction. | Retain the modelling instructions needed to rebuild and edit a design. |
| [Yo.Town Mars repository](https://github.com/yotown/mars) | Public model outputs include CadQuery/OCCT parts, local frames, named components and connector/mate helpers. The [walking cargo rover source](https://github.com/yotown/mars/blob/main/mobility/walking-cargo-rover/assets/model.py) constructs separate parts and aligns connector frames. The repository is not the private prompt-to-CAD service. | Separate component construction, stable identities, local coordinates and explicit assembly relationships. |

These examples show useful architecture patterns. They do not establish that every arbitrary prompt succeeds. Our app uses its own typed modelling tools rather than executing generated Python or OpenSCAD. This makes revisions inspectable and restricts execution to implemented operations. Adding a genuinely new operation requires a schema and a deterministic builder implementation.

Current flow
------------

1. React submits a description to `POST /api/design-jobs`. FastAPI validates the input and returns HTTP 202 with a job ID.
2. The model creates an assembly brief: component IDs, colours, named parameters, placements or face attachments, required operations, construction requirements, dependencies and relationships. Assemblies with more than three parts receive a second layout review against the request before construction.
3. The app requests feature recipes for up to three components whose dependencies are ready. Each request includes the target briefs, shared parameters, dependency measurements and a compact contract for relevant operations. Metadata stays attached to the planned IDs. Simple shared references are rewritten to equivalent existing local aliases so those part parameters drive its features.
4. CadQuery constructs each candidate component on the CPU. A rejected recipe receives schema or geometry feedback before the next group is attempted.
5. The complete assembly is checked for valid solids, expected local dimensions, surface contact, coaxial alignment, anchor distances and unintended overlapping volume. New generated parameters must be linked to the design.
6. If the assembly fails, a restricted repair can replace/add features or change placements/attachments. It cannot delete parts, remove relationships or change parameter values to bypass the checks.
7. The existing export path writes named STEP bodies and STL previews, re-imports STEP, checks exchanged geometry, then commits the accepted revision. React receives the result through the polling endpoint.

Selected edits use the selected ID and feature history, with other part summaries and relationships. A rejected or stale candidate preserves the accepted project state. Undo/redo still operates on accepted revisions.

Limits and diagnostics
----------------------

There are at most three attempts per stage and 24 model requests per action. The action stops starting requests after ten minutes; the last in-flight request can run until its configured timeout. All inference uses the configured endpoint and model. Authentication, quota, network and timeout failures stop immediately. There is no provider/model fallback and no training requirement.

The interface shows stages, completed/total components and elapsed time. Failed actions offer **Download generation details**. Local diagnostics contain the original request, candidate responses and validation failures in `generation-jobs/<job-id>/diagnostics.json`. Keep these files private when they contain private design descriptions. Credentials are not recorded. In-process progress is lost if the backend closes; accepted projects and diagnostic files persist.

Inline loft sections express station, width, height and optional centre in a named plane. The engine computes section origins along the plane normal: XY → +Z, XZ → -Y, YZ → +X. Earlier sketch-based lofts remain supported. This removes a common ambiguity without changing the requested geometry.

A `distance` relationship has two part IDs, local anchor points and a target expression. For adjacent button centres, local anchors at `[0,0,0]` and target `shared.button_pitch` check the actual placed centres. This is a dimensional assertion, not a general assembly solver.

A component `attachment` specifies a parent, world axis, side, two offset expressions and gap. For example, `{ "parent":"body", "axis":"Z", "side":1, "offset":["x_offset","y_offset"], "gap":0 }` aligns the child's lowest world Z with the parent's highest world Z. The engine derives translation from actual bounds after rebuilding, including centred versus one-sided child geometry. Parent edits therefore move attached children without changing their definitions. Axis Y and side -1 attach to the rear; offsets then use X and Z. Actual BREP contact and overlap checks remain mandatory because bounding faces do not describe every curved or rotated interface. `set_attachment` edits the rule; `set_placement` translation alone does not move an attached part.

Every attachment receives an automatic surface-distance check, even if the plan omits a separate contact relationship. A child aligned with the top bounding plane but positioned outside the parent's footprint is rejected. Selected-edit context includes attachment rules and measured world bounds, so the model sees the actual assembly position.

Trying the controller example
----------------------------

[The controller prompt](../examples/gaming-controller.prompt.txt) describes ten separate components: a 140 x 70 x 20 mm body, two elliptical grips, two joysticks, a directional pad and four coloured buttons.

Open [the generated controller design](../examples/gaming-controller.generated.cad.json) to rebuild the supplied assembly without inference. Each part has a stable ID and editable feature history. Select the green button, request a height change, inspect the accepted revision and use Undo/Redo to compare the results. New generation or conversational editing requires your own configured endpoint and model.

The deterministic controller specification also serves as a regression input for CAD construction, dimensions, attachments and selected-part edits. Mocked provider tests exercise repair and job control. These checks verify implemented behaviours; they are not a benchmark of success on arbitrary descriptions. Inspect generated geometry against the requested design.

Next engineering work
---------------------

Evaluate a varied prompt set and record both geometry validity and agreement with requested features. Extend reusable dimensional assertions, richer sketches and durable face/edge references where failures justify them. Full assembly solving, STEP import and functional mechanism verification need separate implementations. A successful BREP check does not prove manufacturing suitability or mechanical function.
