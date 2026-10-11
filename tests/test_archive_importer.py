import unittest
from copy import deepcopy
from typing import Any, cast

from sqlalchemy import text
from sqlmodel import Session, select

from birdapp.storage.db import get_engine, init_db
from birdapp.storage.importer import import_archive_data
from birdapp.storage.models import (
    Follower,
    Following,
    Like,
    NoteTweet,
    Tweet,
    TweetHashtag,
    TweetMedia,
    UploadOptions,
)


class TestArchiveImporter(unittest.TestCase):
    def test_import_archive_data_inserts_and_parses(self) -> None:
        data = {
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
                        "username": "example",
                        "accountId": "42",
                        "createdAt": "2023-01-01T00:00:00.000Z",
                        "accountDisplayName": "Example",
                    }
                }
            ],
            "profile": [
                {
                    "profile": {
                        "description": {
                            "bio": "bio",
                            "website": "https://example.com",
                            "location": "Nowhere",
                        },
                        "avatarMediaUrl": "https://example.com/avatar.png",
                        "headerMediaUrl": "https://example.com/header.png",
                    }
                }
            ],
            "tweets": [
                {
                    "tweet": {
                        "created_at": "2023-05-01T00:00:00.000Z",
                        "display_text_range": ["0", "10"],
                        "edit_info": {
                            "initial": {
                                "editTweetIds": ["111"],
                                "editableUntil": "2023-05-02T00:00:00.000Z",
                                "editsRemaining": "5",
                                "isEditEligible": False,
                            }
                        },
                        "entities": {
                            "hashtags": [{"text": "Tag", "indices": ["0", "4"]}],
                            "symbols": [],
                            "user_mentions": [],
                            "urls": [],
                            "media": [
                                {
                                    "expanded_url": "https://example.com/media",
                                    "indices": ["0", "5"],
                                    "url": "https://t.co/abc",
                                    "media_url": "https://example.com/media.jpg",
                                    "id_str": "999",
                                    "id": "999",
                                    "media_url_https": "https://example.com/media.jpg",
                                    "sizes": {"small": {"w": "1", "h": "2", "resize": "fit"}},
                                    "type": "photo",
                                    "display_url": "pic.twitter.com/abc",
                                }
                            ],
                        },
                        "favorite_count": "5",
                        "in_reply_to_status_id_str": None,
                        "id_str": "111",
                        "in_reply_to_user_id": None,
                        "truncated": False,
                        "retweet_count": "2",
                        "id": "111",
                        "in_reply_to_status_id": None,
                        "favorited": False,
                        "full_text": "hello",
                        "lang": "en",
                        "in_reply_to_screen_name": None,
                        "in_reply_to_user_id_str": None,
                        "source": "web",
                        "retweeted": False,
                        "extended_entities": {
                            "media": [
                                {
                                    "expanded_url": "https://example.com/video",
                                    "indices": ["0", "5"],
                                    "url": "https://t.co/vid",
                                    "media_url": "https://example.com/video.jpg",
                                    "id_str": "1000",
                                    "id": "1000",
                                    "media_url_https": "https://example.com/video.jpg",
                                    "sizes": {"small": {"w": "1", "h": "2", "resize": "fit"}},
                                    "type": "video",
                                    "display_url": "pic.twitter.com/vid",
                                    "video_info": {
                                        "aspect_ratio": ["16", "9"],
                                        "variants": [
                                            {
                                                "bitrate": "128000",
                                                "content_type": "video/mp4",
                                                "url": "https://example.com/video.mp4",
                                            }
                                        ],
                                    },
                                    "additional_media_info": {"monetizable": False},
                                }
                            ]
                        },
                    }
                }
            ],
            "community-tweet": [
                {
                    "tweet": {
                        "created_at": "2023-06-01T00:00:00.000Z",
                        "display_text_range": ["0", "8"],
                        "entities": {"hashtags": [], "symbols": [], "user_mentions": [], "urls": []},
                        "favorite_count": "1",
                        "id_str": "222",
                        "truncated": False,
                        "retweet_count": "0",
                        "id": "222",
                        "favorited": False,
                        "full_text": "community",
                        "lang": "en",
                        "source": "web",
                        "retweeted": False,
                        "community_id": "99",
                        "community_id_str": "99",
                        "scopes": {"followers": True},
                    }
                }
            ],
            "note-tweet": [
                {
                    "noteTweet": {
                        "noteTweetId": "nt1",
                        "updatedAt": "2023-01-01T00:00:00.000Z",
                        "createdAt": "2023-01-01T00:00:00.000Z",
                        "lifecycle": {
                            "value": "ok",
                            "name": "ok",
                            "originalName": "ok",
                            "annotations": {},
                        },
                        "core": {
                            "styletags": [],
                            "urls": [],
                            "text": "note",
                            "mentions": [],
                            "cashtags": [],
                            "hashtags": [],
                        },
                    }
                }
            ],
            "like": [
                {"like": {"tweetId": "333", "fullText": "liked", "expandedUrl": "https://x.com"}}
            ],
            "follower": [{"follower": {"accountId": "11", "userLink": "https://x.com/11"}}],
            "following": [{"following": {"accountId": "12", "userLink": "https://x.com/12"}}],
        }

        engine = get_engine("sqlite:///:memory:")
        init_db(engine)
        with Session(engine) as session:
            counts = import_archive_data(data, session)

            self.assertEqual(counts["tweet"], 1)
            self.assertEqual(counts["community_tweet"], 1)
            self.assertEqual(counts["note_tweet"], 1)
            self.assertEqual(counts["like"], 1)
            self.assertEqual(counts["tweet_media"], 2)

            tweet = session.get(Tweet, "111")
            self.assertIsNotNone(tweet)
            tweet = cast(Tweet, tweet)
            self.assertEqual(tweet.favorite_count, 5)
            self.assertEqual(tweet.retweet_count, 2)
            self.assertEqual(tweet.display_text_range, [0, 10])
            self.assertEqual(tweet.account_id, "42")

            hashtags = session.exec(select(TweetHashtag)).all()
            self.assertEqual(len(hashtags), 1)
            self.assertEqual(hashtags[0].start_index, 0)
            self.assertEqual(hashtags[0].end_index, 4)

            media_items = session.exec(select(TweetMedia)).all()
            self.assertEqual(len(media_items), 2)

            note = session.get(NoteTweet, "nt1")
            self.assertIsNotNone(note)

            likes = session.exec(select(Like)).all()
            self.assertEqual(len(likes), 1)
            self.assertEqual(likes[0].account_id, "42")

            upload_options = session.exec(select(UploadOptions)).all()
            self.assertEqual(len(upload_options), 1)
            self.assertEqual(upload_options[0].account_id, "42")

            followers = session.exec(select(Follower)).all()
            self.assertEqual(len(followers), 1)
            self.assertEqual(followers[0].account_id, "42")
            self.assertEqual(followers[0].follower_account_id, "11")

            followings = session.exec(select(Following)).all()
            self.assertEqual(len(followings), 1)
            self.assertEqual(followings[0].account_id, "42")
            self.assertEqual(followings[0].followed_account_id, "12")

    def test_import_archive_data_incremental_update(self) -> None:
        base_data = {
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
                        "username": "example",
                        "accountId": "42",
                        "createdAt": "2023-01-01T00:00:00.000Z",
                        "accountDisplayName": "Example",
                    }
                }
            ],
            "profile": [
                {
                    "profile": {
                        "description": {
                            "bio": "bio",
                            "website": "https://example.com",
                            "location": "Nowhere",
                        },
                        "avatarMediaUrl": "https://example.com/avatar.png",
                        "headerMediaUrl": "https://example.com/header.png",
                    }
                }
            ],
            "tweets": [
                {
                    "tweet": {
                        "created_at": "2023-05-01T00:00:00.000Z",
                        "display_text_range": ["0", "10"],
                        "edit_info": {
                            "initial": {
                                "editTweetIds": ["111"],
                                "editableUntil": "2023-05-02T00:00:00.000Z",
                                "editsRemaining": "5",
                                "isEditEligible": False,
                            }
                        },
                        "entities": {
                            "hashtags": [{"text": "Tag", "indices": ["0", "4"]}],
                            "symbols": [{"text": "SYM", "indices": ["0", "3"]}],
                            "user_mentions": [
                                {
                                    "name": "Example",
                                    "screen_name": "example",
                                    "indices": ["0", "7"],
                                    "id_str": "9",
                                    "id": "9",
                                }
                            ],
                            "urls": [
                                {
                                    "url": "https://t.co/abc",
                                    "expanded_url": "https://example.com",
                                    "display_url": "example.com",
                                    "indices": ["0", "10"],
                                }
                            ],
                            "media": [
                                {
                                    "expanded_url": "https://example.com/media",
                                    "indices": ["0", "5"],
                                    "url": "https://t.co/abc",
                                    "media_url": "https://example.com/media.jpg",
                                    "id_str": "999",
                                    "id": "999",
                                    "media_url_https": "https://example.com/media.jpg",
                                    "sizes": {"small": {"w": "1", "h": "2", "resize": "fit"}},
                                    "type": "photo",
                                    "display_url": "pic.twitter.com/abc",
                                }
                            ],
                        },
                        "favorite_count": "5",
                        "id_str": "111",
                        "truncated": False,
                        "retweet_count": "2",
                        "id": "111",
                        "favorited": False,
                        "full_text": "hello",
                        "lang": "en",
                        "source": "web",
                        "retweeted": False,
                    }
                }
            ],
            "community-tweet": [
                {
                    "tweet": {
                        "created_at": "2023-06-01T00:00:00.000Z",
                        "display_text_range": ["0", "8"],
                        "entities": {"hashtags": [], "symbols": [], "user_mentions": [], "urls": []},
                        "favorite_count": "1",
                        "id_str": "222",
                        "truncated": False,
                        "retweet_count": "0",
                        "id": "222",
                        "favorited": False,
                        "full_text": "community",
                        "lang": "en",
                        "source": "web",
                        "retweeted": False,
                        "community_id": "99",
                        "community_id_str": "99",
                        "scopes": {"followers": True},
                    }
                }
            ],
            "note-tweet": [
                {
                    "noteTweet": {
                        "noteTweetId": "nt1",
                        "updatedAt": "2023-01-01T00:00:00.000Z",
                        "createdAt": "2023-01-01T00:00:00.000Z",
                        "lifecycle": {
                            "value": "ok",
                            "name": "ok",
                            "originalName": "ok",
                            "annotations": {},
                        },
                        "core": {
                            "styletags": [],
                            "urls": [],
                            "text": "note",
                            "mentions": [],
                            "cashtags": [],
                            "hashtags": [],
                        },
                    }
                }
            ],
            "like": [
                {"like": {"tweetId": "333", "fullText": "liked", "expandedUrl": "https://x.com"}}
            ],
            "follower": [{"follower": {"accountId": "11", "userLink": "https://x.com/11"}}],
            "following": [{"following": {"accountId": "12", "userLink": "https://x.com/12"}}],
        }

        second_data = deepcopy(base_data)
        tweets = cast(list[dict[str, Any]], second_data["tweets"])
        community_tweets = cast(list[dict[str, Any]], second_data["community-tweet"])
        note_tweets = cast(list[dict[str, Any]], second_data["note-tweet"])
        likes = cast(list[dict[str, Any]], second_data["like"])
        followers = cast(list[dict[str, Any]], second_data["follower"])
        following = cast(list[dict[str, Any]], second_data["following"])

        tweets.append(
            {
                "tweet": {
                    "created_at": "2023-07-01T00:00:00.000Z",
                    "display_text_range": ["0", "5"],
                    "entities": {"hashtags": [], "symbols": [], "user_mentions": [], "urls": []},
                    "favorite_count": "0",
                    "id_str": "112",
                    "truncated": False,
                    "retweet_count": "0",
                    "id": "112",
                    "favorited": False,
                    "full_text": "new",
                    "lang": "en",
                    "source": "web",
                    "retweeted": False,
                }
            }
        )
        community_tweets.append(
            {
                "tweet": {
                    "created_at": "2023-07-02T00:00:00.000Z",
                    "display_text_range": ["0", "8"],
                    "entities": {"hashtags": [], "symbols": [], "user_mentions": [], "urls": []},
                    "favorite_count": "1",
                    "id_str": "223",
                    "truncated": False,
                    "retweet_count": "0",
                    "id": "223",
                    "favorited": False,
                    "full_text": "community2",
                    "lang": "en",
                    "source": "web",
                    "retweeted": False,
                    "community_id": "99",
                    "community_id_str": "99",
                    "scopes": {"followers": True},
                }
            }
        )
        note_tweets.append(
            {
                "noteTweet": {
                    "noteTweetId": "nt2",
                    "updatedAt": "2023-02-01T00:00:00.000Z",
                    "createdAt": "2023-02-01T00:00:00.000Z",
                    "lifecycle": {
                        "value": "ok",
                        "name": "ok",
                        "originalName": "ok",
                        "annotations": {},
                    },
                    "core": {
                        "styletags": [],
                        "urls": [],
                        "text": "note2",
                        "mentions": [],
                        "cashtags": [],
                        "hashtags": [],
                    },
                }
            }
        )
        likes.append(
            {"like": {"tweetId": "334", "fullText": "liked2", "expandedUrl": "https://x.com/2"}}
        )
        followers.append(
            {"follower": {"accountId": "11", "userLink": "https://x.com/13"}}
        )
        following.append(
            {"following": {"accountId": "12", "userLink": "https://x.com/14"}}
        )

        engine = get_engine("sqlite:///:memory:")
        init_db(engine)
        with Session(engine) as session:
            import_archive_data(base_data, session)
            import_archive_data(second_data, session)

            self.assertEqual(len(session.exec(select(Tweet)).all()), 4)
            self.assertEqual(len(session.exec(select(TweetHashtag)).all()), 1)
            self.assertEqual(len(session.exec(select(TweetMedia)).all()), 1)
            self.assertEqual(len(session.exec(select(NoteTweet)).all()), 2)
            self.assertEqual(len(session.exec(select(Like)).all()), 2)

    def test_import_archive_data_multi_user_like_dedupe(self) -> None:
        def make_archive(owner_id: str, username: str, tweet_id: str) -> dict[str, Any]:
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
                "tweets": [
                    {
                        "tweet": {
                            "created_at": "2023-05-01T00:00:00.000Z",
                            "display_text_range": ["0", "5"],
                            "entities": {"hashtags": [], "symbols": [], "user_mentions": [], "urls": []},
                            "favorite_count": "0",
                            "id_str": tweet_id,
                            "truncated": False,
                            "retweet_count": "0",
                            "id": tweet_id,
                            "favorited": False,
                            "full_text": f"tweet-{owner_id}",
                            "lang": "en",
                            "source": "web",
                            "retweeted": False,
                        }
                    }
                ],
                "community-tweet": [],
                "note-tweet": [],
                "like": [
                    {
                        "like": {
                            "tweetId": "333",
                            "fullText": "liked",
                            "expandedUrl": "https://x.com",
                        }
                    }
                ],
                "follower": [],
                "following": [],
            }

        engine = get_engine("sqlite:///:memory:")
        init_db(engine)
        with Session(engine) as session:
            import_archive_data(make_archive("42", "alpha", "111"), session)
            import_archive_data(make_archive("99", "beta", "222"), session)

            likes = session.exec(select(Like).order_by(Like.account_id)).all()
            self.assertEqual(len(likes), 2)
            self.assertEqual(likes[0].account_id, "42")
            self.assertEqual(likes[0].tweet_id, "333")
            self.assertEqual(likes[1].account_id, "99")
            self.assertEqual(likes[1].tweet_id, "333")

            upload_options = session.exec(select(UploadOptions).order_by(UploadOptions.account_id)).all()
            self.assertEqual(len(upload_options), 2)
            self.assertEqual(upload_options[0].account_id, "42")
            self.assertEqual(upload_options[1].account_id, "99")

    def test_import_archive_data_rejects_cross_owner_tweet_id_collision(self) -> None:
        def make_archive(owner_id: str, username: str, tweet_id: str) -> dict[str, Any]:
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
                "tweets": [
                    {
                        "tweet": {
                            "created_at": "2023-05-01T00:00:00.000Z",
                            "display_text_range": ["0", "5"],
                            "entities": {
                                "hashtags": [],
                                "symbols": [],
                                "user_mentions": [],
                                "urls": [],
                            },
                            "favorite_count": "0",
                            "id_str": tweet_id,
                            "truncated": False,
                            "retweet_count": "0",
                            "id": tweet_id,
                            "favorited": False,
                            "full_text": f"tweet-{owner_id}",
                            "lang": "en",
                            "source": "web",
                            "retweeted": False,
                        }
                    }
                ],
                "community-tweet": [],
                "note-tweet": [],
                "like": [],
                "follower": [],
                "following": [],
            }

        engine = get_engine("sqlite:///:memory:")
        init_db(engine)
        with Session(engine) as session:
            import_archive_data(make_archive("42", "alice", "111"), session)

            # Sanity-check FTS row is present for the imported tweet.
            row = session.exec(
                text(
                    "SELECT account_id, full_text FROM tweet_fts WHERE tweet_id = :tweet_id"
                ).bindparams(tweet_id="111")
            ).one()
            self.assertEqual(row[0], "42")
            self.assertEqual(row[1], "tweet-42")

            with self.assertRaises(ValueError):
                import_archive_data(make_archive("99", "bob", "111"), session)

            tweet = session.get(Tweet, "111")
            self.assertIsNotNone(tweet)
            tweet = cast(Tweet, tweet)
            self.assertEqual(tweet.account_id, "42")

            # Ensure we didn't clobber the FTS row during the rejected import.
            row_after = session.exec(
                text(
                    "SELECT account_id, full_text FROM tweet_fts WHERE tweet_id = :tweet_id"
                ).bindparams(tweet_id="111")
            ).one()
            self.assertEqual(row_after[0], "42")
            self.assertEqual(row_after[1], "tweet-42")

    def test_import_archive_data_creates_one_fts_row_per_tweet(self) -> None:
        data = {
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
                        "username": "example",
                        "accountId": "42",
                        "createdAt": "2023-01-01T00:00:00.000Z",
                        "accountDisplayName": "Example",
                    }
                }
            ],
            "profile": [],
            "tweets": [
                {
                    "tweet": {
                        "created_at": "2023-05-01T00:00:00.000Z",
                        "display_text_range": ["0", "5"],
                        "entities": {
                            "hashtags": [],
                            "symbols": [],
                            "user_mentions": [],
                            "urls": [],
                        },
                        "favorite_count": "0",
                        "id_str": "111",
                        "truncated": False,
                        "retweet_count": "0",
                        "id": "111",
                        "favorited": False,
                        "full_text": "hello",
                        "lang": "en",
                        "source": "web",
                        "retweeted": False,
                    }
                },
                {
                    "tweet": {
                        "created_at": "2023-05-02T00:00:00.000Z",
                        "display_text_range": ["0", "5"],
                        "entities": {
                            "hashtags": [],
                            "symbols": [],
                            "user_mentions": [],
                            "urls": [],
                        },
                        "favorite_count": "0",
                        "id_str": "112",
                        "truncated": False,
                        "retweet_count": "0",
                        "id": "112",
                        "favorited": False,
                        "full_text": "world",
                        "lang": "en",
                        "source": "web",
                        "retweeted": False,
                    }
                },
            ],
            "community-tweet": [
                {
                    "tweet": {
                        "created_at": "2023-06-01T00:00:00.000Z",
                        "display_text_range": ["0", "9"],
                        "entities": {"hashtags": [], "symbols": [], "user_mentions": [], "urls": []},
                        "favorite_count": "0",
                        "id_str": "221",
                        "truncated": False,
                        "retweet_count": "0",
                        "id": "221",
                        "favorited": False,
                        "full_text": "community",
                        "lang": "en",
                        "source": "web",
                        "retweeted": False,
                        "community_id": "99",
                        "community_id_str": "99",
                        "scopes": {"followers": True},
                    }
                }
            ],
            "note-tweet": [],
            "like": [],
            "follower": [],
            "following": [],
        }

        engine = get_engine("sqlite:///:memory:")
        init_db(engine)
        with Session(engine) as session:
            import_archive_data(data, session)

            rows = session.exec(
                text("SELECT tweet_id, account_id, full_text FROM tweet_fts ORDER BY tweet_id")
            ).all()

        self.assertEqual(len(rows), 3)
        self.assertEqual([row[0] for row in rows], ["111", "112", "221"])
        self.assertEqual([row[1] for row in rows], ["42", "42", "42"])
        self.assertEqual([row[2] for row in rows], ["hello", "world", "community"])

    def test_import_archive_data_reimport_updates_fts_without_duplicates(self) -> None:
        def make_archive(full_text: str) -> dict[str, Any]:
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
                            "username": "example",
                            "accountId": "42",
                            "createdAt": "2023-01-01T00:00:00.000Z",
                            "accountDisplayName": "Example",
                        }
                    }
                ],
                "profile": [],
                "tweets": [
                    {
                        "tweet": {
                            "created_at": "2023-05-01T00:00:00.000Z",
                            "display_text_range": ["0", str(len(full_text))],
                            "entities": {
                                "hashtags": [],
                                "symbols": [],
                                "user_mentions": [],
                                "urls": [],
                            },
                            "favorite_count": "0",
                            "id_str": "111",
                            "truncated": False,
                            "retweet_count": "0",
                            "id": "111",
                            "favorited": False,
                            "full_text": full_text,
                            "lang": "en",
                            "source": "web",
                            "retweeted": False,
                        }
                    }
                ],
                "community-tweet": [],
                "note-tweet": [],
                "like": [],
                "follower": [],
                "following": [],
            }

        engine = get_engine("sqlite:///:memory:")
        init_db(engine)
        with Session(engine) as session:
            import_archive_data(make_archive("hello"), session)
            import_archive_data(make_archive("hello updated"), session)

            rows = session.exec(
                text(
                    "SELECT account_id, full_text FROM tweet_fts WHERE tweet_id = :tweet_id"
                ).bindparams(tweet_id="111")
            ).all()

            tweet = session.get(Tweet, "111")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "42")
        self.assertEqual(rows[0][1], "hello updated")
        self.assertIsNotNone(tweet)
        tweet = cast(Tweet, tweet)
        self.assertEqual(tweet.full_text, "hello updated")
