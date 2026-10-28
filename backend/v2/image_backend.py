"""Tripo v3 image reconstruction. This service has its own user key and billing."""

import hashlib
import ipaddress
import math
import os
import re
import socket
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from backend.native.contracts import WorkspaceError
from backend.native.documents import write_json

BASE = "https://openapi.tripo3d.ai/v3"
MODEL = "v3.1-20260211"


class Tripo:
    def __init__(self, key, cancelled, notify=lambda event: None, client=None):
        self.key, self.cancelled, self.notify = key, cancelled, notify
        self.client = client or httpx.Client(timeout=30, trust_env=False, follow_redirects=False)
        self.owns_client = client is None

    def request(self, method, path, **kwargs):
        try:
            response = self.client.request(
                method, BASE + path, headers={"Authorization": "Bearer " + self.key}, **kwargs
            )
            if response.status_code >= 400:
                raise WorkspaceError(
                    f"Tripo returned HTTP {response.status_code}. Check the image-service key, credits and account permissions.",
                    "image_provider_error",
                )
            body = response.json()
            if body.get("code") != 0:
                raise WorkspaceError(
                    "Tripo rejected the request (code "
                    + str(body.get("code"))
                    + "). Check the image-service dashboard.",
                    "image_provider_error",
                )
            return body["data"]
        except (httpx.HTTPError, ValueError, KeyError):
            raise WorkspaceError(
                "The image service could not be reached or returned an invalid response. No automatic paid retry was made.",
                "image_provider_network",
            ) from None

    def generate(self, reference, target_size_mm, destination, record_path, resume=None, context=None):
        if not self.key:
            raise WorkspaceError(
                "Connect your own Tripo API key. Image generation is billed separately from Codex.",
                "image_not_connected",
            )
        if (
            type(target_size_mm) not in (int, float)
            or not math.isfinite(target_size_mm)
            or not 0.1 <= target_size_mm <= 100000
        ):
            raise WorkspaceError("Specify the model's longest dimension in millimetres.")
        path = Path(reference["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != reference["sha256"]:
            raise WorkspaceError("The reference image changed.", "asset_integrity")
        settings = {
            "model": MODEL,
            "face_limit": 20000,
            "texture": True,
            "pbr": True,
            "auto_size": False,
            "model_seed": 0,
            "texture_seed": 0,
        }
        record = {
            **(context or {}),
            "provider": "Tripo v3",
            "reference": reference,
            "settings": settings,
            "longest_dimension_mm": target_size_mm,
            "dimension_source": "user supplied; other dimensions inferred",
            "status": "running",
            "billing": "Separate Tripo API credits",
        }
        try:
            if resume:
                task_id = resume
            else:
                if self.cancelled.is_set():
                    raise WorkspaceError("Image generation cancelled before submission.", "cancelled")
                self.notify({"stage": "image_upload", "message": "Uploading reference to Tripo · separate API credits"})
                with path.open("rb") as stream:
                    uploaded = self.request(
                        "POST",
                        "/files",
                        files={
                            "file": (
                                path.name,
                                stream,
                                "image/" + ("jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else path.suffix[1:]),
                            )
                        },
                    )
                created = self.request(
                    "POST", "/generation/image-to-model", json={"input": uploaded["file_token"], **settings}
                )
                task_id = created["task_id"]
            if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", task_id):
                raise WorkspaceError("The image service returned an invalid task identifier.")
            record["remote_task_id"] = task_id
            write_json(record_path, record)
            deadline = time.monotonic() + 600
            failures = 0
            while time.monotonic() < deadline:
                if self.cancelled.is_set():
                    raise WorkspaceError(
                        "Stopped waiting. The remote image task may continue and consume Tripo credits; it can be resumed from its saved task record.",
                        "cancelled",
                    )
                try:
                    task = self.request("GET", "/tasks/" + task_id)
                    failures = 0
                except WorkspaceError as error:
                    if error.code != "image_provider_network" or failures >= 2:
                        raise
                    failures += 1
                    self.cancelled.wait(2 * failures)
                    continue
                status = task.get("status")
                self.notify(
                    {
                        "stage": "image_generation",
                        "message": "Tripo: " + str(status),
                        "progress": task.get("progress"),
                        "remote_task_id": task_id,
                    }
                )
                if status == "success":
                    self.download(task["output"]["model_url"], Path(destination))
                    record.update(
                        status="downloaded",
                        credits_consumed=task.get("credits_consumed"),
                        output_sha256=hashlib.sha256(Path(destination).read_bytes()).hexdigest(),
                    )
                    write_json(record_path, record)
                    return record
                if status in ("failed", "cancelled", "banned", "expired"):
                    raise WorkspaceError(
                        "Tripo task ended with status " + status + ". No geometry was accepted.",
                        "image_generation_failed",
                    )
                if status not in ("queued", "running"):
                    raise WorkspaceError("Tripo returned an unsupported task status.")
                self.cancelled.wait(2)
            raise WorkspaceError(
                "Image generation exceeded the local ten-minute wait. The remote task may still consume credits; resume the recorded task instead of generating again.",
                "timeout",
            )
        except Exception as error:
            record.update(status="interrupted" if self.cancelled.is_set() else "failed", message=str(error))
            write_json(record_path, record)
            raise
        finally:
            if self.owns_client:
                self.client.close()

    def download(self, url, destination):
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or not any(host == d or host.endswith("." + d) for d in ("tripo3d.ai", "tripo3d.com"))
        ):
            raise WorkspaceError(
                "Tripo returned an unrecognized model download host. No external file was fetched.",
                "image_download_host",
            )
        for address in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
            if not ipaddress.ip_address(address[4][0]).is_global:
                raise WorkspaceError("The image download host resolved to a private address.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".download")
        try:
            # No authorization header is forwarded to the CDN; signed URLs never enter logs or project metadata.
            with self.client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise WorkspaceError("The generated model download failed or expired.")
                count = 0
                with temporary.open("wb") as stream:
                    for chunk in response.iter_bytes():
                        if self.cancelled.is_set():
                            raise WorkspaceError("Image download cancelled.", "cancelled")
                        count += len(chunk)
                        if count > 100 * 1024 * 1024:
                            raise WorkspaceError("The generated model exceeds the 100 MB import limit.")
                        stream.write(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
            if temporary.read_bytes()[:4] != b"glTF":
                raise WorkspaceError("The image service did not return a supported GLB model.")
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
