from __future__ import annotations

import unittest
from datetime import UTC, date, datetime

from sqlmodel import Session

from birdapp.storage.db import get_engine, init_db
from birdapp.storage.importer import import_archive_data
from birdapp.storage.search import SearchOwner, SearchResult, search_tweets


def _make_archive(owner_id: str, username: str, tweets: list[dict[str, str]]) -> dict[str, object]:
    tweet_items = []
    for tweet in tweets:
        tweet_items.append(
            {
                "tweet": {
                    "id": tweet["id"],
                    "id_str": tweet["id"],
                    "created_at": tweet["created_at"],
                    "display_text_range": ["0", str(len(tweet["full_text"]))],
                    "entities": {"hashtags": [], "symbols": [], "user_mentions": [], "urls": []},
                    "favorite_count": "0",
                    "truncated": False,
                    "retweet_count": "0",
                    "favorited": False,
                    "full_text": tweet["full_text"],
                    "lang": "en",
                    "source": "web",
                    "retweeted": False,
                }
            }
        )
    return {
        "upload-options": {
            "keepPrivate": False,
            "uploadLikes": True,
            "startDate": "2023-01-01T00:00:00.000Z",
            "endDate": "2024-01-01T00:00:00.000Z",
        },
        "account": [
            {
                "account": {
                    "createdVia": "oauth:123",
                    "username": username,
                    "accountId": owner_id,
                    "createdAt": "2023-01-01T00:00:00.000Z",
                    "accountDisplayName": username.title(),
                }
            }
        ],
        "profile": [],
        "tweets": tweet_items,
        "community-tweet": [],
        "note-tweet": [],
        "like": [],
        "follower": [],
        "following": [],
    }


class TestStorageSearch(unittest.TestCase):
    def test_search_returns_created_at_datetime_when_present(self) -> None:
        engine = get_engine("sqlite:///:memory:")
        init_db(engine)
        with Session(engine) as session:
            import_archive_data(
                _make_archive(
                    "42",
                    "alice",
                    [
                        {
                            "id": "111",
                            "full_text": "hello world",
                            # Matches Twitter "Download your data" ZIP export format.
                            "created_at": "Thu Jan 22 21:04:29 +0000 2026",
                        }
                    ],
                ),
                session,
            )

            results = search_tweets(session, query="hello")

        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0].created_at)
        self.assertEqual(
            results[0].created_at,
            datetime(2026, 1, 22, 21, 4, 29, tzinfo=UTC),
        )

    def test_search_returns_empty_for_blank_query(self) -> None:
        engine = get_engine("sqlite:///:memory:")
        init_db(engine)
        with Session(engine) as session:
            import_archive_data(
                _make_archive(
                    "42",
                    "alice",
                    [
                        {
                            "id": "111",
                            "full_text": "hello world",
                            "created_at": "2023-05-01T00:00:00.000Z",
                        }
                    ],
                ),
                session,
            )

            self.assertEqual(search_tweets(session, query=""), [])
            self.assertEqual(search_tweets(session, query="   "), [])

    def test_search_returns_matches_by_keyword(self) -> None:
        engine = get_engine("sqlite:///:memory:")
        init_db(engine)
        with Session(engine) as session:
            archive = _make_archive(
                "42",
                "alice",
                [
                    {
                        "id": "111",
                        "full_text": "hello world",
                        "created_at": "2023-05-01T00:00:00.000Z",
                    }
                ],
            )
            import_archive_data(archive, session)

            results = search_tweets(session, query="hello")

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], SearchResult)
        self.assertEqual(results[0].tweet_id, "111")
        self.assertIsInstance(results[0].owner, SearchOwner)
        self.assertEqual(results[0].owner.username, "alice")

    def test_search_filters_by_author_and_date(self) -> None:
        engine = get_engine("sqlite:///:memory:")
        init_db(engine)
        with Session(engine) as session:
            import_archive_data(
                _make_archive(
                    "42",
                    "alice",
                    [
                        {
                            "id": "111",
                            "full_text": "hello python",
                            "created_at": "2023-05-01T00:00:00.000Z",
                        }
                    ],
                ),
                session,
            )
            import_archive_data(
                _make_archive(
                    "99",
                    "bob",
                    [
                        {
                            "id": "222",
                            "full_text": "hello python",
                            "created_at": "2023-06-01T00:00:00.000Z",
                        }
                    ],
                ),
                session,
            )

            by_author = search_tweets(session, query="hello", author="@alice")
            since_date = search_tweets(session, query="hello", since=date(2023, 5, 15))
            until_date = search_tweets(session, query="hello", until=date(2023, 5, 15))

        self.assertEqual([result.owner.username for result in by_author], ["alice"])
        self.assertEqual([result.owner.username for result in since_date], ["bob"])
        self.assertEqual([result.owner.username for result in until_date], ["alice"])

    def test_search_excludes_missing_timestamps_from_date_filter(self) -> None:
        engine = get_engine("sqlite:///:memory:")
        init_db(engine)
        with Session(engine) as session:
            archive = _make_archive(
                "42",
                "alice",
                [
                    {
                        "id": "111",
                        "full_text": "hello world",
                        "created_at": "invalid",
                    }
                ],
            )
            import_archive_data(archive, session)

            results = search_tweets(
                session,
                query="hello",
                since=date(2023, 1, 1),
            )

        self.assertEqual(results, [])

    def test_search_returns_empty_for_unknown_author(self) -> None:
        engine = get_engine("sqlite:///:memory:")
        init_db(engine)
        with Session(engine) as session:
            import_archive_data(
                _make_archive(
                    "42",
                    "alice",
                    [
                        {
                            "id": "111",
                            "full_text": "hello world",
                            "created_at": "2023-05-01T00:00:00.000Z",
                        }
                    ],
                ),
                session,
            )

            results = search_tweets(session, query="hello", author="@doesnotexist")

        self.assertEqual(results, [])

    def test_search_supports_quoted_phrase_queries(self) -> None:
        engine = get_engine("sqlite:///:memory:")
        init_db(engine)
        with Session(engine) as session:
            import_archive_data(
                _make_archive(
                    "42",
                    "alice",
                    [
                        {
                            "id": "111",
                            "full_text": "machine learning is fun",
                            "created_at": "2023-05-01T00:00:00.000Z",
                        },
                        {
                            "id": "222",
                            "full_text": "machine deep learning is different",
                            "created_at": "2023-05-02T00:00:00.000Z",
                        },
                    ],
                ),
                session,
            )

            results = search_tweets(session, query='"machine learning"')

        self.assertEqual([result.tweet_id for result in results], ["111"])

    def test_search_matches_tokens_across_punctuation_in_text(self) -> None:
        engine = get_engine("sqlite:///:memory:")
        init_db(engine)
        with Session(engine) as session:
            import_archive_data(
                _make_archive(
                    "42",
                    "alice",
                    [
                        {
                            "id": "111",
                            "full_text": "Hello, world!",
                            "created_at": "2023-05-01T00:00:00.000Z",
                        }
                    ],
                ),
                session,
            )

            results = search_tweets(session, query="world")

        self.assertEqual([result.tweet_id for result in results], ["111"])
