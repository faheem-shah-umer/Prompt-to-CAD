"""Synthetic geometry for automated checks; no saved user designs or conversations."""

import json
from pathlib import Path


def assembly_definition():
    return {
        "schema_version": 1, "name": "Synthetic geometry fixture", "units": "mm",
        "components": [
            {
                "id": "base", "name": "Fixture plate", "color": "#81909f",
                "parameters": {"length": 64, "width": 44, "thickness": 8},
                "features": [
                    {"id": "blank", "type": "box", "size": ["length", "width", "thickness"]},
                    {"id": "corners", "type": "fillet", "size": 1, "edges": "|Z"},
                    {"id": "bore", "type": "cylinder", "radius": 2, "height": 12,
                     "operation": "cut", "placement": {"translation": [12, 0, -6]}},
                    {"id": "bores", "type": "circular_pattern", "feature": "bore",
                     "count": 4, "operation": "cut"},
                ],
                "expected_size": ["length", "width", "thickness"],
            },
            {
                "id": "post", "name": "Fixture column", "color": "#b69bce",
                "parameters": {"height": 20},
                "features": [{"id": "column", "type": "cylinder", "radius": 5, "height": "height"}],
                "placement": {"translation": [0, 0, "base.thickness / 2"]},
            },
            {
                "id": "cap", "name": "Fixture loft", "color": "#90b6cc",
                "features": [
                    {"id": "start", "type": "sketch", "profile": "circle", "radius": 5},
                    {"id": "middle", "type": "sketch", "profile": "circle", "radius": 7, "origin": [0, 0, 5]},
                    {"id": "end", "type": "sketch", "profile": "circle", "radius": 5, "origin": [0, 0, 10]},
                    {"id": "loft", "type": "loft", "sketches": ["start", "middle", "end"]},
                ],
                "placement": {"translation": [0, 0, "base.thickness / 2 + post.height"]},
            },
        ],
        "relationships": [
            {"id": "plate_contact", "type": "contact", "component_a": "base", "component_b": "post"},
            {"id": "loft_contact", "type": "contact", "component_a": "post", "component_b": "cap"},
            {"id": "axis", "type": "coaxial", "component_a": "post", "component_b": "cap"},
        ],
    }


def write_assembly(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "synthetic-assembly.cad.json"
    path.write_text(json.dumps(assembly_definition()), encoding="utf-8")
    return path
