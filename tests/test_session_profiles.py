import json
import tempfile
import unittest
from typing import Any, cast
from unittest import mock

from birdapp import session as session_module


class TestSessionProfiles(unittest.TestCase):
    def test_save_and_load_token_scoped_to_profile(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch.object(session_module, "get_sessions_dir", return_value=tmpdir),
        ):
            session_module.save_token(
                user_id="1",
                token={"access_token": "token-1"},
                profile="alice",
            )
            session_module.save_token(
                user_id="2",
                token={"access_token": "token-2"},
                profile="bob",
            )

            tokens_path = session_module.os.path.join(tmpdir, "tokens.json")
            with open(tokens_path) as f:
                stored = json.loads(f.read())

            self.assertIn("profiles", stored)
            self.assertIn("alice", stored["profiles"])
            self.assertIn("bob", stored["profiles"])
            self.assertEqual(
                stored["profiles"]["alice"]["1"]["access_token"],
                "token-1",
            )
            self.assertEqual(
                stored["profiles"]["bob"]["2"]["access_token"],
                "token-2",
            )

            token = session_module.load_token("1", profile="alice")
            self.assertIsNotNone(token)
            token = cast(dict[str, Any], token)
            self.assertEqual(token["access_token"], "token-1")
            self.assertIsNone(session_module.load_token("1", profile="bob"))
