import base64
import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from birdapp import oauth2


def _base64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

class TestOAuth2(unittest.TestCase):
    def test_default_oauth2_scopes_include_tweet_write(self) -> None:
        self.assertIn("tweet.write", oauth2.DEFAULT_OAUTH2_SCOPES.split())

    def test_create_pkce_pair(self) -> None:
        code_verifier, code_challenge = oauth2.create_pkce_pair()
        self.assertGreaterEqual(len(code_verifier), 43)
        self.assertLessEqual(len(code_verifier), 128)

        expected = _base64url_encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
        self.assertEqual(code_challenge, expected)

    def test_build_authorize_url(self) -> None:
        url = oauth2.build_authorize_url(
            state="state123",
            code_challenge="challenge",
            scopes=["tweet.read", "users.read"],
            redirect_uri="http://127.0.0.1:8080/callback",
            client_id="client123",
        )

        parsed = urlparse(url)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "x.com")
        self.assertEqual(parsed.path, "/i/oauth2/authorize")

        params = parse_qs(parsed.query)
        self.assertEqual(params["response_type"][0], "code")
        self.assertEqual(params["client_id"][0], "client123")
        self.assertEqual(params["redirect_uri"][0], "http://127.0.0.1:8080/callback")
        self.assertEqual(params["state"][0], "state123")
        self.assertEqual(params["code_challenge"][0], "challenge")
        self.assertEqual(params["code_challenge_method"][0], "S256")
        self.assertEqual(params["scope"][0], "tweet.read users.read")

    def test_token_exchange_shape(self) -> None:
        response = Mock()
        response.ok = True
        response.json.return_value = {
            "access_token": "access-token",
            "token_type": "bearer",
        }

        with patch("birdapp.oauth2.requests.post", return_value=response) as post:
            token = oauth2.exchange_code_for_token(
                code="code123",
                code_verifier="verifier123",
                redirect_uri="http://127.0.0.1:8080/callback",
                client_id="client123",
                client_secret=None,
            )
            post.assert_called_once()

        self.assertIn("access_token", token)
        self.assertIn("token_type", token)

    def test_token_exchange_missing_auth_header_message(self) -> None:
        response = Mock()
        response.ok = False
        response.status_code = 401
        response.text = '{"error":"unauthorized_client","error_description":"Missing valid authorization header"}'

        with patch("birdapp.oauth2.requests.post", return_value=response):
            with self.assertRaises(RuntimeError) as ctx:
                oauth2.exchange_code_for_token(
                    code="code123",
                    code_verifier="verifier123",
                    redirect_uri="http://127.0.0.1:8080/callback",
                    client_id="client123",
                    client_secret=None,
                )

        self.assertIn("Missing valid authorization header", str(ctx.exception))
        self.assertIn("confidential client", str(ctx.exception))

    def test_get_user_me_shape(self) -> None:
        response = Mock()
        response.ok = True
        response.json.return_value = {"data": {"id": "1", "username": "user"}}

        with patch("birdapp.oauth2.requests.get", return_value=response) as get:
            payload = oauth2.get_user_me(access_token="access-token")
            get.assert_called_once()

        self.assertIn("data", payload)

    def test_write_oauth2_fixtures(self) -> None:
        token = {
            "access_token": "access-token-1234567890",
            "refresh_token": "refresh-token-1234567890",
            "token_type": "bearer",
        }
        user_payload = {"data": {"id": "1", "username": "user"}}

        with tempfile.TemporaryDirectory() as tmpdir:
            oauth2.write_oauth2_fixtures(token=token, user_payload=user_payload, fixtures_dir=tmpdir)
            token_path = os.path.join(tmpdir, "oauth2_token.json")
            user_path = os.path.join(tmpdir, "oauth2_user.json")

            self.assertTrue(os.path.exists(token_path))
            self.assertTrue(os.path.exists(user_path))

            with open(token_path, "r") as f:
                stored_token = json.load(f)
            with open(user_path, "r") as f:
                stored_user = json.load(f)

            self.assertEqual(stored_user, user_payload)
            self.assertNotEqual(stored_token["access_token"], token["access_token"])
            self.assertNotEqual(stored_token["refresh_token"], token["refresh_token"])

