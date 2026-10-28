"""App-owned public OAuth client. Tokens never cross the desktop RPC boundary."""

import base64
import ctypes
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import httpx
from backend.native.contracts import WorkspaceError
from backend.app.project_lock import revision_lock

APP_NAME = "Prompt to CAD V2"
AUTH = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"


def request_json(method, url, **kwargs):
    try:
        with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = client.request(method, url, **kwargs)
        if response.status_code >= 400:
            code = "provider_error"
            try:
                error = response.json().get("error", {})
                code = error.get("code", error.get("type", code)) if isinstance(error, dict) else error
            except (ValueError, AttributeError):
                pass
            code = code if isinstance(code, str) else "provider_error"
            safe_codes = {
                "invalid_grant",
                "invalid_client",
                "insufficient_quota",
                "rate_limit_exceeded",
                "model_not_found",
                "invalid_refresh_token",
                "token_expired",
                "refresh_token_expired",
                "refresh_token_invalidated",
                "refresh_token_reused",
                "subscription_sharing_user_not_eligible",
                "subscription_sharing_usage_limit_exceeded",
                "subscription_sharing_usage_unavailable",
                "subscription_sharing_unsupported_capability",
                "subscription_sharing_route_not_supported",
                "subscription_sharing_invalid_user",
                "subscription_sharing_user_unavailable",
                "chatpass_v2_scope_not_authorized",
                "chatpass_v2_invalid_authorization_context",
            }
            label = code if code in safe_codes else "provider_error"
            error = WorkspaceError(
                f"Provider returned HTTP {response.status_code} ({label}). Check the connected account, model or usage. Billing was not changed.",
                label,
            )
            error.http_status = response.status_code
            error.request_id = response.headers.get("x-request-id", "")[:120]
            raise error
        return response.json() if response.content else {}
    except httpx.HTTPError:
        raise WorkspaceError(
            "Cannot reach the provider. Check the network and try again.", "provider_network"
        ) from None


class Vault:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / "credentials.dpapi"
        self.lock = threading.RLock()

    @staticmethod
    def protect(data, decrypt=False):
        if os.name != "nt":
            raise WorkspaceError(
                "This build requires Windows DPAPI for credential storage.", "credential_store_unavailable"
            )
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

        buffer = ctypes.create_string_buffer(data)
        source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        result = Blob()
        crypt = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
        function.argtypes = [
            ctypes.POINTER(Blob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(Blob),
        ]
        function.restype = wintypes.BOOL
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
            raise WorkspaceError(
                "Windows could not unlock the application credential store.", "credential_store_unavailable"
            )
        try:
            return ctypes.string_at(result.data, result.size)
        finally:
            kernel.LocalFree(result.data)

    def read(self):
        if not self.path.exists():
            return {"accounts": {}, "active": None, "host_id": "urn:uuid:" + str(uuid4())}
        return json.loads(self.protect(self.path.read_bytes(), decrypt=True))

    def write(self, data):
        encrypted = self.protect(json.dumps(data, allow_nan=False).encode())
        temporary = self.path.with_suffix("." + uuid4().hex + ".tmp")
        try:
            with temporary.open("wb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


class Connections:
    def __init__(self, folder, notify=lambda event: None, vault=None):
        self.vault = vault or Vault(folder)
        self.notify = notify
        self.pending = None
        self.lock = threading.RLock()
        self.last_error = ""
        with self.vault.lock, revision_lock(self.vault.folder):
            data = self.vault.read()
            self.vault.write(data)

    def status(self):
        with self.vault.lock:
            data = self.vault.read()
        accounts = [
            {
                "id": key,
                "email": a.get("email", "API key"),
                "workspace": a.get("workspace", "Workspace not reported"),
                "connection": a["mode"],
                "connected": bool(a.get("access_token") or a.get("api_key")),
                "plan_enabled": "chatgpt.tokens.use.direct" in a.get("scopes", []),
            }
            for key, a in data["accounts"].items()
        ]
        active = next((a for a in accounts if a["id"] == data["active"]), None)
        billing = "Disconnected"
        if active and active["connected"]:
            if active["connection"] == "chatgpt":
                billing = (
                    "ChatGPT plan and authorized credits"
                    if active["plan_enabled"]
                    else "Identity connected · plan permission disabled"
                )
            else:
                billing = "API billing (separate)"
        elif active:
            billing = "Disconnected · reconnect required"
        return {
            "accounts": accounts,
            "active": active,
            "signing_in": self.pending is not None,
            "error": self.last_error,
            "billing": billing,
            "usage": {
                "available": False,
                "message": "Allowance unavailable from this connection. Manage usage in ChatGPT Settings.",
            },
            "usage_url": "https://chatgpt.com/settings/usage",
        }

    def begin(self, account_id=None):
        with self.lock:
            if self.pending:
                raise WorkspaceError("A sign-in is already in progress.", "sign_in_pending")
            with self.vault.lock:
                data = self.vault.read()
            old = data["accounts"].get(account_id) if account_id else None
            if account_id and (not old or old["mode"] != "chatgpt"):
                raise WorkspaceError("Choose a saved ChatGPT registration.")
            state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
            owner = self

            class Callback(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def do_GET(self):
                    uri = urlsplit(self.path)
                    query = parse_qs(uri.query)
                    if uri.path != "/auth/callback" or not hmac.compare_digest(query.get("state", [""])[0], state):
                        self.send_error(400, "Invalid authorization callback")
                        return
                    try:
                        if "error" in query:
                            raise WorkspaceError(
                                "Authorization was declined. Plan use requires consent.", "access_denied"
                            )
                        issued = query.get("client_id", [old["client_id"] if old else ""])[0]
                        if not issued or issued == "dynamic_agent_client" or (old and issued != old["client_id"]):
                            raise WorkspaceError(
                                "The authorization registration does not match this attempt.", "invalid_client"
                            )
                        tokens = request_json(
                            "POST",
                            AUTH + "/api/accounts/oauth/token",
                            data={
                                "grant_type": "authorization_code",
                                "client_id": issued,
                                "code": query.get("code", [""])[0],
                                "code_verifier": verifier,
                                "redirect_uri": redirect,
                                "resource": RESOURCE,
                            },
                        )
                        enabled = owner.complete(tokens, issued, nonce, old, attempt=server)
                        message = (
                            "Connected. You can return to Prompt to CAD V2."
                            if enabled
                            else "Identity connected, but ChatGPT plan use is disabled. Reconnect and authorize plan use before running tasks."
                        )
                    except Exception as error:
                        owner.last_error = (
                            str(error)
                            if isinstance(error, WorkspaceError)
                            else "Sign-in validation failed. Start a fresh sign-in."
                        )
                        message = owner.last_error
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(message.encode())
                    if owner.pending is server:
                        owner.pending = None
                    owner.notify({"stage": "connection", "message": message})
                    threading.Thread(target=server.shutdown, daemon=True).start()

            server = HTTPServer(("127.0.0.1", 0), Callback)
            server.timeout = 1
            redirect = f"http://127.0.0.1:{server.server_port}/auth/callback"
            query = {
                "client_id": old["client_id"] if old else "dynamic_agent_client",
                "ext_agent_host_id": data["host_id"],
                "response_type": "code",
                "redirect_uri": redirect,
                "scope": SCOPES,
                "resource": RESOURCE,
                "state": state,
                "nonce": nonce,
                "code_challenge_method": "S256",
                "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .rstrip(b"=")
                .decode(),
            }
            if old:
                if old.get("email"):
                    query["login_hint"] = old["email"]
            else:
                query["agent_name_hint"] = APP_NAME
            self.pending = server
            self.last_error = ""

            def serve():
                try:
                    server.serve_forever(poll_interval=0.2)
                finally:
                    server.server_close()

            threading.Thread(target=serve, daemon=True).start()

            def expire():
                time.sleep(300)
                if self.pending is server:
                    self.pending = None
                    self.last_error = "Sign-in expired. Try again."
                    server.shutdown()

            threading.Thread(target=expire, daemon=True).start()
            return {"authorization_url": AUTH + "/api/accounts/authorize?" + urlencode(query)}

    def complete(self, tokens, issued, nonce, old=None, attempt=None):
        import jwt

        discovery = request_json("GET", AUTH + "/.well-known/openid-configuration")
        jwks = discovery["jwks_uri"]
        if (
            discovery["issuer"] != AUTH
            or urlsplit(jwks).scheme != "https"
            or urlsplit(jwks).hostname != "auth.openai.com"
        ):
            raise WorkspaceError("Untrusted identity provider metadata.")
        token = tokens["id_token"]
        key = jwt.PyJWKClient(jwks, timeout=30).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            issuer=AUTH,
            audience=issued,
            options={"require": ["exp", "iat", "sub", "nonce"]},
        )
        if not hmac.compare_digest(claims["nonce"], nonce) or (old and claims["sub"] != old["subject"]):
            raise WorkspaceError("The signed-in identity does not match this authorization attempt.")
        scopes = tokens.get("scope", "").split()
        record = {
            "mode": "chatgpt",
            "subject": claims["sub"],
            "client_id": issued,
            "email": claims.get("email", "ChatGPT account"),
            "workspace": "Workspace name not reported · registration " + issued[-8:],
            "scopes": scopes,
            "expires_at": time.time() + tokens["expires_in"],
            **{k: tokens[k] for k in ("access_token", "refresh_token", "id_token")},
        }
        key_id = hashlib.sha256((claims["sub"] + ":" + issued).encode()).hexdigest()[:24]
        with self.lock, self.vault.lock, revision_lock(self.vault.folder):
            if attempt is not None and self.pending is not attempt:
                raise WorkspaceError("This sign-in attempt was cancelled or expired.", "cancelled")
            data = self.vault.read()
            data["accounts"][key_id] = record
            data["active"] = key_id
            self.vault.write(data)
        return "chatgpt.tokens.use.direct" in scopes

    def cancel_login(self):
        with self.lock:
            server, self.pending = self.pending, None
        if server:
            server.shutdown()
        return self.status()

    def api_key(self, key):
        if not isinstance(key, str) or len(key.strip()) < 20:
            raise WorkspaceError("Enter a valid user-supplied API key.")
        with self.vault.lock, revision_lock(self.vault.folder):
            data = self.vault.read()
            key_id = "api-" + uuid4().hex[:12]
            data["accounts"][key_id] = {
                "mode": "api",
                "api_key": key.strip(),
                "workspace": "API organization associated with this key",
            }
            data["active"] = key_id
            self.vault.write(data)
        return self.status()

    def select(self, key_id):
        with self.vault.lock, revision_lock(self.vault.folder):
            data = self.vault.read()
            if key_id not in data["accounts"]:
                raise WorkspaceError("Unknown account registration.")
            data["active"] = key_id
            self.vault.write(data)
        return self.status()

    def credential(self):
        with self.vault.lock, revision_lock(self.vault.folder):
            data = self.vault.read()
            account = data["accounts"].get(data["active"])
            if not account or not (account.get("access_token") or account.get("api_key")):
                raise WorkspaceError("Connect your own ChatGPT plan or API key in Account settings.", "not_connected")
            if account["mode"] == "chatgpt" and "chatgpt.tokens.use.direct" not in account.get("scopes", []):
                raise WorkspaceError(
                    "This identity has not authorized ChatGPT plan use. Reconnect and enable plan usage.",
                    "plan_permission_missing",
                )
            if account["mode"] == "chatgpt" and account["expires_at"] <= time.time() + 90:
                try:
                    tokens = request_json(
                        "POST",
                        AUTH + "/api/accounts/oauth/token",
                        data={
                            "grant_type": "refresh_token",
                            "client_id": account["client_id"],
                            "refresh_token": account["refresh_token"],
                            "resource": RESOURCE,
                        },
                    )
                except WorkspaceError as error:
                    if error.code in (
                        "invalid_grant",
                        "invalid_refresh_token",
                        "token_expired",
                        "refresh_token_expired",
                        "refresh_token_invalidated",
                        "refresh_token_reused",
                    ):
                        for key in ("access_token", "refresh_token", "id_token"):
                            account.pop(key, None)
                        self.vault.write(data)
                        raise WorkspaceError(
                            "This renewable session is no longer valid. Reconnect the saved ChatGPT registration.",
                            "reauthorization_required",
                        ) from None
                    raise
                scopes = tokens.get("scope", " ".join(account["scopes"])).split()
                if "chatgpt.tokens.use.direct" not in scopes:
                    raise WorkspaceError(
                        "Plan permission was revoked. Reconnect this account.", "plan_permission_missing"
                    )
                account.update({k: tokens[k] for k in ("access_token", "refresh_token", "id_token") if k in tokens})
                account.update(expires_at=time.time() + tokens["expires_in"], scopes=scopes)
                self.vault.write(data)
            return data["active"], dict(account)

    def models(self):
        _, account = self.credential()
        response = request_json(
            "GET",
            RESOURCE + "/models",
            headers={"Authorization": "Bearer " + account.get("access_token", account.get("api_key", ""))},
        )
        if account["mode"] == "chatgpt":
            models = [
                {"id": m["slug"], "name": m.get("display_name", m["slug"]), "access": "Not yet verified by inference"}
                for m in response.get("models", [])
                if m.get("visibility") == "list"
            ]
        else:
            models = [
                {"id": m["id"], "name": m["id"], "access": "Catalogue entry; inference not verified"}
                for m in response.get("data", [])
            ]
        return {"models": models, "billing": self.status()["billing"]}

    def disconnect(self):
        confirmed = True
        with self.vault.lock, revision_lock(self.vault.folder):
            data = self.vault.read()
            account = data["accounts"].get(data["active"])
            if account and account["mode"] == "chatgpt" and account.get("refresh_token"):
                try:
                    discovery = request_json("GET", AUTH + "/.well-known/openid-configuration")
                    endpoint = discovery["revocation_endpoint"]
                    if urlsplit(endpoint).hostname != "auth.openai.com" or urlsplit(endpoint).scheme != "https":
                        raise ValueError()
                    request_json(
                        "POST",
                        endpoint,
                        data={
                            "token": account["refresh_token"],
                            "token_type_hint": "refresh_token",
                            "client_id": account["client_id"],
                        },
                    )
                except Exception:
                    confirmed = False
            if account:
                for key in ("access_token", "refresh_token", "id_token", "api_key"):
                    account.pop(key, None)
            data["active"] = None
            self.vault.write(data)
        return {
            **self.status(),
            "remote_revocation_confirmed": confirmed,
            "message": "Disconnected."
            if confirmed
            else "Disconnected locally. Remote revocation was not confirmed; manage access in ChatGPT Settings.",
        }
