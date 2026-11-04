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


def plotter_definition():
    return {
        "schema_version": 1, "name": "Synthetic desktop 3-axis pen plotter", "units": "mm",
        "components": [
            {
                "id": "bed", "name": "Work surface", "color": "#64748b",
                "parameters": {"length": 180, "width": 130, "thickness": 8},
                "features": [{"id": "blank", "type": "box", "size": ["length", "width", "thickness"]}],
                "expected_size": ["length", "width", "thickness"],
            },
            {
                "id": "left_frame", "name": "Left frame", "color": "#9ca3af",
                "parameters": {"height": 90, "width": 10, "depth": 10},
                "features": [{"id": "upright", "type": "box", "size": ["width", "depth", "height"]}],
                "placement": {"translation": [-85, -55, 49]},
            },
            {
                "id": "right_frame", "name": "Right frame", "color": "#9ca3af",
                "parameters": {"height": 90, "width": 10, "depth": 10},
                "features": [{"id": "upright", "type": "box", "size": ["width", "depth", "height"]}],
                "placement": {"translation": [75, -55, 49]},
            },
            {
                "id": "x_rail", "name": "X axis rail", "color": "#b9a7d6",
                "parameters": {"length": 170, "width": 12, "height": 12},
                "features": [{"id": "rail", "type": "box", "size": ["length", "width", "height"]}],
                "placement": {"translation": [-85, -55, 88]},
            },
            {
                "id": "carriage", "name": "Plotter carriage", "color": "#d2a66f",
                "parameters": {"width": 30, "depth": 24, "height": 18},
                "features": [{"id": "body", "type": "box", "size": ["width", "depth", "height"]}],
                "placement": {"translation": [-15, -61, 70]},
            },
            {
                "id": "z_axis", "name": "Z axis", "color": "#82c5c8",
                "parameters": {"radius": 4, "height": 34},
                "features": [{"id": "shaft", "type": "cylinder", "radius": "radius", "height": "height"}],
                "placement": {"translation": [0, -55, 45]},
            },
            {
                "id": "pen", "name": "Pen holder", "color": "#e6b86a",
                "parameters": {"radius": 5, "height": 38},
                "features": [{"id": "holder", "type": "cylinder", "radius": "radius", "height": "height"}],
                "placement": {"translation": [0, -55, 7]},
            },
            {
                "id": "spool", "name": "Pen spool", "color": "#c58bc8",
                "parameters": {"radius": 16, "height": 10},
                "features": [{"id": "hub", "type": "cylinder", "radius": "radius", "height": "height"}],
                "placement": {"translation": [52, 25, 16]},
            },
        ],
        "relationships": [
            {"id": "left_bed_contact", "type": "contact", "component_a": "left_frame", "component_b": "bed"},
            {"id": "right_bed_contact", "type": "contact", "component_a": "right_frame", "component_b": "bed"},
            {"id": "rail_frame_span", "type": "contact", "component_a": "x_rail", "component_b": "left_frame"},
            {"id": "carriage_rail", "type": "contact", "component_a": "carriage", "component_b": "x_rail"},
            {"id": "pen_carriage", "type": "coaxial", "component_a": "pen", "component_b": "z_axis"},
        ],
    }


def write_assembly(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "synthetic-assembly.cad.json"
    path.write_text(json.dumps(assembly_definition()), encoding="utf-8")
    return path


def write_plotter(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "synthetic-plotter.cad.json"
    path.write_text(json.dumps(plotter_definition()), encoding="utf-8")
    return path
