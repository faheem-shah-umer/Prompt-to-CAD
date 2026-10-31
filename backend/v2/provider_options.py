"""Shared presentation and submission contract; effort IDs are provider-owned."""

from typing import Protocol

from backend.native.contracts import WorkspaceError


class ProviderOptions(Protocol):
    identity: dict

    def reasoning_effort(self, model: dict | None) -> dict:
        """Return state, options, default_id and an explanatory message."""
        ...

    def turn_options(self, effort: dict) -> dict:
        """Map an application-validated effort snapshot into runtime settings."""
        ...


def capture_effort(provider_id, model_id, control, requested=None):
    if requested is not None and (not isinstance(requested, str) or not requested):
        raise WorkspaceError("Invalid reasoning effort selection.", "effort_invalid")
    options = {option["id"]: option for option in control.get("options", [])}
    supported = control.get("state") == "supported"
    if requested is not None and (not supported or requested not in options):
        raise WorkspaceError(
            "The selected reasoning effort is no longer available for this provider/model. "
            "Refresh models and select a supported option. Your draft was retained.",
            "effort_unavailable",
        )
    chosen = requested if requested is not None else control.get("default_id")
    if not supported or chosen not in options:
        chosen = None
    return {
        "provider_id": provider_id,
        "model_id": model_id,
        "state": control.get("state", "unavailable"),
        "option_id": chosen,
        "label": options[chosen]["label"] if chosen is not None else None,
        "source": "user" if requested is not None else
                  "provider_default" if chosen is not None else "provider_configuration",
    }
