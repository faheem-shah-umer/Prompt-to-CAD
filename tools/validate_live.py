"""Explicit, plan-only live CAD acceptance. Never falls back to API billing."""

import argparse
import math
import time
from pathlib import Path
from uuid import uuid4

from backend.native.contracts import WorkspaceError
from backend.native.documents import write_json
from backend.v2.cad_tools import fingerprint
from backend.v2.workspace import WorkspaceV2

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Use the selected app-owned ChatGPT plan for these CAD tasks.",
    )
    parser.add_argument("--model", default="gpt-6.1-sol")
    args = parser.parse_args()
    if not args.execute:
        parser.error("Live plan usage requires --execute. No inference was started.")
    output = ROOT / "artifacts/validation"
    output.mkdir(parents=True, exist_ok=True)
    home = ROOT / "tmp" / ("live-rework-" + uuid4().hex[:8])
    identity = Path.home() / ".promptcad/v2/identity"
    events = []
    workspace = None
    started = time.monotonic()
    report = {
        "passed": False,
        "mocked": False,
        "billing": "ChatGPT subscription",
        "model": args.model,
        "cases": [],
        "data_directory": str(home),
    }
    try:

        def progress(event):
            events.append(
                {
                    k: event[k]
                    for k in (
                        "stage",
                        "state",
                        "task_id",
                        "conversation_id",
                        "document_id",
                    )
                    if k in event
                }
            )
            if event.get("stage") not in ("assistant_delta", "candidate"):
                print(event.get("stage", "progress"), flush=True)

        workspace = WorkspaceV2(home, progress, identity_home=identity)
        _, account = workspace.connections.credential()
        if account["mode"] != "chatgpt":
            raise WorkspaceError(
                "Live runner requires the explicitly selected ChatGPT connection; API billing was not used."
            )
        catalogue = workspace.connections.models()["models"]
        if args.model not in [m["id"] for m in catalogue]:
            raise WorkspaceError(
                "Requested model is absent from the connected catalogue. Choose an available model explicitly."
            )
        workspace.dispatch("v2.project.create", {"name": "Text CAD acceptance"})

        def task(prompt, selection=None):
            params = {
                "prompt": prompt,
                "model": args.model,
                "base_revision_id": workspace.state()["document"]["revision_id"],
                "task_id": uuid4().hex,
            }
            if selection:
                params["selection"] = selection
            result = workspace.dispatch("v2.task", params)
            assert result["task"]["status"] == "completed", result["task"]["status"]
            return result

        result = task(
            "Create two separate engineering solids using retained editable CAD definitions: plate, a rectangular mounting plate 100 x 60 x 8 mm centered at the origin, and post, a 10 x 10 x 20 mm block centered at world X=80 mm. Use exactly the instance IDs plate and post. No holes yet. Validate both solids and preserve named dimensions."
        )
        original = result["document"]
        parts = {p["instance_id"]: p for p in original["components"]}
        assert set(parts) == {"plate", "post"}
        assert abs(parts["plate"]["metrics"]["volume_mm3"] - 48000) < 0.01
        report["cases"].append(
            {
                "name": "text_creation",
                "revision": original["revision_id"],
                "volume_mm3": 48000,
                "solid_count": 2,
            }
        )
        selection = {
            "revision_id": original["revision_id"],
            "document_id": original["document_id"],
            "instance_id": "plate",
            "kind": "body",
        }
        result = task(
            "Add four through mounting holes of diameter 6 mm to the selected plate. Centres are 10 mm from each adjacent outside edge: local XY centres (-40,-20), (-40,20), (40,-20), (40,20). Keep post and all its placement unchanged. Inspect and validate the result.",
            selection,
        )
        changed = result["document"]
        parts = {p["instance_id"]: p for p in changed["components"]}
        expected = 48000 - 4 * math.pi * 3**2 * 8
        assert abs(parts["plate"]["metrics"]["volume_mm3"] - expected) < 0.1
        assert fingerprint(original)["post"] == fingerprint(changed)["post"]
        first_chat = result["conversation"]["conversation_id"]
        session = result["conversation"]["provider_session"]
        undone = workspace.dispatch(
            "v2.undo", {"base_revision_id": changed["revision_id"]}
        )["document"]
        assert fingerprint(undone) == fingerprint(original)
        redone = workspace.dispatch(
            "v2.redo", {"base_revision_id": undone["revision_id"]}
        )["document"]
        assert fingerprint(redone) == fingerprint(changed)
        report["cases"].append(
            {
                "name": "selected_four_holes",
                "revision": changed["revision_id"],
                "volume_mm3": parts["plate"]["metrics"]["volume_mm3"],
                "expected_volume_mm3": expected,
                "unrelated_components_preserved": True,
                "undo_redo": True,
            }
        )
        workspace.worker.close()
        workspace = WorkspaceV2(home, progress, identity_home=identity)
        state = workspace.state()
        assert (
            state["conversation"]["conversation_id"] == first_chat
            and state["conversation"]["provider_session"] == session
        )
        assert fingerprint(state["document"]) == fingerprint(changed)
        workspace.dispatch("v2.conversation.new", {})
        workspace.dispatch("v2.conversation.open", {"conversation_id": first_chat})
        assert fingerprint(workspace.state()["document"]) == fingerprint(changed)
        selected = {
            "revision_id": changed["revision_id"],
            "document_id": changed["document_id"],
            "instance_id": "plate",
            "kind": "body",
        }
        result = task(
            "Make the selected plate 5 mm taller by increasing its Z thickness from 8 to 13 mm while keeping all four diameter 6 mm holes through the full thickness. Keep post unchanged. Inspect the current document first; validate the result.",
            selected,
        )
        thick = result["document"]
        parts = {p["instance_id"]: p for p in thick["components"]}
        assert (
            abs(
                parts["plate"]["metrics"]["volume_mm3"]
                - (100 * 60 - 4 * math.pi * 9) * 13
            )
            < 0.15
        )
        assert fingerprint(thick)["post"] == fingerprint(changed)["post"]
        assert result["conversation"]["provider_session"] == session
        report["cases"].append(
            {
                "name": "reopen_resume_and_refine",
                "revision": thick["revision_id"],
                "same_provider_session": True,
                "conversations_persisted": True,
                "volume_mm3": parts["plate"]["metrics"]["volume_mm3"],
                "unrelated_components_preserved": True,
            }
        )

        def cancel_preview(event):
            progress(event)
            if event.get("stage") == "candidate":
                workspace.cancel()

        workspace.output = cancel_preview
        selected["revision_id"] = thick["revision_id"]
        try:
            task(
                "Move only the selected plate 1 mm along world X, inspect it, then move it another 1 mm. Validate each result.",
                selected,
            )
            raise AssertionError("Cancelled task was accepted")
        except WorkspaceError as error:
            assert error.code == "cancelled", error.code
        assert workspace.document.current()["revision_id"] == thick["revision_id"]
        assert workspace.runtime is None
        report["cases"].append(
            {
                "name": "cancel_after_candidate",
                "accepted_revision_preserved": True,
                "runtime_closed": True,
            }
        )
        report.update(
            passed=True,
            event_count=len(events),
            correlated_task_events=sum("task_id" in e for e in events),
        )
    except Exception as error:
        report.update(
            error=str(error), error_code=getattr(error, "code", type(error).__name__)
        )
        raise
    finally:
        if workspace:
            workspace.connections.cancel_login()
            workspace.worker.close()
        report["elapsed_seconds"] = time.monotonic() - started
        write_json(output / "live-text-cad.json", report)
        write_json(
            output / "live-events.json",
            {"events": events, "visible_text_or_credentials_retained": False},
        )


if __name__ == "__main__":
    main()
