import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.native.contracts import WorkspaceError
from backend.v2.auth import AUTH, Connections

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.name == "nt", "V2 native workers and DPAPI require Windows")
class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.connections = Connections(Path(self.temporary.name))
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.claims = {
            "iss": AUTH,
            "sub": "fixture-subject",
            "aud": "fixture-client",
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
            "nonce": "fixture-nonce",
            "email": "fixture@example.test",
        }

    def tearDown(self):
        self.connections.cancel_login()
        self.temporary.cleanup()

    def tokens(
        self, claims=None, scopes="openid chatgpt.tokens.use.direct offline_access"
    ):
        return {
            "id_token": jwt.encode(claims or self.claims, self.key, algorithm="RS256"),
            "access_token": "fixture-access",
            "refresh_token": "fixture-refresh",
            "expires_in": 600,
            "scope": scopes,
        }

    def complete(self, tokens, old=None):
        with (
            patch(
                "backend.v2.auth.request_json",
                return_value={"issuer": AUTH, "jwks_uri": AUTH + "/jwks"},
            ),
            patch("jwt.PyJWKClient") as jwks,
        ):
            jwks.return_value.get_signing_key_from_jwt.return_value = SimpleNamespace(
                key=self.key.public_key()
            )
            return self.connections.complete(
                tokens, "fixture-client", "fixture-nonce", old
            )

    def test_invalid_api_connection_does_not_replace_the_selected_registration(self):
        self.complete(self.tokens())
        before = self.connections.status()["active"]["id"]
        with patch(
            "backend.v2.auth.request_json",
            side_effect=WorkspaceError("Invalid API key", "invalid_api_key"),
        ):
            with self.assertRaises(WorkspaceError):
                self.connections.api_key("fixture-invalid-key-never-transmitted")
        self.assertEqual(self.connections.status()["active"]["id"], before)
        with patch(
            "backend.v2.auth.request_json", return_value={"data": []}
        ) as request:
            self.connections.api_key("fixture-validated-key-never-transmitted")
        self.assertEqual(
            request.call_args.args[:2], ("GET", "https://api.openai.com/v1/models")
        )
        self.assertEqual(self.connections.status()["active"]["connection"], "api")

    def test_retired_image_key_migration_preserves_accounts_and_host(self):
        self.complete(self.tokens())
        data = self.connections.vault.read()
        data["tripo_key"] = "retired-fixture-secret"
        self.connections.vault.write(data)
        migrated = Connections(self.connections.vault.folder)
        result = migrated.vault.read()
        self.assertNotIn("tripo_key", result)
        self.assertEqual(result["accounts"], data["accounts"])
        self.assertEqual(result["host_id"], data["host_id"])

    def test_signed_identity_scope_nonce_and_returning_account_binding(self):
        tokens = self.tokens()
        self.assertTrue(self.complete(tokens))
        active, account = self.connections.credential()
        self.assertEqual(account["subject"], "fixture-subject")
        with self.assertRaises(jwt.InvalidAudienceError):
            self.complete(self.tokens({**self.claims, "aud": "another-client"}))
        with self.assertRaises(WorkspaceError):
            self.complete(self.tokens({**self.claims, "nonce": "wrong"}))
        with self.assertRaises(WorkspaceError):
            self.complete(
                self.tokens({**self.claims, "sub": "another-subject"}), account
            )
        bad = self.tokens()
        bad["id_token"] = jwt.encode(
            self.claims,
            rsa.generate_private_key(public_exponent=65537, key_size=2048),
            algorithm="RS256",
        )
        with self.assertRaises(jwt.InvalidSignatureError):
            self.complete(bad)
        self.assertEqual(self.connections.credential()[0], active)
        self.assertNotIn("fixture-access", json.dumps(self.connections.status()))

    def test_missing_plan_scope_preserves_registration_but_refuses_inference(self):
        self.assertFalse(self.complete(self.tokens(scopes="openid profile email")))
        status = self.connections.status()
        self.assertFalse(status["active"]["plan_enabled"])
        self.assertIn("disabled", status["billing"])
        with self.assertRaises(WorkspaceError) as missing:
            self.connections.credential()
        self.assertEqual(missing.exception.code, "plan_permission_missing")
        self.assertEqual(len(status["accounts"]), 1)

    def test_authorization_has_loopback_pkce_and_stable_host_registration(self):
        result = self.connections.begin()
        query = parse_qs(urlsplit(result["authorization_url"]).query)
        self.assertEqual(query["client_id"], ["dynamic_agent_client"])
        self.assertEqual(query["agent_name_hint"], ["Prompt to CAD"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        callback = urlsplit(query["redirect_uri"][0])
        self.assertEqual(callback.hostname, "127.0.0.1")
        self.assertEqual(callback.path, "/auth/callback")
        self.assertGreater(len(query["state"][0]), 30)
        host = query["ext_agent_host_id"][0]
        self.connections.cancel_login()
        again = parse_qs(urlsplit(self.connections.begin()["authorization_url"]).query)
        self.assertEqual(again["ext_agent_host_id"][0], host)
        self.assertNotEqual(query["state"], again["state"])

    def test_primary_sign_in_reuses_client_after_disconnect_and_serializes_attempts(
        self,
    ):
        self.complete(self.tokens())
        before = self.connections.vault.read()
        query = parse_qs(urlsplit(self.connections.begin()["authorization_url"]).query)
        self.assertEqual(query["client_id"], ["fixture-client"])
        self.assertNotIn("agent_name_hint", query)
        self.assertEqual(query["ext_agent_host_id"], [before["host_id"]])
        with self.assertRaises(WorkspaceError) as pending:
            self.connections.begin()
        self.assertEqual(pending.exception.code, "sign_in_pending")
        self.connections.cancel_login()
        with patch(
            "backend.v2.auth.request_json",
            return_value={"revocation_endpoint": AUTH + "/revoke"},
        ):
            result = self.connections.disconnect()
        self.assertTrue(result["remote_revocation_confirmed"])
        self.assertEqual(result["state"], "disconnected")
        query = parse_qs(urlsplit(self.connections.begin()["authorization_url"]).query)
        self.assertEqual(query["client_id"], ["fixture-client"])
        self.connections.cancel_login()
        self.complete(self.tokens())
        self.assertEqual(len(self.connections.status()["accounts"]), 1)
        self.assertEqual(self.connections.vault.read()["host_id"], before["host_id"])

    def test_duplicate_email_registrations_remain_distinct_and_old_revoke_preserves_primary(
        self,
    ):
        self.complete(self.tokens())
        data = self.connections.vault.read()
        primary = data["active"]
        data["accounts"]["legacy-registration"] = {
            **data["accounts"][primary],
            "client_id": "legacy-client",
        }
        self.connections.vault.write(data)
        accounts = self.connections.status()["accounts"]
        self.assertEqual(len(accounts), 2)
        self.assertNotEqual(accounts[0]["label"], accounts[1]["label"])
        with patch(
            "backend.v2.auth.request_json", side_effect=WorkspaceError("offline")
        ):
            result = self.connections.disconnect("legacy-registration")
        self.assertFalse(result["remote_revocation_confirmed"])
        self.assertIn("not confirmed", result["message"])
        self.assertFalse(
            self.connections.disconnect("legacy-registration")[
                "remote_revocation_confirmed"
            ]
        )
        self.assertEqual(self.connections.credential()[0], primary)
        self.assertNotIn(
            "refresh_token",
            self.connections.vault.read()["accounts"]["legacy-registration"],
        )

    def test_model_discovery_is_coalesced_cached_and_account_scoped(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading

        self.complete(self.tokens())
        response = {"models": [{"slug": "fixture-model", "visibility": "list"}]}
        with patch("backend.v2.auth.request_json", return_value=response) as request:
            self.connections.models()
            self.connections.models()
            self.assertEqual(request.call_count, 1)
            self.connections.models(refresh=True)
            self.assertEqual(request.call_count, 2)
            data = self.connections.vault.read()
            primary = data["active"]
            data["accounts"]["other-registration"] = {
                **data["accounts"][primary],
                "client_id": "other-client",
            }
            self.connections.vault.write(data)
            self.connections.select("other-registration")
            self.connections.models()
            self.assertEqual(request.call_count, 3)
            self.connections.select(primary)
            self.connections.models()
            self.assertEqual(request.call_count, 3)
        started, release = threading.Event(), threading.Event()

        def fetch(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(5))
            return response

        with (
            patch("backend.v2.auth.request_json", side_effect=fetch) as request,
            ThreadPoolExecutor(max_workers=4) as executor,
        ):
            futures = [executor.submit(self.connections.models, True)]
            self.assertTrue(started.wait(5))
            futures.extend(executor.submit(self.connections.models) for _ in range(3))
            release.set()
            for future in futures:
                self.assertEqual(future.result()["models"][0]["id"], "fixture-model")
            self.assertEqual(request.call_count, 1)

    def test_expired_or_cancelled_login_emits_local_status_without_provider_requests(
        self,
    ):
        events = []
        self.connections.notify = events.append
        with patch("backend.v2.auth.request_json") as request:
            self.connections.begin()
            self.connections.expire_login(self.connections.pending)
            self.assertFalse(events[-1]["provider_status"]["signing_in"])
            self.assertIn("expired", events[-1]["message"])
            self.connections.begin()
            self.connections.cancel_login()
            self.assertFalse(events[-1]["provider_status"]["signing_in"])
            self.assertEqual(request.call_count, 0)

    def test_explicit_replacement_and_host_login_lease_keep_primary_until_success(self):
        self.complete(self.tokens())
        before = self.connections.status()["active"]["id"]
        uri = self.connections.begin(new_registration=True)["authorization_url"]
        query = parse_qs(urlsplit(uri).query)
        self.assertEqual(query["client_id"], ["dynamic_agent_client"])
        self.assertEqual(query["agent_name_hint"], ["Prompt to CAD"])
        self.assertEqual(self.connections.status()["active"]["id"], before)
        other = Connections(self.connections.vault.folder)
        with self.assertRaises(WorkspaceError) as pending:
            other.begin()
        self.assertEqual(pending.exception.code, "sign_in_pending")
        self.connections.cancel_login()
        other.begin()
        other.cancel_login()
        self.assertEqual(self.connections.status()["active"]["id"], before)

    def test_forget_legacy_removes_only_local_entry_and_preserves_primary_and_host(
        self,
    ):
        self.complete(self.tokens())
        data = self.connections.vault.read()
        primary = data["active"]
        host = data["host_id"]
        data["accounts"]["legacy-account"] = {
            **data["accounts"][primary],
            "client_id": "legacy-client",
        }
        self.connections.vault.write(data)
        with self.assertRaises(WorkspaceError):
            self.connections.forget(primary)
        with patch(
            "backend.v2.auth.request_json",
            side_effect=WorkspaceError("Synthetic offline"),
        ):
            result = self.connections.forget("legacy-account")
        self.assertFalse(result["remote_revocation_confirmed"])
        after = self.connections.vault.read()
        self.assertNotIn("legacy-account", after["accounts"])
        self.assertEqual(after["active"], primary)
        self.assertEqual(after["host_id"], host)

    def test_refresh_rotates_atomically_and_terminal_revocation_never_switches_billing(
        self,
    ):
        self.complete(self.tokens())
        with self.connections.vault.lock:
            data = self.connections.vault.read()
            aid = data["active"]
            data["accounts"][aid]["expires_at"] = 0
            self.connections.vault.write(data)
        with patch(
            "backend.v2.auth.request_json",
            return_value={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
            },
        ):
            self.assertEqual(
                self.connections.credential()[1]["refresh_token"], "new-refresh"
            )
        with patch("backend.v2.auth.request_json", return_value={"data": []}):
            self.connections.api_key("fixture-api-credential-not-real")
        self.connections.select(aid)
        with self.connections.vault.lock:
            data = self.connections.vault.read()
            data["accounts"][aid]["expires_at"] = 0
            self.connections.vault.write(data)
        with patch(
            "backend.v2.auth.request_json",
            side_effect=WorkspaceError("revoked", "invalid_grant"),
        ):
            with self.assertRaises(WorkspaceError) as revoked:
                self.connections.credential()
        self.assertEqual(revoked.exception.code, "reauthorization_required")
        self.assertEqual(self.connections.status()["active"]["id"], aid)
        with self.assertRaises(WorkspaceError):
            self.connections.credential()


if __name__ == "__main__":
    unittest.main()
