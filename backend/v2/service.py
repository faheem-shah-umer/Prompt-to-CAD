import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.native.contracts import WorkspaceError

from .workspace import WorkspaceV2


def application_folder():
    folder = Path(__file__).resolve().parents[2]
    if (folder.parent / "bin/PromptToCAD.exe").is_file() and (
        folder.parent / "python/python.exe"
    ).is_file():
        return folder.parent
    return folder


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--projects-dir",
        type=Path,
        default=Path(
            os.getenv(
                "PROMPTCAD_HOME",
                str(application_folder() / ".promptcad"),
            )
        ),
    )
    args = parser.parse_args()
    isolated = (
        "PROMPTCAD_HOME" in os.environ
        or args.projects_dir != application_folder() / ".promptcad"
    )
    project_folder = Path(
        os.getenv(
            "PROMPTCAD_PROJECTS_DIR",
            str(
                args.projects_dir / "projects"
                if isolated
                else application_folder() / "Projects"
            ),
        )
    )
    output_lock = threading.Lock()
    state_lock = threading.Lock()
    busy = False
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cad-service")

    def send(message):
        with output_lock:
            sys.stdout.write(
                json.dumps(message, ensure_ascii=False, allow_nan=False) + "\n"
            )
            sys.stdout.flush()

    workspace = WorkspaceV2(
        args.projects_dir,
        lambda event: send({"jsonrpc": "2.0", "method": "progress", "params": event}),
        identity_home=os.getenv("PROMPTCAD_IDENTITY_HOME")
        or (None if isolated else Path.home() / ".promptcad/v2/identity"),
        projects_dir=project_folder,
    )

    def respond(request):
        nonlocal busy
        try:
            result = workspace.dispatch(request["method"], request.get("params", {}))
            reply = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except Exception as error:
            reply = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "error": {
                    "code": -32000,
                    "message": str(error),
                    "data": {"code": getattr(error, "code", "application_error")},
                },
            }
        with state_lock:
            busy = False
            send(reply)

    try:
        for line in sys.stdin:
            request = None
            try:
                request = json.loads(line)
                if (
                    not isinstance(request, dict)
                    or request.get("jsonrpc") != "2.0"
                    or "id" not in request
                ):
                    raise WorkspaceError(
                        "Expected an identified JSON-RPC 2.0 request.",
                        "invalid_request",
                    )
                if not isinstance(request.get("params", {}), dict):
                    raise WorkspaceError(
                        "RPC parameters must be an object.", "invalid_request"
                    )
                method = request["method"]
                if method == "provider.respond":
                    if not workspace.runtime:
                        raise WorkspaceError("There is no active agent clarification.")
                    params = request.get("params", {})
                    result = workspace.runtime.respond(
                        params["request_id"], params["answers"]
                    )
                    workspace.emit(
                        {
                            "stage": "agent_running",
                            "message": "Continuing with your answer.",
                        }
                    )
                    send({"jsonrpc": "2.0", "id": request["id"], "result": result})
                    continue
                if method == "workspace.cancel":
                    with state_lock:
                        workspace.cancel()
                    send(
                        {
                            "jsonrpc": "2.0",
                            "id": request["id"],
                            "result": {"cancellation_requested": True},
                        }
                    )
                    continue
                if method == "workspace.shutdown":
                    workspace.cancelled.set()
                    send({"jsonrpc": "2.0", "id": request["id"], "result": {}})
                    break
                with state_lock:
                    if busy:
                        raise WorkspaceError(
                            "Another task is running. Wait or cancel it first.", "busy"
                        )
                    busy = True
                    workspace.cancelled.clear()
                executor.submit(respond, request)
            except Exception as error:
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": request.get("id") if isinstance(request, dict) else None,
                        "error": {
                            "code": -32600,
                            "message": str(error),
                            "data": {"code": getattr(error, "code", "invalid_request")},
                        },
                    }
                )
    finally:
        workspace.cancelled.set()
        executor.shutdown(wait=True, cancel_futures=True)
        workspace.connections.cancel_login()
        workspace.worker.close()


if __name__ == "__main__":
    main()
