import json
import tempfile
import os
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

    def tokens(self, claims=None, scopes="openid chatgpt.tokens.use.direct offline_access"):
        return {
            "id_token": jwt.encode(claims or self.claims, self.key, algorithm="RS256"),
            "access_token": "fixture-access",
            "refresh_token": "fixture-refresh",
            "expires_in": 600,
            "scope": scopes,
        }

    def complete(self, tokens, old=None):
        with (
            patch("backend.v2.auth.request_json", return_value={"issuer": AUTH, "jwks_uri": AUTH + "/jwks"}),
            patch("jwt.PyJWKClient") as jwks,
        ):
            jwks.return_value.get_signing_key_from_jwt.return_value = SimpleNamespace(key=self.key.public_key())
            return self.connections.complete(tokens, "fixture-client", "fixture-nonce", old)

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
            self.complete(self.tokens({**self.claims, "sub": "another-subject"}), account)
        bad = self.tokens()
        bad["id_token"] = jwt.encode(
            self.claims, rsa.generate_private_key(public_exponent=65537, key_size=2048), algorithm="RS256"
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
        self.assertEqual(query["agent_name_hint"], ["Prompt to CAD V2"])
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

    def test_refresh_rotates_atomically_and_terminal_revocation_never_switches_billing(self):
        self.complete(self.tokens())
        with self.connections.vault.lock:
            data = self.connections.vault.read()
            aid = data["active"]
            data["accounts"][aid]["expires_at"] = 0
            self.connections.vault.write(data)
        with patch(
            "backend.v2.auth.request_json",
            return_value={"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600},
        ):
            self.assertEqual(self.connections.credential()[1]["refresh_token"], "new-refresh")
        self.connections.api_key("fixture-api-credential-not-real")
        self.connections.select(aid)
        with self.connections.vault.lock:
            data = self.connections.vault.read()
            data["accounts"][aid]["expires_at"] = 0
            self.connections.vault.write(data)
        with patch("backend.v2.auth.request_json", side_effect=WorkspaceError("revoked", "invalid_grant")):
            with self.assertRaises(WorkspaceError) as revoked:
                self.connections.credential()
        self.assertEqual(revoked.exception.code, "reauthorization_required")
        self.assertEqual(self.connections.status()["active"]["id"], aid)
        with self.assertRaises(WorkspaceError):
            self.connections.credential()


if __name__ == "__main__":
    unittest.main()
