import contextlib
import io
import sys
import unittest
from unittest import mock

from birdapp import main as main_module


class TestTweetCli(unittest.TestCase):
    def test_tweet_help_includes_profile_flag(self) -> None:
        stdout = io.StringIO()
        with (
            mock.patch.object(sys, "argv", ["birdapp", "tweet", "--help"]),
            contextlib.redirect_stdout(stdout),
            self.assertRaises(SystemExit) as exc,
        ):
            main_module.main()

        # argparse uses SystemExit(0) on --help
        self.assertEqual(exc.exception.code, 0)
        self.assertIn("--profile", stdout.getvalue())

    def test_tweet_cli_accepts_positional_text(self) -> None:
        with (
            mock.patch.object(sys, "argv", ["birdapp", "tweet", "hello world"]),
            mock.patch("birdapp.main.post_tweet", return_value=(True, "ok")) as post_tweet,
            mock.patch("builtins.print"),
        ):
            main_module.main()

        post_tweet.assert_called_once_with(text="hello world", media_path=None, reply_to=None)

    def test_tweet_cli_still_accepts_text_flag(self) -> None:
        with (
            mock.patch.object(sys, "argv", ["birdapp", "tweet", "--text", "hello world"]),
            mock.patch("birdapp.main.post_tweet", return_value=(True, "ok")) as post_tweet,
            mock.patch("builtins.print"),
        ):
            main_module.main()

        post_tweet.assert_called_once_with(text="hello world", media_path=None, reply_to=None)

    def test_tweet_cli_reminds_to_login_for_oauth2(self) -> None:
        with (
            mock.patch.object(sys, "argv", ["birdapp", "tweet", "hello world"]),
            mock.patch("birdapp.main._has_oauth2_config", return_value=True),
            mock.patch("birdapp.main._has_oauth1_credentials", return_value=False),
            mock.patch("birdapp.main.has_oauth2_token", return_value=False),
            mock.patch("birdapp.main.post_tweet", return_value=(True, "ok")),
            mock.patch("builtins.print") as print_mock,
        ):
            main_module.main()

        messages = [" ".join(map(str, call.args)) for call in print_mock.call_args_list]
        self.assertTrue(any("auth login" in msg for msg in messages))

