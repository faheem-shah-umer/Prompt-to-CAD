from pydantic import ValidationError

from .design_schema import Design, EditPlan
from .parameters import DesignError


def apply_changes(design: Design, plan: EditPlan, selected_id: str | None) -> Design:
    if plan.status != "ready":
        raise DesignError("An incomplete edit cannot change a project.")
    if selected_id is not None and selected_id not in {part.id for part in design.components}:
        raise DesignError("The selected component no longer exists.")
    data = design.model_dump(mode="json")
    for change_model in plan.changes:
        change = change_model.model_dump(mode="json")
        kind = change["type"]
        target = change.get("component_id")
        if selected_id is not None:
            if kind in ("add_component", "remove_component", "set_relationship", "remove_relationship") or target != selected_id:
                raise DesignError("This edit is limited to the selected part. Choose Assembly to change other parts or relationships.")
        if kind == "add_component":
            if any(part["id"] == change["component"]["id"] for part in data["components"]):
                raise DesignError("A new component must have a new ID.")
            data["components"].append(change["component"])
            continue
        if kind == "set_relationship":
            relation = change["relationship"]
            old = next((index for index, item in enumerate(data["relationships"]) if item["id"] == relation["id"]), None)
            if old is None:
                data["relationships"].append(relation)
            else:
                data["relationships"][old] = relation
            continue
        if kind == "remove_relationship":
            original = len(data["relationships"])
            data["relationships"] = [r for r in data["relationships"] if r["id"] != change["relationship_id"]]
            if original == len(data["relationships"]):
                raise DesignError("The relationship to remove does not exist.")
            continue
        if kind == "set_parameters" and target is None:
            data["parameters"].update(change["values"])
            continue
        part = next((part for part in data["components"] if part["id"] == target), None)
        if part is None:
            raise DesignError(f"The component '{target}' does not exist.")
        if kind == "set_parameters":
            part["parameters"].update(change["values"])
        elif kind == "set_placement":
            part["placement"] = change["placement"]
        elif kind == "remove_component":
            data["components"].remove(part)
        elif kind == "add_feature":
            if any(feature["id"] == change["feature"]["id"] for feature in part["features"]):
                raise DesignError("A new feature must have a new ID.")
            after = change["after"]
            if after is None:
                part["features"].append(change["feature"])
            else:
                index = next((i for i, feature in enumerate(part["features"]) if feature["id"] == after), None)
                if index is None:
                    raise DesignError("The insertion point does not exist.")
                part["features"].insert(index + 1, change["feature"])
        else:
            feature_id = change["feature"]["id"] if kind == "replace_feature" else change["feature_id"]
            index = next((i for i, feature in enumerate(part["features"]) if feature["id"] == feature_id), None)
            if index is None:
                raise DesignError(f"Feature '{feature_id}' does not exist.")
            if kind == "replace_feature":
                part["features"][index] = change["feature"]
            else:
                part["features"].pop(index)
    try:
        candidate = Design.model_validate(data)
    except ValidationError as error:
        raise DesignError("The proposed edit has invalid references or would leave an empty component.") from error
    if candidate == design:
        raise DesignError("The proposed edit does not change the design.")
    return candidate
