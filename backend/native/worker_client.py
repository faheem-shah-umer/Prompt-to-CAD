import json
import math
import os
import queue
import subprocess
import sys
import site
import threading
import time
from pathlib import Path
from uuid import uuid4

from .contracts import WorkspaceError
from .runtime_identity import RuntimeIdentity


class GeometryWorker:
    def __init__(self, log_dir, timeout=120):
        self.log_dir = Path(log_dir)
        if not math.isfinite(timeout) or timeout <= 0:
            raise WorkspaceError("CAD_GEOMETRY_TIMEOUT must be a finite, positive number.", "configuration")
        self.timeout = timeout
        self.process = None
        self.log = None
        self.responses = None
        self.runtime_identity = RuntimeIdentity("geometry_client")
        # One request at a time on the worker pipe, even when a background task and the UI both need geometry.
        self.call_lock = threading.RLock()

    def start(self):
        if self.process and self.process.poll() is None:
            return
        self.close()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log = (self.log_dir / "geometry.log").open("ab")
        self.responses = queue.Queue()
        responses = self.responses
        interpreter = sys.executable
        environment = os.environ.copy()
        environment.update(self.runtime_identity.environment())
        if os.name == "nt" and sys.prefix != sys.base_prefix:
            # The Windows venv executable is a launcher; kill the actual interpreter on timeout.
            interpreter = sys._base_executable
        environment["PYTHONPATH"] = os.pathsep.join([str(self.runtime_identity.root), *site.getsitepackages()])
        self.process = subprocess.Popen(
            [interpreter, "-B", "-m", "backend.native.worker"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=self.log, text=True, encoding="utf-8",
            cwd=Path(__file__).resolve().parents[2], env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        process = self.process

        def read():
            try:
                for line in process.stdout:
                    responses.put(json.loads(line))
            except (ValueError, OSError) as error:
                responses.put({"reader_error": str(error)})
            finally:
                responses.put(None)
        threading.Thread(target=read, daemon=True).start()

    def call(self, method, params, cancel=None, progress=None, timeout=None):
        with self.call_lock:
            return self._call(method, params, cancel, progress, timeout)

    def _call(self, method, params, cancel=None, progress=None, timeout=None):
        self.runtime_identity.ensure_current()
        self.start()
        request_id = uuid4().hex
        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        try:
            self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": request_id,
                                                 "method": method, "params": params}, allow_nan=False) + "\n")
            self.process.stdin.flush()
            while True:
                if cancel and cancel.is_set():
                    raise WorkspaceError("Task cancelled. The accepted revision is unchanged.", "cancelled")
                if time.monotonic() > deadline:
                    raise WorkspaceError("Geometry operation timed out. The accepted revision is unchanged.", "timeout")
                try:
                    reply = self.responses.get(timeout=0.05)
                except queue.Empty:
                    continue
                if reply is None or "reader_error" in reply:
                    raise WorkspaceError("The geometry worker stopped. The accepted revision is unchanged.", "worker_crashed")
                if "method" in reply:
                    if progress:
                        progress(reply["params"])
                    continue
                if reply.get("id") != request_id:
                    raise WorkspaceError("The geometry worker returned an unexpected response.", "protocol_error")
                self.runtime_identity.verify_peer(reply.get("runtime_identity", {}), "geometry")
                if "error" in reply:
                    error = reply["error"]
                    data = error.get("data", {})
                    raise WorkspaceError(
                        error["message"],
                        data.get("code", "geometry_failed"),
                        {key: value for key, value in data.items() if key != "code"},
                    )
                return reply["result"]
        except (BrokenPipeError, OSError) as error:
            self.close()
            raise WorkspaceError("Lost the geometry worker connection.", "worker_crashed") from error
        except WorkspaceError as error:
            if error.code in ("cancelled", "timeout", "worker_crashed", "protocol_error", "runtime_mismatch"):
                self.close()
            raise

    def close(self):
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            for stream in (self.process.stdin, self.process.stdout):
                if stream:
                    stream.close()
            self.process = None
        if self.log:
            self.log.close()
            self.log = None
