import json
from time import perf_counter

from pydantic import ValidationError

from .design_schema import DesignPlan, EditPlan
from .llm_client import LLMError, generate_json, load_settings

MODELLING_GUIDE = """
You plan editable, parametric solid CAD in millimetres. Return JSON only, matching the supplied schema.
Never return Python, executable code, shell commands, meshes or file paths.
This is a general feature-based modeller, not a plate template. Decompose the request into separate
components and ordered construction features. Preserve all requested geometry and dimensions.
If a request lacks sizes, you may create a plausible CONCEPT with explicit sizing assumptions.
Do not claim a concept meets a manufacturing standard, fit, strength requirement or functional mechanism.
Ask questions (needs_input) if requirements contradict one another or a necessary design decision
cannot reasonably be assumed. Use unsupported only for operations outside the engine, not simply
because a part is complex. Explain which capability is missing, and never substitute simpler geometry
for an explicitly requested feature without asking.

Every component must end as ONE connected solid. Different parts MUST be different components.
IDs use lowercase letters, digits and underscores, starting with a letter; IDs are permanent.
Use named parameters and arithmetic expressions in feature values and placements so future edits
rebuild the design. 'diameter / 2', 'post.height + base.thickness / 2', and 'shared.clearance' are valid.
Bare parameter names resolve within the component, then shared parameters. Expressions permit + - * /
** (bounded exponent), pi, sin/cos/tan (radians), sqrt, abs, min, max. No arrays, assignments or code.
Every named parameter must actually drive a feature or placement. A bolt-circle parameter must
appear in hole centres (e.g. ["bolt_circle_diameter / 2",0]), not just be stored beside literal 26.
A component ID cannot be shared, pi or a function name. Numeric sizes are <=2000 mm.

Feature conventions:
- box: size=[x,y,z]; centered=true centres on origin, false starts at origin.
- cylinder/cone: from z=0 to height, along +Z; sphere is centred at origin.
  CYLINDERS ARE NOT CENTRED. Do not add half their height to a resting placement.
  For a centred 8 mm base, a 32 mm cylinder resting on top starts at z=4, not z=20.
  A loft whose sketch origins span z=0..24 rests on that cylinder at z=4+32=36.
- sketch: a closed profile on XY, XZ or YZ, with origin [x,y,z], centre [u,v].
  circle needs radius, rectangle/ellipse need width and height (full lengths);
  polygon/spline need at least 3 [u,v] points. Spline is periodic.
  One sketch is ONE contour. For circle/rectangle/ellipse, points MUST be [].
  Do not place multiple circles in a sketch. Use hole or a cylinder cut + pattern instead.
  XY local coordinates are X,Y; XZ are X,Z with normal -Y; YZ are Y,Z with normal +X.
- extrude: refers to an earlier sketch, signed distance along its plane normal; symmetric optional.
- revolve: earlier sketch + GLOBAL-to-the-component axis_start/end, angle 0..360 degrees.
  A revolved closed profile must stay to one side of its axis. An XZ sketch revolved about Z
  produces a turned knob, wheel, stepped shaft etc.
- loft: ordered earlier sketch IDs at different origins; optional ruled.
- sweep: earlier sketch normal to the start tangent, path list of 3D points (absolute in part
  coordinates); smooth=true uses a spline, otherwise polyline. frenet optional.
- solid features operation=new/add/cut/intersect; first solid can be new/add.
  A cut tool MUST overlap and remove material. A subsequent add must connect to the body.
  Use long cylinders with operation=cut for holes, bores and counterbores.
- hole: radius, centres=[[u,v],...], axis='Z' by default, depth=null for THROUGH holes.
  It drills every centre through the complete existing body. No operation or placement fields.
  axis Z centres are [X,Y], axis X centres are [Y,Z], axis Y centres are [X,Z].
  depth=number drills from the POSITIVE bounding face inward for a blind hole.
  Example: four diameter 6 through holes on a diameter 52 bolt circle use radius=3,
  centres=[[26,0],[0,26],[-26,0],[0,-26]], axis='Z', depth=null.
  A sketch at z=0 extruded positively cannot make a through hole in a centred box.
- linear_pattern / circular_pattern: repeat an earlier SOLID FEATURE TOOL, not the entire part.
  The original was already applied. count includes original. step is a 3D translation.
  A 360-degree circular pattern spaces count copies around a full circle;
  otherwise count copies span the requested angle, including endpoints.
  A pattern of holes must also use operation=cut. Can pattern a preceding pattern tool.
- mirror: previous feature tool mirrored in the plane through origin with normal; specify operation.
- boolean: another component's LOCAL solid, transformed by this feature's placement; specify operation.
  Do not create circular dependencies.
- fillet / chamfer: size and an edge selector. Selectors: '|Z', '>Z', '<Z', '%Circle', etc.
  Refer to the body at that point in history. Keep sizes physically feasible.
- thread: REAL triangular helical solid, major_radius > minor_radius, pitch, length, left_hand.
  Depth major-minor must be <0.8*pitch; maximum 48 turns. External thread creates a minor-diameter
  core plus a swept ridge. internal=true cuts that helical tool out of an existing body.
  This is geometric threading, NOT ISO-certified threads. Do not use a plain cylinder as a thread.
- placement: rotation=[X,Y,Z] degrees, applied in that order about part origin, then translation.
  ALL solid features have placement; sketches have origin. Components have their own placement.
- expected_size optional: intended LOCAL overall bounding size [x,y,z] for dimension verification.
- relationships: component_a/b + type=coaxial or contact. Coaxial points and axes are LOCAL to each
  part, then transformed by its placement. Default axes [0,0,1], points [0,0,0].
  contact verifies minimum BREP distance <= tolerance. Set placements yourself using expressions;
  the engine verifies relationships, it does not solve unspecified positions.
- Avoid interpenetrating components. allowed_intersections defaults []; only declare an explicit
  intentionally intersecting pair if the user requests one; never use it to bypass a placement mistake.
Before returning a ready design, calculate each part's local minimum and maximum Z and its world
position. Contact needs actual surfaces touching, not just named components or matching axis origins.
Typical stack: centred base box size=[80,60,8] spans -4..4; post cylinder radius=8,height=32 spans
0..32 locally and uses component placement translation=[0,0,"base.thickness / 2"];
grip sketches at z=0,12,24 plus loft use placement=[0,0,"base.thickness / 2 + post.height"].
Do NOT put those world Z offsets into both a solid feature placement and its component placement.
Limits: 32 parts, 256 total features, 96 per part, 128 circular copies, 64 linear copies, 12 loft sections.
Do not imply 'verified' proves function, production readiness, standards compliance or user intent.
"""

CREATE_PROMPT = MODELLING_GUIDE + """
For creation return status, description, questions, assumptions, design.
For ready, design has name, units='mm', parameters, components and relationships.
For needs_input/unsupported, design=null and questions explain how to proceed.
Prefer a concise, well-parameterised history. A plate is a box, and a hole is a cylinder cut.
Assembly parts must have meaningful distinct names and persistent IDs.
""" + "\nJSON schema:\n" + json.dumps(DesignPlan.model_json_schema(), separators=(",", ":"))

EDIT_PROMPT = MODELLING_GUIDE + """
You are editing an EXISTING project supplied in the user message. Return status, description,
questions, assumptions, changes, never an entire replacement design.
Keep component IDs and feature IDs stable. Use set_parameters for size changes if possible.
Inspect the existing history first: set_parameters works only if that parameter is referenced by
features or placements. If dimensions are literal, replace_feature with the new values or expressions.
A selected_component_id restricts ALL changes to that part's parameters, features and placement.
Do not change shared parameters or other parts, add/remove components, or change relationships in
selected mode. Dependencies may automatically rebuild other parts without changing their definitions.
For adding/removing parts or relationships the user must first choose Assembly.
set_parameters has component_id (null for shared) and values.
replace_feature has component_id and a complete feature with the SAME existing id.
add_feature has component_id, a new feature id, and after (existing feature ID or null to append).
remove_feature has component_id, feature_id. set_placement has component_id, placement.
add_component has component, remove_component has component_id.
set_relationship has a complete relationship (existing id replaces; new id adds).
remove_relationship has relationship_id. Remove any dependent relationships if removing a part.
Use needs_input and changes=[] if the selection conflicts with the requested scope.
For ready provide at least one change. Leave unmodified data out of changes.
""" + "\nJSON schema:\n" + json.dumps(EditPlan.model_json_schema(), separators=(",", ":"))


def interpret(prompt: str, project=None, selected_id=None):
    started = perf_counter()
    settings = load_settings()
    if project is None:
        system, user, schema = CREATE_PROMPT, prompt, DesignPlan
    else:
        design = project["design"]
        if selected_id is None:
            context = design
        else:
            selected = next((part for part in design["components"] if part["id"] == selected_id), None)
            if selected is None:
                raise LLMError("The selected part no longer exists.", "invalid_plan")
            context = {"name": design["name"], "parameters": design["parameters"], "selected_component": selected,
                       "other_components": [{key: part[key] for key in ("id", "name", "parameters", "placement")}
                                            for part in design["components"] if part["id"] != selected_id],
                       "relationships": design["relationships"]}
        user = json.dumps({"request": prompt, "selected_component_id": selected_id,
                           "current_design": context, "earlier_assumptions": project["assumptions"]}, ensure_ascii=False)
        system, schema = EDIT_PROMPT, EditPlan
    response = generate_json(system, user, settings, max_tokens=8192)
    try:
        plan = schema.model_validate_json(response.text)
    except ValidationError as error:
        first = error.errors(include_input=False)[0]
        location = ".".join(str(item) for item in first["loc"])
        raise LLMError(f"The model returned an invalid CAD plan at {location}: {first['msg']}. Revise the request and try again.", "invalid_plan") from error
    return plan, {"provider": settings.provider, "model": settings.model,
                  "seconds": round(perf_counter() - started, 3)}
