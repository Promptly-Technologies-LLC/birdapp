import json
import os
import tempfile
import unittest
from unittest import mock


class TestTweetOAuth2(unittest.TestCase):
    def test_submit_tweet_uses_oauth2_when_token_present(self) -> None:
        """
        If an OAuth2 access token exists for the active profile, tweeting should
        use a Bearer token instead of OAuth1 user tokens.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Arrange: store an OAuth2 token for the active profile.
            tokens_path = os.path.join(tmpdir, "tokens.json")
            with open(tokens_path, "w") as f:
                json.dump(
                    {
                        "profiles": {
                            "WSPZoo": {
                                "123": {
                                    "access_token": "access-token-abc",
                                    "token_type": "bearer",
                                }
                            }
                        }
                    },
                    f,
                )

            from birdapp import tweet as tweet_module

            def _oauth1_should_not_be_used() -> None:
                raise AssertionError("OAuth1 should not be used when OAuth2 token exists")

            request_mock = mock.Mock()

            with (
                mock.patch("birdapp.config.get_active_profile", return_value="WSPZoo"),
                mock.patch("birdapp.session.get_sessions_dir", return_value=tmpdir),
                mock.patch.object(tweet_module, "create_oauth1_auth", side_effect=_oauth1_should_not_be_used),
                mock.patch.object(tweet_module.requests, "request", return_value=request_mock) as request,
            ):
                tweet_module.submit_tweet(text="hello from oauth2")

            # Assert: request uses Bearer auth header (OAuth2).
            _, kwargs = request.call_args
            headers = kwargs.get("headers") or {}
            self.assertEqual(headers.get("Authorization"), "Bearer access-token-abc")

    def test_submit_tweet_supports_mixed_auth_across_profiles(self) -> None:
        """
        When multiple profiles exist, tweeting should use the auth mechanism
        appropriate to the active profile:
        - OAuth2 when a stored token exists for that profile
        - OAuth1 when OAuth2 token does not exist for that profile
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tokens_path = os.path.join(tmpdir, "tokens.json")
            with open(tokens_path, "w") as f:
                json.dump(
                    {
                        "profiles": {
                            "WSPZoo": {
                                "123": {
                                    "access_token": "access-token-abc",
                                    "token_type": "bearer",
                                }
                            }
                        }
                    },
                    f,
                )

            from birdapp import tweet as tweet_module

            request_mock = mock.Mock()

            # OAuth2 profile should use Bearer token and never call OAuth1.
            with (
                mock.patch("birdapp.config.get_active_profile", return_value="WSPZoo"),
                mock.patch("birdapp.session.get_sessions_dir", return_value=tmpdir),
                mock.patch.object(
                    tweet_module,
                    "create_oauth1_auth",
                    side_effect=AssertionError("OAuth1 should not be used for OAuth2 profile"),
                ),
                mock.patch.object(tweet_module.requests, "request", return_value=request_mock) as request,
            ):
                tweet_module.submit_tweet(text="hello from wspzoo")

            _, kwargs = request.call_args
            headers = kwargs.get("headers") or {}
            self.assertEqual(headers.get("Authorization"), "Bearer access-token-abc")

            # OAuth1 profile should use OAuth1 auth and not send a Bearer token.
            oauth1_auth = object()
            with (
                mock.patch("birdapp.config.get_active_profile", return_value="christophcsmith"),
                mock.patch("birdapp.session.get_sessions_dir", return_value=tmpdir),
                mock.patch.object(tweet_module, "create_oauth1_auth", return_value=oauth1_auth),
                mock.patch.object(tweet_module.requests, "request", return_value=request_mock) as request,
            ):
                tweet_module.submit_tweet(text="hello from christophcsmith")

            _, kwargs = request.call_args
            self.assertIs(kwargs.get("auth"), oauth1_auth)
            headers = kwargs.get("headers") or {}
            self.assertNotEqual(headers.get("Authorization"), "Bearer access-token-abc")

    def test_submit_tweet_refreshes_oauth2_token_on_401_and_retries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tokens_path = os.path.join(tmpdir, "tokens.json")
            with open(tokens_path, "w") as f:
                json.dump(
                    {
                        "profiles": {
                            "WSPZoo": {
                                "123": {
                                    "access_token": "access-token-old",
                                    "refresh_token": "refresh-token-xyz",
                                    "token_type": "bearer",
                                }
                            }
                        }
                    },
                    f,
                )

            from birdapp import tweet as tweet_module

            response_401 = mock.Mock()
            response_401.ok = False
            response_401.status_code = 401

            response_ok = mock.Mock()
            response_ok.ok = True

            with (
                mock.patch("birdapp.config.get_active_profile", return_value="WSPZoo"),
                mock.patch("birdapp.session.get_sessions_dir", return_value=tmpdir),
                mock.patch.object(
                    tweet_module,
                    "create_oauth1_auth",
                    side_effect=AssertionError("OAuth1 should not be used for OAuth2 profile"),
                ),
                mock.patch("birdapp.oauth2.refresh_access_token", return_value={"access_token": "access-token-new", "token_type": "bearer"}) as refresh,
                mock.patch("birdapp.session.save_token") as save_token,
                mock.patch.object(tweet_module.requests, "request", side_effect=[response_401, response_ok]) as request,
                mock.patch("birdapp.config.get_credential", side_effect=lambda key, **_: {"X_OAUTH2_CLIENT_ID": "client123", "X_OAUTH2_CLIENT_SECRET": None}.get(key)),
            ):
                resp = tweet_module.submit_tweet(text="hello with refresh")

            self.assertIs(resp, response_ok)
            refresh.assert_called_once()
            save_token.assert_called_once()
            self.assertEqual(request.call_count, 2)
            _, second_kwargs = request.call_args
            headers = second_kwargs.get("headers") or {}
            self.assertEqual(headers.get("Authorization"), "Bearer access-token-new")

    def test_submit_tweet_prompts_oauth2_login_when_oauth2_configured_but_no_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            # No tokens.json (or an empty tokens file) for the profile.
            tokens_path = os.path.join(tmpdir, "tokens.json")
            with open(tokens_path, "w") as f:
                json.dump({"profiles": {}}, f)

            from birdapp import tweet as tweet_module

            def _oauth1_should_not_be_used() -> None:
                raise AssertionError("OAuth1 should not be used when OAuth2 is configured")

            with (
                mock.patch("birdapp.config.get_active_profile", return_value="WSPZoo"),
                mock.patch("birdapp.session.get_sessions_dir", return_value=tmpdir),
                mock.patch.object(tweet_module, "create_oauth1_auth", side_effect=_oauth1_should_not_be_used),
                mock.patch.object(
                    tweet_module.config_module,
                    "get_credential",
                    side_effect=lambda key, **_: {
                        "X_OAUTH2_CLIENT_ID": "client123",
                        "X_OAUTH2_REDIRECT_URI": "http://127.0.0.1:8080/callback",
                    }.get(key),
                ),
                self.assertRaises(RuntimeError) as exc,
            ):
                tweet_module.submit_tweet(text="hello")

            message = str(exc.exception)
            self.assertIn("auth login", message)
            self.assertIn("--profile WSPZoo", message)
            self.assertNotIn("auth config --oauth1", message)

    def test_submit_tweet_prompts_oauth2_login_when_token_401_and_cannot_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tokens_path = os.path.join(tmpdir, "tokens.json")
            with open(tokens_path, "w") as f:
                json.dump(
                    {
                        "profiles": {
                            "WSPZoo": {
                                "123": {
                                    "access_token": "access-token-old",
                                    "token_type": "bearer",
                                }
                            }
                        }
                    },
                    f,
                )

            from birdapp import tweet as tweet_module

            response_401 = mock.Mock()
            response_401.ok = False
            response_401.status_code = 401

            with (
                mock.patch("birdapp.config.get_active_profile", return_value="WSPZoo"),
                mock.patch("birdapp.session.get_sessions_dir", return_value=tmpdir),
                mock.patch.object(
                    tweet_module,
                    "create_oauth1_auth",
                    side_effect=AssertionError("OAuth1 should not be used for OAuth2 profile"),
                ),
                mock.patch.object(tweet_module.requests, "request", return_value=response_401),
                mock.patch("birdapp.oauth2.refresh_access_token") as refresh,
                mock.patch("birdapp.session.save_token") as save_token,
                mock.patch.object(
                    tweet_module.config_module,
                    "get_credential",
                    side_effect=lambda key, **_: {
                        "X_OAUTH2_CLIENT_ID": "client123",
                        "X_OAUTH2_REDIRECT_URI": "http://127.0.0.1:8080/callback",
                    }.get(key),
                ),
                self.assertRaises(RuntimeError) as exc,
            ):
                tweet_module.submit_tweet(text="hello 401")

            refresh.assert_not_called()
            save_token.assert_not_called()
            self.assertIn("auth login", str(exc.exception))

    def test_missing_tweet_write_scope_produces_helpful_message(self) -> None:
        from birdapp import tweet as tweet_module

        response_403 = mock.Mock()
        response_403.ok = False
        response_403.status_code = 403
        response_403.reason = "Forbidden"
        response_403.json.return_value = {
            "title": "Forbidden",
            "detail": "Insufficient scope for this resource",
        }

        success, message = tweet_module.handle_tweet_response(response_403)
        self.assertFalse(success)
        self.assertIn("tweet.write", message)
        self.assertIn("auth config --oauth2", message)
        self.assertIn("auth login", message)
