import json
import tempfile
import unittest
import zipfile
from datetime import UTC
from pathlib import Path

from sqlmodel import Session, select

from birdapp.storage.db import get_engine, init_db
from birdapp.storage.importer import (
    import_archive,
    import_archive_data,
    load_twitter_zip,
)
from birdapp.storage.models import Account, Tweet


def _wrap_ytd(global_name: str, payload: object) -> str:
    return f"window.{global_name} = {json.dumps(payload)}\n"


def _wrap_thar_config(payload: object) -> str:
    return f"window.__THAR_CONFIG = {json.dumps(payload)}\n"


class TestTwitterZipImporter(unittest.TestCase):
    def test_load_twitter_zip_normalizes_datasets(self) -> None:
        tweets_payload = [
            {
                "tweet": {
                    "id_str": "111",
                    "id": "111",
                    "created_at": "Thu Jan 22 21:04:29 +0000 2026",
                    "full_text": "hello",
                    "lang": "en",
                    "source": "web",
                    "retweeted": False,
                    "favorited": False,
                    "truncated": False,
                    "favorite_count": "0",
                    "retweet_count": "0",
                    "entities": {
                        "hashtags": [],
                        "symbols": [],
                        "user_mentions": [],
                        "urls": [],
                    },
                    "display_text_range": ["0", "5"],
                }
            }
        ]
        account_payload = [
            {
                "account": {
                    "createdVia": "oauth:1",
                    "username": "example",
                    "accountId": "42",
                    "createdAt": "2016-03-08T05:42:24.075Z",
                    "accountDisplayName": "Example",
                }
            }
        ]
        profile_payload = [
            {
                "profile": {
                    "description": {"bio": "bio", "website": "https://t.co/x", "location": "NY"},
                    "avatarMediaUrl": "https://example.com/a.jpg",
                    "headerMediaUrl": "https://example.com/h.jpg",
                }
            }
        ]
        manifest_payload = {
            "dataTypes": {
                "account": {"files": [{"fileName": "data/account.js"}]},
                "profile": {"files": [{"fileName": "data/profile.js"}]},
                "tweets": {"files": [{"fileName": "data/tweets.js"}]},
            }
        }

        with tempfile.NamedTemporaryFile(suffix=".zip") as handle:
            zip_path = Path(handle.name)
            with zipfile.ZipFile(zip_path, mode="w") as archive:
                archive.writestr("data/manifest.js", _wrap_thar_config(manifest_payload))
                archive.writestr("data/account.js", _wrap_ytd("YTD.account.part0", account_payload))
                archive.writestr("data/profile.js", _wrap_ytd("YTD.profile.part0", profile_payload))
                archive.writestr("data/tweets.js", _wrap_ytd("YTD.tweets.part0", tweets_payload))

            normalized = load_twitter_zip(zip_path)

        self.assertIn("account", normalized)
        self.assertIn("profile", normalized)
        self.assertIn("tweets", normalized)
        self.assertEqual(normalized["account"][0]["account"]["accountId"], "42")
        self.assertEqual(normalized["tweets"][0]["tweet"]["id_str"], "111")

        engine = get_engine("sqlite:///:memory:")
        init_db(engine)
        with Session(engine) as session:
            import_archive_data(normalized, session, batch_size=1000)
            account = session.get(Account, "42")
            self.assertIsNotNone(account)
            tweet = session.get(Tweet, "111")
            self.assertIsNotNone(tweet)
            assert tweet is not None
            self.assertEqual(tweet.account_id, "42")
            self.assertIsNotNone(tweet.created_at)
            assert tweet.created_at is not None
            self.assertEqual(tweet.created_at.tzinfo, UTC)
            self.assertEqual(tweet.created_at.year, 2026)

    def test_load_twitter_zip_merges_multipart_files(self) -> None:
        tweets_part0 = [{"tweet": {"id_str": "1", "id": "1", "created_at": None, "full_text": "a"}}]
        tweets_part1 = [{"tweet": {"id_str": "2", "id": "2", "created_at": None, "full_text": "b"}}]
        account_payload = [
            {
                "account": {
                    "createdVia": "oauth:1",
                    "username": "example",
                    "accountId": "42",
                    "createdAt": "2016-03-08T05:42:24.075Z",
                    "accountDisplayName": "Example",
                }
            }
        ]
        manifest_payload = {
            "dataTypes": {
                "account": {"files": [{"fileName": "data/account.js"}]},
                "tweets": {
                    "files": [
                        {"fileName": "data/tweets-part0.js"},
                        {"fileName": "data/tweets-part1.js"},
                    ]
                },
            }
        }

        with tempfile.NamedTemporaryFile(suffix=".zip") as handle:
            zip_path = Path(handle.name)
            with zipfile.ZipFile(zip_path, mode="w") as archive:
                archive.writestr("data/manifest.js", _wrap_thar_config(manifest_payload))
                archive.writestr("data/account.js", _wrap_ytd("YTD.account.part0", account_payload))
                archive.writestr("data/tweets-part0.js", _wrap_ytd("YTD.tweets.part0", tweets_part0))
                archive.writestr("data/tweets-part1.js", _wrap_ytd("YTD.tweets.part1", tweets_part1))

            normalized = load_twitter_zip(zip_path)

        self.assertEqual(len(normalized["tweets"]), 2)
        ids = {item["tweet"]["id_str"] for item in normalized["tweets"]}
        self.assertEqual(ids, {"1", "2"})

    def test_import_archive_twitter_zip_is_idempotent(self) -> None:
        tweets_payload = [
            {
                "tweet": {
                    "id_str": "111",
                    "id": "111",
                    "created_at": "Thu Jan 22 21:04:29 +0000 2026",
                    "full_text": "hello",
                    "lang": "en",
                    "source": "web",
                    "retweeted": False,
                    "favorited": False,
                    "truncated": False,
                    "favorite_count": "0",
                    "retweet_count": "0",
                    "entities": {
                        "hashtags": [],
                        "symbols": [],
                        "user_mentions": [],
                        "urls": [],
                    },
                    "display_text_range": ["0", "5"],
                }
            }
        ]
        account_payload = [
            {
                "account": {
                    "createdVia": "oauth:1",
                    "username": "example",
                    "accountId": "42",
                    "createdAt": "2016-03-08T05:42:24.075Z",
                    "accountDisplayName": "Example",
                }
            }
        ]
        profile_payload = [
            {
                "profile": {
                    "description": {"bio": "bio", "website": "https://t.co/x", "location": "NY"},
                    "avatarMediaUrl": "https://example.com/a.jpg",
                    "headerMediaUrl": "https://example.com/h.jpg",
                }
            }
        ]
        manifest_payload = {
            "dataTypes": {
                "account": {"files": [{"fileName": "data/account.js"}]},
                "profile": {"files": [{"fileName": "data/profile.js"}]},
                "tweets": {"files": [{"fileName": "data/tweets.js"}]},
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            zip_path = tmp_path / "twitter.zip"
            db_path = tmp_path / "birdapp.db"
            db_url = f"sqlite:///{db_path}"
            with zipfile.ZipFile(zip_path, mode="w") as archive:
                archive.writestr("data/manifest.js", _wrap_thar_config(manifest_payload))
                archive.writestr("data/account.js", _wrap_ytd("YTD.account.part0", account_payload))
                archive.writestr("data/profile.js", _wrap_ytd("YTD.profile.part0", profile_payload))
                archive.writestr("data/tweets.js", _wrap_ytd("YTD.tweets.part0", tweets_payload))

            first = import_archive(db_url, path=zip_path)
            second = import_archive(db_url, path=zip_path)

            self.assertGreater(first["account"], 0)
            self.assertGreater(first["profile"], 0)
            self.assertGreater(first["tweet"], 0)
            self.assertTrue(all(value == 0 for value in second.values()))

            engine = get_engine(db_url)
            init_db(engine)
            with Session(engine) as session:
                accounts = session.exec(select(Account)).all()
                tweets = session.exec(select(Tweet)).all()
                self.assertEqual(len(accounts), 1)
                self.assertEqual(len(tweets), 1)

