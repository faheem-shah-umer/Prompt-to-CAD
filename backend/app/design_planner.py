import ast
import json
from time import perf_counter

from pydantic import ValidationError

from .assembly_schema import AssemblyPlan, ComponentBatch
from .design_edits import apply_changes
from .design_schema import Component, Design, DesignPlan, EditPlan, GeometryRepairPlan
from .llm_client import LLMError, generate_json, load_settings
from .modelling import Builder, verify_assembly
from .parameters import DesignError, Parameters
from .service import CAD_LOCK

MAX_REQUESTS = 24
ATTEMPTS_PER_STAGE = 3


def prompt_schema(model, operations=None):
    schema = model.model_json_schema()
    definitions = schema.get("$defs", {})

    def compact(node):
        if isinstance(node, list):
            return [compact(value) for value in node]
        if not isinstance(node, dict):
            return node
        result = {key: compact(value) for key, value in node.items() if key not in ("title", "default", "description", "$defs")}
        choices = result.get("oneOf", [])
        if operations and choices:
            feature_choices = [choice for choice in choices
                               if "id" in definitions.get(choice.get("$ref", "").split("/")[-1], {}).get("properties", {})]
            if len(feature_choices) == len(choices):
                retained = []
                for choice in choices:
                    kind = definitions[choice["$ref"].split("/")[-1]]["properties"]["type"]
                    if set(kind.get("enum", [kind.get("const")])) & operations:
                        retained.append(choice)
                result["oneOf"] = retained
                result.pop("discriminator", None)
        return result

    result = compact(schema)
    needed = {}

    def references(node):
        if isinstance(node, list):
            for child in node:
                references(child)
        elif isinstance(node, dict):
            if "$ref" in node:
                key = node["$ref"].split("/")[-1]
                if key not in needed:
                    needed[key] = compact(definitions[key])
                    references(needed[key])
            for child in node.values():
                references(child)

    references(result)
    if needed:
        result["$defs"] = needed
    return json.dumps(result, separators=(",", ":"))


def modelling_guide(operations=None):
    if not operations:
        return MODELLING_GUIDE
    prefix, features = MODELLING_GUIDE.split("Feature conventions:\n", 1)
    choices, suffix = features.split("- expected_size", 1)
    blocks = choices.split("\n- ")
    selected = []
    for block in blocks:
        label = block.split(":", 1)[0]
        names = set(label.replace("- ", "").replace("/", " ").split())
        if "cylinder" in names:
            names.add("sphere")
        if label.startswith("solid features") or names & operations:
            selected.append(block.removeprefix("- "))
    return prefix + "Feature conventions:\n- " + "\n- ".join(selected) + "\n- expected_size" + suffix

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
Shared parameters MUST use an explicit shared. prefix in component parameter definitions.
Example: shared parameters {'corner_radius':6}, component parameters {'corner_radius':'shared.corner_radius'}.
NEVER define {'corner_radius':'corner_radius'}: it is a self-reference, not a shared alias.

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
  PREFER the inline sections form for parallel profiles: type='loft', plane='XZ', profile='ellipse',
  sections=[{'station':0,'width':'width','height':'thickness'},
            {'station':'length / 2','width':'width','height':'thickness'},
            {'station':'length','width':'width / 2','height':'thickness / 2'}].
  Stations are along the plane NORMAL: XY=+Z, XZ=-Y, YZ=+X. XZ station 40 means y=-40, not z=40.
  The engine computes section origins. Use either sections or sketches, never both.
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
  Add these only when the user requests rounding/chamfering, not as gratuitous decoration.
  Rounding both circular rims of a cylinder requires radius STRICTLY LESS than half its height;
  alternatively round only the top rim using '>Z'. Never use the cylinder radius as the fillet size.
- thread: REAL triangular helical solid, major_radius > minor_radius, pitch, length, left_hand.
  Depth major-minor must be <0.8*pitch; maximum 48 turns. External thread creates a minor-diameter
  core plus a swept ridge. internal=true cuts that helical tool out of an existing body.
  This is geometric threading, NOT ISO-certified threads. Do not use a plain cylinder as a thread.
- expected_size optional: intended LOCAL overall bounding size [x,y,z] for dimension verification.
- relationships: component_a/b + type=coaxial or contact. Coaxial points and axes are LOCAL to each
  part, then transformed by its placement. Default axes [0,0,1], points [0,0,0].
  contact verifies minimum BREP distance <= tolerance. Set placements yourself using expressions;
  the engine verifies relationships, it does not solve unspecified positions.
  type='distance' verifies the Euclidean distance between transformed local point_a/point_b
  against a named 'distance' expression. Use this for explicit adjacent control centres, hole centres
  across components, wheel spacing, etc. The anchors default to each part's local origin.
- A component attachment={parent:'body',axis:'Z',side:1,offset:[x,y],gap:0} places its minimum
  world Z on the parent's maximum world Z. The engine computes the actual contact translation.
  Offset uses the other two WORLD axes in XYZ order, relative to the parent's bounding centre.
  axis='Y',side=-1 attaches the child's maximum Y to the parent's minimum Y (rear).
  Attached parts use placement translation=[0,0,0]; rotation remains applicable.
  The rule aligns bounding faces, not arbitrary curved faces; actual contact/interference are still checked.
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

Transform properties (NOT feature types):
placement is a JSON PROPERTY of a component or solid feature, never a standalone feature.
NEVER emit a feature with type='placement', type='translate', type='rotate' or type='move'.
Use 'placement': {'translation':[x,y,z], 'rotation':[rx,ry,rz]} on the component or solid feature.
Rotations are degrees about X, then Y, then Z around the local origin, then translation.
Sketches use origin, not placement. Fillet/chamfer/hole have no placement field.
For a later move, use an edit change with type='set_placement', not a construction feature.

Spatial planning:
Build parts in their own LOCAL coordinates, then position them once using component.placement.
Choose the local origin at a clear connecting surface when this simplifies contact.
A separate control resting on a centred body's top uses z=body.thickness/2;
its local cylinder runs from z=0 to height, and a cap starts at z=stem_height.
An elliptical grip extending backwards can use XZ sketches (normal -Y): root at [0,0,0],
middle at [0,-length/2,0], tip at [0,-length,0]. Place the root on the parent's flat rear face,
y=-body.depth/2, away from its rounded corner. This makes a shared connecting face without overlap.
Ellipse width/height are FULL profile lengths; do not double them.
For N equally spaced controls with adjacent centre distance s, circle radius is s/(2*sin(pi/N)).
For a four-button diamond the offsets from its centre are s/sqrt(2), not s.
A raised cross can be one non-self-intersecting polygon sketch + extrude.
Keep explicitly requested sizes and colours. Do not remove requested detail to make checks pass.
"""

ASSEMBLY_PROMPT = """
You plan an editable parametric CAD assembly in millimetres. Return JSON only.
First decompose the user's idea into an ASSEMBLY BRIEF, not construction features.
Return status, description, questions, assumptions, assembly matching the following schema.
For ready, assembly contains name, units, shared parameters, components and relationships.
For needs_input/unsupported, assembly=null. Complex does not automatically mean unsupported.
For EACH separately selectable part provide its id, name, hex colour, parameters, placement,
requirements and depends_on. Describe its requested shape, construction method and dimensions
in requirements. Include EVERY requested part. Never merge buttons/wheels/grips the user wants selectable.
List the construction operations needed for each part in 'operations'. Choose from the schema's
feature names, e.g. ['box','fillet'], ['loft'], or ['sketch','extrude']; transforms are not operations.
For connected parts prefer an 'attachment' rule so the engine positions actual surfaces after building:
{parent:'body',axis:'Z',side:1,offset:[x,y],gap:0} rests a child on top of its parent.
{parent:'body',axis:'Y',side:-1,offset:[x,z],gap:0} attaches it to the rear.
Offsets use the other WORLD axes in XYZ order relative to the parent's bounding centre.
Use named offset parameters or expressions. Attached parts keep placement.translation=[0,0,0].
Use explicit placements for free parts and cases unsuitable for bounding-face contact.
Give enough named parameters for the requested geometry, including editable layout coordinates.
expected_size is optional: use only when the LOCAL overall dimensions are unambiguous.
For an explicitly sized rectangular body, include expected_size=[width,depth,thickness].
Keep all explicit dimensions. State assumptions for unspecified dimensions or design decisions.
depends_on lists parts needed before this part can be constructed (usually the main body).
Do not include features in this brief. Plan positions and interfaces carefully before generating parts.
Shared and component parameter expressions must be resolvable, without cycles or unknown names.
Add actual contact relationships for the requested attachments. Avoid unintended intersection.
Only permit an intersection if it was explicitly requested; never use this to bypass a failed assembly.
Contact does NOT require overlap. Default allowed_intersections=[] even for connected parts.
If the user gives an exact spacing between component centres, add type='distance' relationships
for those pairs, with point_a/point_b=[0,0,0] and distance='shared.spacing_parameter'.
Use that spacing parameter in their placement expressions too; storing an unused value is an error.

Coordinate conventions are critical:
- X = left/right; negative X is left. Y = front/back; negative Y is backward. Z = up.
- The main box/body is CENTRED at the origin, spanning +/- half each dimension.
  Its top is z=thickness/2, rear is y=-depth/2. It does NOT run from z=0 to thickness.
- Each child is built in local coordinates, preferably with its attachment surface at local zero.
  A top-mounted control then uses translation=[x,y,'body.thickness / 2'], NOT full thickness.
  Its local cylinder/extrusion starts at z=0. NEVER add the control height to the resting translation.
- Two rear grips must BOTH have root y=-body.depth/2, with negative and positive X offsets.
  Do not put one at the front, use X=0 for both, or add the world offsets to their local sketches.
- A rear grip can use local XZ ellipse sections at y=0,-length/2,-length and z=0.
  Do not use a zero-size tip section. Curvature/thickness variations are allowed with positive sizes.
- All visible controls must fit on the top footprint, with clearance from rounded corners and each other.
- For four controls in a diamond with ADJACENT centre distance s, offsets are s/sqrt(2), not s.
  Around centre (cx,cy), use (cx,cy+r),(cx+r,cy),(cx,cy-r),(cx-r,cy), r=s/sqrt(2).

Parameters:
Use 'parameters' for shared values, NOT an object called 'shared'. Expressions reference them as
'shared.name'. A component parameter may alias a shared value as {'width':'shared.width'}.
Never use {'width':'width'}: it is circular because local names shadow shared names.
Arithmetic allows +,-,*,/,**, pi, sin/cos/tan (radians), sqrt, abs, min, max; no executable code.
Keep placements linked to parameters. IDs start with a lowercase letter and use lowercase/digits/underscores.
Each component is one solid, not a mesh. Preserve explicit dimensions, colours and separate selection.
Unspecified sizes may be estimated as concept assumptions. Do not claim functional or manufacturing validation.
Ask questions only for contradictions or a necessary decision that cannot reasonably be assumed.
Use unsupported only for an unavailable modelling operation, not simply because a request is complex.
""" + "\nJSON schema:\n" + prompt_schema(AssemblyPlan)

COMPONENT_RULES = """
Construct ONLY the requested batch of components, returning {'components':[...]} matching the schema.
Each component recipe contains ONLY id, features and optional parameters for additional dimensions.
Name, colour, planned parameters, placement and expected_size are attached by the application from
the assembly brief. DO NOT repeat these fields in a recipe or move the part in its features.
You may add needed named parameters, but do not change parameter values already planned.
Use ONLY the target component_briefs and shared parameters as the source of truth for this batch.
The complete assembly was already planned; OTHER COMPONENTS ARE GENERATED IN OTHER REQUESTS.
The three-component limit applies to this response, not to the assembly. The supplied feature subset
applies to these parts, not the whole application. Never merge other parts into these features.
Put actual geometry operations in features.
Previous components' measured bounds are provided to help check attachment and clearance.
Return complete local feature recipes, with ordered sketch/solid construction history.
Use exactly the IDs requested in this batch, no omitted parts and no additional parts.
Do not duplicate the component placement in its features. Preserve requested dimensions and shapes.
Boolean references may only target components already built or in the same batch.
Reference the planned LOCAL parameter names in features, e.g. width rather than shared.body_width
when width already aliases shared.body_width. Local aliases must actually drive their part.
For symmetric/repeated parts, retain consistent construction. A cap sits at the stem's TOP,
so its feature translation Z equals stem height, never zero. Name unspecified construction sizes too.
For a cross-shaped pad use one 12-vertex polygon + extrude, or two intersecting rectangular bars.
Do not start from a full square plate that fills the cross's missing corners.
"""


def localise_features(features, parameters):
    aliases = {raw: name for name, raw in parameters.items() if isinstance(raw, str) and raw.startswith("shared.")
               and raw[7:].isidentifier()}
    ignored = {"id", "type", "operation", "sketch", "plane", "profile", "feature", "component", "edges", "axis"}

    class LocalReferences(ast.NodeTransformer):
        def visit_Attribute(self, node):
            key = ast.unparse(node)
            return ast.copy_location(ast.Name(id=aliases[key], ctx=ast.Load()), node) if key in aliases else node

    def visit(value, key=None):
        if isinstance(value, dict):
            return {field: visit(item, field) for field, item in value.items()}
        if isinstance(value, list):
            return [visit(item, key) for item in value]
        if isinstance(value, str) and key not in ignored and "shared." in value:
            try:
                tree = LocalReferences().visit(ast.parse(value, mode="eval"))
                return ast.unparse(tree.body)
            except SyntaxError:
                pass
        return value

    return [visit(feature.model_dump(mode="json")) for feature in features]

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
set_attachment has component_id, attachment (new face rule, or null to detach).
For an attached part, edit its offset parameters or use set_attachment; translation is derived
from the attachment, so set_placement translation alone does not move it.
add_component has component, remove_component has component_id.
set_relationship has a complete relationship (existing id replaces; new id adds).
remove_relationship has relationship_id. Remove any dependent relationships if removing a part.
Use needs_input and changes=[] if the selection conflicts with the requested scope.
For ready provide at least one change. Leave unmodified data out of changes.
""" + "\nJSON schema:\n" + json.dumps(EditPlan.model_json_schema(), separators=(",", ":"))


def validation_message(error):
    if isinstance(error, ValidationError):
        return "\n".join(f"{'.'.join(map(str, item['loc']))}: {item['msg']}"
                         for item in error.errors(include_input=False)[:6])
    return str(error)


class PlanningSession:
    def __init__(self, settings, progress=None, trace=None):
        self.settings = settings
        self.progress = progress
        self.trace = trace
        self.calls = 0
        self.repairs = 0
        self.completed = 0
        self.total = 0
        self.started = perf_counter()

    def notify(self, stage, message):
        if self.progress:
            self.progress({"stage": stage, "message": message, "components_completed": self.completed,
                           "components_total": self.total, "requests_used": self.calls, "max_requests": MAX_REQUESTS})

    def ask(self, system, context, schema, stage, message, validate=None):
        original = json.dumps(context, ensure_ascii=False)
        user = original
        request_system = system
        history = None
        for attempt in range(ATTEMPTS_PER_STAGE):
            if perf_counter() - self.started > 600:
                raise LLMError("Generation reached its ten-minute limit. Your saved design is unchanged.", "timeout")
            if self.calls >= MAX_REQUESTS:
                raise LLMError("The bounded generation budget was reached. Your saved design is unchanged.", "invalid_plan")
            self.calls += 1
            if attempt or stage == "repairing":
                self.repairs += 1
            self.notify(stage if not attempt else "repairing", message if not attempt else f"Repairing {stage}: attempt {attempt + 1}/{ATTEMPTS_PER_STAGE}")
            text = None
            try:
                options = {"max_tokens": 8192}
                if history:
                    options.update(history=history, temperature=0.15)
                response = generate_json(request_system, user, self.settings, **options)
                text = response.text
                if self.trace:
                    self.trace({"stage": stage, "request": self.calls, "response": text,
                                "input_tokens": response.input_tokens, "output_tokens": response.output_tokens})
                plan = schema.model_validate_json(text)
                if validate:
                    validate(plan)
                return plan
            except (ValidationError, DesignError, LLMError) as error:
                if isinstance(error, LLMError) and error.code not in ("invalid_json", "truncated", "empty_response"):
                    raise
                text = text or getattr(error, "response_text", None)
                diagnostic = validation_message(error)
                if self.trace:
                    self.trace({"stage": stage, "request": self.calls, "validation_error": diagnostic,
                                "response": text})
                if attempt == ATTEMPTS_PER_STAGE - 1:
                    raise LLMError(f"Could not build a valid design after {ATTEMPTS_PER_STAGE} attempts in {stage}. "
                                   f"Last check: {diagnostic[:800]}", "invalid_plan") from error
                history = [{"role": "user", "content": original}]
                if text:
                    history.append({"role": "assistant", "content": text})
                user = json.dumps({"validation_errors": diagnostic,
                                   "repair_instruction": "Return a COMPLETE corrected response for this stage. Preserve all user requirements and explicit dimensions. Placement is a property, not a feature type. Do not bypass geometry checks."}, ensure_ascii=False)
                request_system = system + "\nREPAIR REQUIRED: The previous response failed validation. You MUST fix the following errors, changing the invalid fields rather than repeating the same output:\n" + diagnostic + "\nFor a local parameter aliasing a shared parameter, use 'shared.name', never a bare self-reference. Return the corrected JSON object only."
                if "fillet" in diagnostic or "chamfer" in diagnostic:
                    request_system += "\nIf this edge treatment was extra decoration not requested by the user, omit it from the corrected recipe. If explicitly requested, preserve its required size and choose feasible edges; do not silently reduce a requested dimension."


def skeleton(brief, constructed=None):
    constructed = constructed or {}
    components = []
    for part in brief.components:
        if part.id in constructed:
            components.append(constructed[part.id])
        else:
            data = part.model_dump(exclude={"requirements", "depends_on", "operations"})
            data["expected_size"] = None
            data["features"] = [{"id": "pending", "type": "box", "size": [1, 1, 1]}]
            components.append(Component.model_validate(data))
    return Design(name=brief.name, parameters=brief.parameters, components=components,
                  relationships=brief.relationships, allowed_intersections=brief.allowed_intersections)


def checked_design(design, original=None, *, require_driven=False):
    with CAD_LOCK:
        builder = Builder(design)
        parts = builder.build()
        report = verify_assembly(builder, parts)
        if require_driven and report["unused_parameters"]:
            raise DesignError("Parameters do not drive the design: " + ", ".join(report["unused_parameters"]) +
                              ". Link the requested dimensions to feature/placement expressions; preserve their values.")
        if original is not None:
            old_parameters = {f"shared.{key}": value for key, value in original.parameters.items()}
            for part in original.components:
                old_parameters.update({f"{part.id}.{key}": value for key, value in part.parameters.items()})
            unused = [key for key in report["unused_parameters"] if old_parameters.get(key) != builder.parameters.raw[key]]
            if unused:
                raise DesignError("Changed parameters do not drive geometry: " + ", ".join(unused) + ". Link them to feature values first.")
        return {part.component.id: {"local_dimensions_mm": part.validation["local_dimensions_mm"],
                                  "world_bounds_mm": part.validation["bounds_mm"],
                                  "volume_mm3": part.validation["volume_mm3"]} for part in parts}


def create_design(prompt, session):
    def check_brief(plan):
        if plan.assembly:
            Parameters(skeleton(plan.assembly))

    outline = session.ask(ASSEMBLY_PROMPT, {"request": prompt}, AssemblyPlan, "planning",
                          "Breaking the idea into components and connecting surfaces…", check_brief)
    if not outline.assembly:
        return DesignPlan(status=outline.status, description=outline.description,
                          questions=outline.questions, assumptions=outline.assumptions)
    brief = outline.assembly
    if len(brief.components) > 3:
        review_prompt = ASSEMBLY_PROMPT + """
REVIEW THE DRAFT AGAINST THE ORIGINAL REQUEST before any construction. Correct errors in the
draft, especially explicit dimensions, spatial layout, requested shapes, colours and contact rules.
Keep the draft's component IDs. Return a complete corrected assembly plan. Check every requirement,
not just whether the schema is valid. A diamond is a circular arrangement, not a rectangular grid.
Its four ADJACENT spacings must equal the requested pitch; offsets are pitch/sqrt(2).
A cross has missing corners. Prefer sketch+extrude or two bars; do not model a solid square pad.
Use attachments for top/rear contacts and shared expressions for all requested layout dimensions.
"""
        outline = session.ask(review_prompt, {"request": prompt, "draft": outline.model_dump(mode="json")},
                              AssemblyPlan, "planning", "Reviewing the part layout and requested dimensions…", check_brief)
        if not outline.assembly:
            return DesignPlan(status=outline.status, description=outline.description,
                              questions=outline.questions, assumptions=outline.assumptions)
        brief = outline.assembly
    session.total = len(brief.components)
    built, measurements = {}, {}
    while len(built) < session.total:
        targets = [part for part in brief.components if part.id not in built
                   and (set(part.depends_on) | ({part.attachment.parent} if part.attachment else set())).issubset(built)][:3]
        if not targets:
            raise LLMError("The assembly has unresolved component dependencies.", "invalid_plan")
        ids = {part.id for part in targets}
        definitions = {part.id: part for part in targets}
        prepared = {}

        def check_batch(batch):
            if len(batch.components) != len(ids) or {part.id for part in batch.components} != ids:
                raise DesignError("Return exactly these component IDs: " + ", ".join(sorted(ids)))
            proposed = dict(built)
            for recipe in batch.components:
                planned = definitions[recipe.id]
                if any(key in planned.parameters and planned.parameters[key] != value for key, value in recipe.parameters.items()):
                    raise DesignError(f"Keep the planned parameter values for {recipe.id}; extra construction parameters are allowed.")
                data = planned.model_dump(exclude={"requirements", "depends_on", "operations"})
                data["parameters"].update(recipe.parameters)
                data["features"] = localise_features(recipe.features, data["parameters"])
                part = Component.model_validate(data)
                for feature in recipe.features:
                    if feature.type == "boolean" and feature.component not in built and feature.component not in ids:
                        raise DesignError(f"Boolean target {feature.component} has not been built. Declare the dependency in the assembly plan.")
                proposed[part.id] = part
            with CAD_LOCK:
                builder = Builder(skeleton(brief, proposed))
                for part in batch.components:
                    builder.component(part.id)
            prepared.update({key: proposed[key] for key in ids})

        dependencies = {key for part in targets for key in part.depends_on}
        dependencies.update(part.attachment.parent for part in targets if part.attachment)
        context = {"task": "Construct ONLY the listed component_ids. This is one batch of a larger, already planned assembly. Other parts are constructed separately.",
                   "shared_parameters": brief.parameters,
                   "component_briefs": [part.model_dump(mode="json") for part in targets],
                   "component_ids": [part.id for part in targets],
                   "built_component_measurements": {key: value for key, value in measurements.items() if key in dependencies}}
        operations = set().union(*(set(part.operations) for part in targets)) if all(part.operations for part in targets) else None
        component_prompt = modelling_guide(operations) + COMPONENT_RULES + "\nJSON schema:\n" + prompt_schema(ComponentBatch, operations)
        batch = session.ask(component_prompt, context, ComponentBatch, "components",
                            f"Constructing {', '.join(part.name for part in targets)}…", check_batch)
        built.update(prepared)
        with CAD_LOCK:
            builder = Builder(skeleton(brief, built))
            for part in batch.components:
                result = builder.component(part.id)
                measurements[part.id] = {"local_dimensions_mm": result.validation["local_dimensions_mm"],
                                         "world_bounds_mm": result.validation["bounds_mm"]}
        session.completed = len(built)
        session.notify("components", f"Built {session.completed}/{session.total} components")
    design = skeleton(brief, built)
    session.notify("verifying", "Checking component geometry, contacts and unintended intersections…")
    try:
        checked_design(design, require_driven=True)
    except DesignError as error:
        repaired = None
        if session.trace:
            session.trace({"stage": "verifying", "request": session.calls, "validation_error": str(error)})

        def check_repair(plan):
            nonlocal repaired
            if plan.status != "ready":
                raise DesignError("Return a ready repair with changes for the failed geometry checks.")
            if any(change.type not in ("set_placement", "set_attachment", "replace_feature", "add_feature") for change in plan.changes):
                raise DesignError("Repair geometry/placement only. Keep all component IDs, parameters, dimensions and relationships; do not remove requested features.")
            repaired = apply_changes(design, plan, None)
            checked_design(repaired, require_driven=True)

        repair_operations = {feature.type for part in design.components for feature in part.features}
        repair_prompt = modelling_guide(repair_operations) + """
Repair the supplied candidate using its ACTUAL measured bounds and validation failures.
Return status='ready', description and changes. The ONLY changes allowed are set_placement, set_attachment,
replace_feature and add_feature. Do not emit set_parameters or repeat unchanged fields.
Keep all IDs, parameter values, explicit dimensions and assembly relationships.
For a placement error, use parameter expressions. A cylinder spans 0..height locally;
to rest it on a centred body's top, its base translation is body.thickness/2, not plus its height.
replace_feature needs component_id and a complete feature with its existing id.
set_placement needs component_id and placement={translation:[x,y,z],rotation:[rx,ry,rz]}.
For an attached part, change its attachment offsets with set_attachment, not set_placement translation.
set_attachment needs component_id and the complete attachment object; preserve its requested parent.
Fix ALL reported contacts/intersections/unused geometry parameters in a single response.
""" + "\nJSON schema:\n" + prompt_schema(GeometryRepairPlan, repair_operations)
        session.ask(repair_prompt, {"request": prompt, "current_design": design.model_dump(mode="json"),
                    "selected_component_id": None, "validation_errors": str(error),
                    "component_measurements": measurements, "repair_only": True},
                    GeometryRepairPlan, "repairing", "Repairing the assembly using actual geometry feedback…", check_repair)
        design = repaired
    return DesignPlan(status="ready", description=outline.description, assumptions=outline.assumptions, design=design)


def interpret(prompt: str, project=None, selected_id=None, *, progress=None, trace=None):
    started = perf_counter()
    settings = load_settings()
    session = PlanningSession(settings, progress, trace)
    if project is None:
        plan = create_design(prompt, session)
    else:
        design = project["design"]
        if selected_id is None:
            context = design
        else:
            selected = next((part for part in design["components"] if part["id"] == selected_id), None)
            if selected is None:
                raise LLMError("The selected part no longer exists.", "invalid_plan")
            context = {"name": design["name"], "parameters": design["parameters"], "selected_component": selected,
                       "other_components": [{key: part.get(key) for key in ("id", "name", "parameters", "placement", "attachment")}
                                            for part in design["components"] if part["id"] != selected_id],
                       "relationships": design["relationships"]}
        measurements = {part["id"]: {"local_dimensions_mm": part.get("validation", {}).get("local_dimensions_mm"),
                                       "world_bounds_mm": part.get("validation", {}).get("bounds_mm")}
                        for part in project.get("components", [])}
        original = Design.model_validate(design)

        def check_edit(value):
            if value.status == "ready":
                checked_design(apply_changes(original, value, selected_id), original)

        user = {"request": prompt, "selected_component_id": selected_id,
                "current_design": context, "component_measurements": measurements,
                "earlier_assumptions": project["assumptions"]}
        plan = session.ask(EDIT_PROMPT, user, EditPlan, "editing", "Planning and checking the requested change…", check_edit)
    return plan, {"provider": settings.provider, "model": settings.model,
                  "strategy": "component_batches" if project is None else "selected_edit",
                  "requests": session.calls, "repairs": session.repairs,
                  "seconds": round(perf_counter() - started, 3)}
