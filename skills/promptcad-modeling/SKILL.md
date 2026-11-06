---
name: promptcad-modeling
version: 1.0.0
description: Create or edit a design in Prompt to CAD using its supported CAD tools, standard-part generators, and staged validation workflow.
---

# Prompt to CAD modeling workflow

Use this workflow when creating a new CAD design or changing existing geometry in Prompt to CAD.

If the required `cad_*` tools are not available in the current agent session, do not imitate them with shell commands, scripts, or direct project-file edits. Explain that the live Prompt to CAD application is not connected and offer guidance only.

1. Call `cad_context` and `cad_capabilities` first. Respect the frozen selection, current candidate ID, operation budget, and tool limits. Load `promptcad-catalog` if an existing catalog component may be useful.
2. Identify the requested components and dimensions. Ask for critical missing dimensions when needed; otherwise state reasonable assumptions through the application's engineering-note workflow. Do not invent a component count if the user specified one.
3. Use `cad_standard_parts` to discover a supported `cq_warehouse` generator for standard hardware. Use `cad_standard_part` with its registered ID and validated parameters. For nonstandard geometry, use the supported CAD operations or restricted `cad_script` language.
4. Preserve unrelated components. Follow the tool's scope rules and inspect after successful writes because candidate IDs and topology references can change.
5. Call `cad_validate` before reporting success. Report what was created, important assumed dimensions, and any limitation or unverified requirement. A successful CAD validity check does not establish functional or manufacturing suitability.

Do not use shell, arbitrary Python, filesystem access, or credentials. Only use application-owned CAD tools.
