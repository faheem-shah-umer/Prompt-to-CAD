import json
import time
import threading
import queue

from backend.app.llm_client import generate_json
from .contracts import AgentAction, WorkspaceError

SYSTEM = """You edit solid CAD through registered tools. Return one JSON object matching this schema:
{schema}
Use status=tool with one command, or done, needs_input, unsupported with command=null.
The tool result includes geometry inspection of the CURRENT candidate. Never reuse edge indices after a topology change without using that new inspection.
Coordinates are local body millimetres. Holes start on the positive bounding face and drill inward; depth=null means through.
A pattern creates count copies INCLUDING its new seed. It does not repeat a feature already cut into the body.
Transform rotation is XYZ degrees around the WORLD origin, then translation in world mm.
Use the exact selected instance when selection is supplied. Do not change other parts.
Describe tool intent briefly. Never claim done before all requested geometry changes have succeeded.
Use numeric geometry to resolve targets. If multiple edges/faces equally fit the instruction, ask for selection.
Imported STEP has no original feature history. Only named parameters of generated recipes are editable.
Ask for missing dimensions that prevent a meaningful edit. Do not invent mechanical certification.
"""


def run_agent(prompt, snapshot, conversation, selected, execute, inspect, cancelled, progress, model_call=None):
    model_call = model_call or generate_json
    started = time.monotonic()
    actions = []
    observation = inspect(snapshot, selected)
    feedback = None
    history = [{"role": message["role"], "content": message["content"]} for message in conversation[-12:]
               if message["role"] in ("user", "assistant")]
    for request_number in range(24):
        if cancelled.is_set():
            raise WorkspaceError("Task cancelled. The accepted revision is unchanged.", "cancelled")
        if time.monotonic() - started > 600:
            raise WorkspaceError("The agent reached its ten-minute task limit.", "timeout")
        progress({"stage": "thinking", "message": "Inspecting the model and planning the next operation.",
                  "requests_used": request_number + 1, "max_requests": 24})
        context = {"request": prompt, "selected_instance_id": selected, "geometry": observation,
                   "completed_commands": actions, "last_tool_error": feedback}
        try:
            responses = queue.Queue()
            def ask_model():
                try:
                    responses.put(model_call(SYSTEM.format(schema=json.dumps(AgentAction.model_json_schema())),
                                             json.dumps(context), history=history, max_tokens=4096))
                except Exception as error:
                    responses.put(error)
            threading.Thread(target=ask_model, daemon=True).start()
            while True:
                if cancelled.is_set():
                    raise WorkspaceError("Task cancelled. The accepted revision is unchanged.", "cancelled")
                if time.monotonic() - started > 600:
                    raise WorkspaceError("The agent reached its ten-minute task limit.", "timeout")
                try:
                    response = responses.get(timeout=0.05)
                    break
                except queue.Empty:
                    pass
            if isinstance(response, Exception):
                raise response
            action = AgentAction.model_validate_json(response.text)
        except ValueError as error:
            feedback = "Invalid tool response: " + str(error)[:2000]
            continue
        if cancelled.is_set():
            raise WorkspaceError("Task cancelled. The accepted revision is unchanged.", "cancelled")
        if action.status != "tool":
            if action.status == "done" and not actions:
                return {"status": "done", "message": action.message, "snapshot": snapshot, "commands": []}
            return {"status": action.status, "message": action.message, "snapshot": snapshot, "commands": actions}
        command = action.command.model_dump(mode="json")
        if selected and command["instance_id"] != selected:
            feedback = "This task is restricted to the selected component instance."
            continue
        progress({"stage": "modelling", "message": action.message})
        try:
            snapshot = execute(snapshot, command)
            actions.append(command)
            observation = inspect(snapshot, selected)
            feedback = None
            progress({"stage": "candidate", "message": action.message, "candidate": snapshot})
        except WorkspaceError as error:
            feedback = str(error)
    raise WorkspaceError("The agent reached its 24-request limit. The accepted revision is unchanged.", "request_limit")
