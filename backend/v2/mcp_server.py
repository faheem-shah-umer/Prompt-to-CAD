"""Stdio MCP façade over the application's scoped CAD tool session."""

import json
import base64
from pathlib import Path
import os
import sys
import urllib.request

from .cad_tools import TOOLS
from backend.native.runtime_identity import RuntimeIdentity


def bridge_call(message):
    call = urllib.request.Request(
        os.environ["PROMPTCAD_TOOL_URL"], data=json.dumps(message).encode(), method="POST",
        headers={"Authorization": "Bearer " + os.environ["PROMPTCAD_TOOL_TOKEN"], "Content-Type": "application/json"})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(call, timeout=120) as response:
        return json.load(response)


def serve(input_stream=sys.stdin, output_stream=sys.stdout):
    runtime = RuntimeIdentity("mcp", tools=TOOLS)
    tool_names = {tool["name"] for tool in TOOLS}
    for line in input_stream:
        request = None
        listed = None
        try:
            if len(line) > 1024 * 1024:
                raise ValueError("MCP request exceeds limit")
            request = json.loads(line)
            method = request["method"]
            if "id" not in request:
                continue
            runtime.ensure_current()
            if method == "initialize":
                result = {
                    "protocolVersion": request.get("params", {}).get("protocolVersion", "2024-11-05"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "Prompt to CAD tools", "version": "0.3.0"},
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                if os.environ.get("PROMPTCAD_TOOL_URL"):
                    peer = runtime.report()
                    answer = bridge_call({"name": "_runtime_check", "arguments": peer})
                    if not answer.get("result", {}).get("verified"):
                        raise ValueError("CAD runtime handshake failed")
                    listed = peer
                result = {"tools": TOOLS}
            elif method == "tools/call":
                message = request.get("params", {})
                if message.get("name") not in tool_names:
                    raise ValueError("Unknown CAD tool")
                answer = bridge_call(message)
                result = {
                    "content": [{"type": "text", "text": json.dumps({k: v for k, v in answer.get("result", answer).items() if k != "image_data"}, allow_nan=False)}],
                    "isError": "error" in answer,
                }
                if answer.get("result", {}).get("image_data"):
                    result["content"].append({"type": "image", "mimeType": "image/png", "data": answer["result"]["image_data"]})
                if message["name"] == "cad_viewport" and answer.get("result", {}).get("image"):
                    image = answer["result"]["image"]
                    result["content"].append(
                        {
                            "type": "image",
                            "mimeType": "image/png",
                            "data": base64.b64encode(Path(image["path"]).read_bytes()).decode(),
                        }
                    )
            else:
                raise ValueError("Unsupported MCP method")
            reply = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except Exception as error:
            reply = {
                "jsonrpc": "2.0",
                "id": request.get("id") if isinstance(request, dict) else None,
                "error": {"code": -32603, "message": type(error).__name__ + ": CAD tool transport failed"},
            }
        output_stream.write(json.dumps(reply, allow_nan=False) + "\n")
        output_stream.flush()
        if listed is not None and "result" in reply:
            try:
                bridge_call({"name": "_runtime_list_returned", "arguments": listed})
            except (OSError, ValueError):
                pass  # The list was already returned. An unavailable log must not block CAD.


if __name__ == "__main__":
    serve()
