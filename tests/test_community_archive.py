import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from sqlmodel import Session, select

from birdapp.storage.community_archive import (
    COMMUNITY_ARCHIVE_ANON_KEY,
    CommunityArchiveError,
    archive_from_community_rows,
    fetch_community_archive,
)
from birdapp.storage.db import get_engine, init_db
from birdapp.storage.importer import import_archive
from birdapp.storage.models import (
    Account,
    Follower,
    Following,
    Like,
    Profile,
    Tweet,
    TweetMedia,
    TweetUrl,
    TweetUserMention,
)


def _account_row() -> dict[str, Any]:
    return {
        "account_id": "42",
        "username": "ExampleUser",
        "account_display_name": "Example",
        "created_at": "2016-03-08T05:42:24.075Z",
        "created_via": "oauth:1",
    }


def _profile_row() -> dict[str, Any]:
    return {
        "bio": "bio",
        "website": "https://example.com",
        "location": "Nowhere",
        "avatar_media_url": "https://example.com/avatar.png",
        "header_media_url": "https://example.com/header.png",
    }


def _tweet_row(tweet_id: str, *, retweet: bool = False) -> dict[str, Any]:
    return {
        "tweet_id": tweet_id,
        "created_at": "2019-10-10T14:38:00+00:00",
        "full_text": f"hello {tweet_id}",
        "favorite_count": 16,
        "retweet_count": 9,
        "reply_to_tweet_id": "99",
        "reply_to_user_id": "7",
        "reply_to_username": "someone",
        "tweet_urls": [
            {
                "url": "https://t.co/abc",
                "expanded_url": "https://example.com/post",
                "display_url": "example.com/post",
            }
        ],
        "tweet_media": [
            {
                "media_id": 1182304276128755713,
                "media_type": "photo",
                "media_url": "https://pbs.twimg.com/media/example.jpg",
                "width": 640,
                "height": 427,
            }
        ],
        "user_mentions": [
            {
                "mentioned_user_id": "1194730652379144192",
                "mentioned_users": {
                    "name": "Dreams from My Brain",
                    "screen_name": "brain_dreams",
                },
            }
        ],
        "retweets": {"retweeted_tweet_id": "55"} if retweet else None,
    }


class _Response:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload
        self.ok = status_code < 400
        self.reason = "Bad Request" if status_code >= 400 else "OK"
        self.text = str(payload)

    def json(self) -> Any:
        if isinstance(self._payload, ValueError):
            raise self._payload
        return self._payload


class _Session:
    def __init__(self, handler: Any) -> None:
        self.handler = handler
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> _Response:
        self.calls.append(
            {
                "url": url,
                "params": dict(params or {}),
                "headers": dict(headers or {}),
                "timeout": timeout,
            }
        )
        return self.handler(url, dict(params or {}))

    def close(self) -> None:
        self.closed = True


class TestArchiveFromCommunityRows(unittest.TestCase):
    def test_maps_account_profile_tweet_like_and_graph(self) -> None:
        archive = archive_from_community_rows(
            account=_account_row(),
            profile=_profile_row(),
            tweets=[_tweet_row("111", retweet=True)],
            likes=[
                {
                    "id": 1,
                    "liked_tweet_id": "222",
                    "liked_tweets": {"full_text": "liked text"},
                }
            ],
            followers=[{"id": 2, "follower_account_id": "333"}],
            following=[{"id": 3, "following_account_id": "444"}],
        )

        self.assertEqual(archive["account"][0]["account"]["accountId"], "42")
        self.assertEqual(archive["account"][0]["account"]["username"], "ExampleUser")
        self.assertEqual(archive["account"][0]["account"]["createdVia"], "oauth:1")
        profile = archive["profile"][0]["profile"]
        self.assertEqual(profile["description"]["bio"], "bio")
        self.assertEqual(profile["avatarMediaUrl"], "https://example.com/avatar.png")

        tweet = archive["tweets"][0]["tweet"]
        self.assertEqual(tweet["id_str"], "111")
        self.assertTrue(tweet["retweeted"])
        self.assertEqual(tweet["in_reply_to_status_id_str"], "99")
        self.assertEqual(tweet["in_reply_to_screen_name"], "someone")
        self.assertEqual(tweet["entities"]["urls"][0]["expanded_url"], "https://example.com/post")
        self.assertEqual(tweet["entities"]["media"][0]["id_str"], "1182304276128755713")
        self.assertEqual(tweet["entities"]["media"][0]["sizes"], {"width": 640, "height": 427})
        mention = tweet["entities"]["user_mentions"][0]
        self.assertEqual(mention["screen_name"], "brain_dreams")
        self.assertEqual(mention["id_str"], "1194730652379144192")

        self.assertEqual(archive["like"][0]["like"]["tweetId"], "222")
        self.assertEqual(archive["like"][0]["like"]["fullText"], "liked text")
        self.assertEqual(archive["follower"][0]["follower"]["accountId"], "333")
        self.assertEqual(archive["following"][0]["following"]["accountId"], "444")

    def test_omits_profile_and_keeps_null_like_text(self) -> None:
        archive = archive_from_community_rows(
            account=_account_row(),
            profile=None,
            tweets=[_tweet_row("111")],
            likes=[{"id": 1, "liked_tweet_id": "222", "liked_tweets": None}],
            followers=[],
            following=[],
        )

        self.assertNotIn("profile", archive)
        self.assertFalse(archive["tweets"][0]["tweet"]["retweeted"])
        self.assertIsNone(archive["like"][0]["like"]["fullText"])
        mention = {
            "mentioned_user_id": "5",
            "mentioned_users": None,
        }
        tweet = archive_from_community_rows(
            account=_account_row(),
            profile=None,
            tweets=[{**_tweet_row("111"), "user_mentions": [mention]}],
            likes=[],
            followers=[],
            following=[],
        )["tweets"][0]["tweet"]
        self.assertEqual(tweet["entities"]["user_mentions"][0]["name"], "")
        self.assertEqual(tweet["entities"]["user_mentions"][0]["screen_name"], "")


class TestFetchCommunityArchive(unittest.TestCase):
    def test_pages_until_short_page_and_sends_anon_key(self) -> None:
        pages = {
            "enriched_tweets": [
                [_tweet_row("1"), _tweet_row("2")],
                [_tweet_row("3")],
            ],
            "likes": [[{"id": 10, "liked_tweet_id": "200", "liked_tweets": None}]],
            "followers": [[]],
            "following": [[]],
        }
        seen: dict[str, int] = {}

        def handler(url: str, params: dict[str, Any]) -> _Response:
            table = url.rstrip("/").rsplit("/", 1)[-1]
            if table == "all_account":
                self.assertEqual(params["username"], "ilike.exampleuser")
                return _Response(200, [_account_row()])
            if table == "all_profile":
                self.assertEqual(params["account_id"], "eq.42")
                return _Response(200, [_profile_row()])
            batch_index = seen.get(table, 0)
            seen[table] = batch_index + 1
            return _Response(200, pages[table][batch_index])

        session = _Session(handler)
        archive = fetch_community_archive(
            "@exampleuser",
            session=session,  # type: ignore[arg-type]
            page_size=2,
        )

        self.assertEqual(
            [item["tweet"]["id_str"] for item in archive["tweets"]],
            ["1", "2", "3"],
        )
        self.assertEqual(len(archive["like"]), 1)
        tweet_calls = [
            call for call in session.calls if call["url"].endswith("/enriched_tweets")
        ]
        self.assertEqual(len(tweet_calls), 2)
        self.assertNotIn("tweet_id", tweet_calls[0]["params"])
        self.assertEqual(tweet_calls[1]["params"]["tweet_id"], "gt.2")
        self.assertEqual(tweet_calls[0]["params"]["order"], "tweet_id.asc")
        self.assertEqual(tweet_calls[0]["params"]["limit"], "2")
        self.assertEqual(tweet_calls[0]["params"]["account_id"], "eq.42")
        self.assertIn("user_mentions", tweet_calls[0]["params"]["select"])
        self.assertIn("tweet_media", tweet_calls[0]["params"]["select"])
        like_call = next(call for call in session.calls if call["url"].endswith("/likes"))
        self.assertEqual(like_call["params"]["order"], "id.asc")
        self.assertEqual(like_call["params"]["account_id"], "eq.42")
        self.assertIn("liked_tweets", like_call["params"]["select"])
        for call in session.calls:
            self.assertEqual(call["headers"]["apikey"], COMMUNITY_ARCHIVE_ANON_KEY)
            self.assertEqual(
                call["headers"]["Authorization"],
                f"Bearer {COMMUNITY_ARCHIVE_ANON_KEY}",
            )
            self.assertEqual(call["timeout"], 60)
        self.assertFalse(session.closed)

    def test_rejects_page_size_above_postgrest_cap(self) -> None:
        with self.assertRaises(ValueError):
            fetch_community_archive("example", page_size=1001)

    def test_rejects_username_that_cannot_be_a_filter_value(self) -> None:
        with self.assertRaises(ValueError):
            fetch_community_archive("not a username")

    def test_raises_when_username_is_missing(self) -> None:
        session = _Session(lambda _url, _params: _Response(200, []))
        with self.assertRaises(CommunityArchiveError) as caught:
            fetch_community_archive("missing", session=session)  # type: ignore[arg-type]
        self.assertIn("missing", str(caught.exception))

    def test_raises_when_username_matches_multiple_accounts(self) -> None:
        rows = [_account_row(), {**_account_row(), "account_id": "43"}]

        def handler(url: str, _params: dict[str, Any]) -> _Response:
            if url.endswith("/all_account"):
                return _Response(200, rows)
            raise AssertionError(url)

        with self.assertRaises(CommunityArchiveError):
            fetch_community_archive("example", session=_Session(handler))  # type: ignore[arg-type]

    def test_raises_when_a_full_page_does_not_advance(self) -> None:
        def handler(url: str, _params: dict[str, Any]) -> _Response:
            if url.endswith("/all_account"):
                return _Response(200, [_account_row()])
            if url.endswith("/all_profile"):
                return _Response(200, [])
            if url.endswith("/enriched_tweets"):
                return _Response(200, [_tweet_row("1"), _tweet_row("1")])
            raise AssertionError(url)

        with self.assertRaises(CommunityArchiveError):
            fetch_community_archive(
                "example",
                session=_Session(handler),  # type: ignore[arg-type]
                page_size=2,
            )

    def test_includes_postgrest_error_message(self) -> None:
        def handler(url: str, _params: dict[str, Any]) -> _Response:
            if url.endswith("/all_account"):
                return _Response(400, {"message": "permission denied"})
            raise AssertionError(url)

        with self.assertRaises(CommunityArchiveError) as caught:
            fetch_community_archive("example", session=_Session(handler))  # type: ignore[arg-type]
        self.assertIn("permission denied", str(caught.exception))
        self.assertIn("400", str(caught.exception))


class TestImportArchiveFromCommunityArchive(unittest.TestCase):
    def test_username_import_persists_postgrest_rows(self) -> None:
        archive = archive_from_community_rows(
            account=_account_row(),
            profile=_profile_row(),
            tweets=[_tweet_row("111", retweet=True)],
            likes=[
                {
                    "id": 1,
                    "liked_tweet_id": "222",
                    "liked_tweets": {"full_text": "liked text"},
                }
            ],
            followers=[{"id": 2, "follower_account_id": "333"}],
            following=[{"id": 3, "following_account_id": "444"}],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            db_url = f"sqlite:///{Path(tmpdir) / 'birdapp.db'}"
            with mock.patch(
                "birdapp.storage.importer.fetch_community_archive",
                return_value=archive,
            ) as fetch_mock:
                counts = import_archive(db_url, username="example")

            fetch_mock.assert_called_once_with("example")
            self.assertEqual(counts["tweet"], 1)
            self.assertEqual(counts["like"], 1)
            self.assertEqual(counts["follower"], 1)
            self.assertEqual(counts["following"], 1)

            engine = get_engine(db_url)
            init_db(engine)
            with Session(engine) as session:
                account = session.get(Account, "42")
                profile = session.get(Profile, "42")
                tweet = session.get(Tweet, "111")
                url = session.exec(select(TweetUrl)).one()
                media = session.exec(select(TweetMedia)).one()
                mention = session.exec(select(TweetUserMention)).one()
                like = session.exec(select(Like)).one()
                follower = session.exec(select(Follower)).one()
                following = session.exec(select(Following)).one()

            assert account is not None
            assert profile is not None
            assert tweet is not None
            self.assertEqual(account.username, "ExampleUser")
            self.assertEqual(profile.bio, "bio")
            self.assertEqual(tweet.full_text, "hello 111")
            self.assertTrue(tweet.retweeted)
            self.assertEqual(tweet.in_reply_to_screen_name, "someone")
            self.assertEqual(url.expanded_url, "https://example.com/post")
            self.assertEqual(media.media_id_str, "1182304276128755713")
            self.assertEqual(media.sizes, {"width": 640, "height": 427})
            self.assertEqual(mention.screen_name, "brain_dreams")
            self.assertEqual(like.full_text, "liked text")
            self.assertEqual(follower.follower_account_id, "333")
            self.assertEqual(follower.user_link, "")
            self.assertEqual(following.followed_account_id, "444")
