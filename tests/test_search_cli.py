from __future__ import annotations

import json
import sys
import unittest
from datetime import UTC, datetime
from unittest import mock

from birdapp import main as main_module
from birdapp.storage.embeddings import EmbeddingsUnavailable, SemanticSearchResult
from birdapp.storage.search import SearchOwner, SearchResult


class TestSearchCli(unittest.TestCase):
    def test_search_cli_emits_json_results(self) -> None:
        sample_results = [
            SearchResult(
                tweet_id="111",
                created_at=datetime(2023, 5, 1, tzinfo=UTC),
                full_text="hello",
                tweet_kind="tweet",
                owner=SearchOwner(
                    account_id="42",
                    username="alice",
                    account_display_name="Alice",
                ),
                rank=0.1,
            )
        ]
        with (
            mock.patch.object(
                sys,
                "argv",
                ["birdapp", "search", "hello", "--db", "sqlite:///:memory:", "--json"],
            ),
            mock.patch("birdapp.main.search_tweets_in_db", return_value=sample_results),
            mock.patch("builtins.print") as print_mock,
        ):
            main_module.main()

        printed = " ".join(" ".join(map(str, args)) for args, _ in print_mock.call_args_list)
        payload = json.loads(printed)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["tweet_id"], "111")
        self.assertEqual(payload["results"][0]["owner"]["username"], "alice")

    def test_search_cli_semantic_handles_missing_embeddings(self) -> None:
        with (
            mock.patch.object(
                sys,
                "argv",
                ["birdapp", "search", "hello", "--semantic"],
            ),
            mock.patch(
                "birdapp.main.semantic_search_tweets_in_db",
                side_effect=EmbeddingsUnavailable(
                    'No embeddings found. Run "birdapp embed" first.'
                ),
            ),
            mock.patch("builtins.print") as print_mock,
        ):
            main_module.main()

        printed = " ".join(" ".join(map(str, args)) for args, _ in print_mock.call_args_list)
        self.assertIn('No embeddings found. Run "birdapp embed" first.', printed)

    def test_search_cli_emits_urls_with_flag(self) -> None:
        sample_results = [
            SearchResult(
                tweet_id="123",
                created_at=datetime(2023, 5, 1, tzinfo=UTC),
                full_text="hello",
                tweet_kind="tweet",
                owner=SearchOwner(
                    account_id="42",
                    username="alice",
                    account_display_name="Alice",
                ),
                rank=0.1,
            )
        ]
        with (
            mock.patch.object(
                sys,
                "argv",
                [
                    "birdapp",
                    "search",
                    "hello",
                    "--db",
                    "sqlite:///:memory:",
                    "--include-url",
                ],
            ),
            mock.patch("birdapp.main.search_tweets_in_db", return_value=sample_results),
            mock.patch("builtins.print") as print_mock,
        ):
            main_module.main()

        printed = " ".join(" ".join(map(str, args)) for args, _ in print_mock.call_args_list)
        self.assertIn("URL: https://x.com/alice/status/123", printed)

    def test_search_cli_semantic_emits_urls_with_flag(self) -> None:
        sample_results = [
            SemanticSearchResult(
                tweet_id="999",
                created_at=datetime(2023, 5, 1, tzinfo=UTC),
                full_text="semantic",
                tweet_kind="tweet",
                owner_account_id="99",
                owner_username="bob",
                owner_display_name="Bob",
            )
        ]
        with (
            mock.patch.object(
                sys,
                "argv",
                [
                    "birdapp",
                    "search",
                    "hello",
                    "--db",
                    "sqlite:///:memory:",
                    "--semantic",
                    "--include-url",
                ],
            ),
            mock.patch(
                "birdapp.main.semantic_search_tweets_in_db", return_value=sample_results
            ),
            mock.patch("builtins.print") as print_mock,
        ):
            main_module.main()

        printed = " ".join(" ".join(map(str, args)) for args, _ in print_mock.call_args_list)
        self.assertIn("URL: https://x.com/bob/status/999", printed)
