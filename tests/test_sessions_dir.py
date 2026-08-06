import os
import tempfile
import unittest
from unittest import mock


class TestSessionsDir(unittest.TestCase):
    def test_get_sessions_dir_uses_platform_user_state_dir(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch("birdapp.session.platformdirs.user_state_dir", return_value=tmpdir),
        ):
            from birdapp import session as session_module

            sessions_dir = session_module.get_sessions_dir()

        self.assertEqual(sessions_dir, os.path.join(tmpdir, "sessions"))

