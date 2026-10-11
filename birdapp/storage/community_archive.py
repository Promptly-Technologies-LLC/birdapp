"""Fetch a public Twitter Community Archive through its PostgREST API.

The per-user ``archive.json`` storage bucket is no longer published. Username
imports page the read-only Supabase API instead. Responses are capped at 1,000
rows, so each table is read with a keyset on a unique column.
"""

from __future__ import annotations

import re
from typing import Any

import requests

COMMUNITY_ARCHIVE_API_URL = "https://fabxmporizzqflnftavs.supabase.co"
COMMUNITY_ARCHIVE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZhYnhtcG9yaXp6cWZsbmZ0YXZzIiwicm9sZSI6ImFub24i"
    "LCJpYXQiOjE3MjIyNDQ5MTIsImV4cCI6MjAzNzgyMDkxMn0."
    "UIEJiUNkLsW28tBHmG-RQDW-I5JNlJLt62CSk9D_qG8"
)
COMMUNITY_ARCHIVE_PAGE_SIZE = 1000
_REQUEST_TIMEOUT_SECONDS = 60
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")

_ACCOUNT_SELECT = "account_id,username,account_display_name,created_at,created_via"
_PROFILE_SELECT = "bio,website,location,avatar_media_url,header_media_url"
_TWEET_SELECT = (
    "tweet_id,created_at,full_text,favorite_count,retweet_count,"
    "reply_to_tweet_id,reply_to_user_id,reply_to_username,"
    "tweet_urls(url,expanded_url,display_url),"
    "tweet_media(media_id,media_type,media_url,width,height),"
    "user_mentions(mentioned_user_id,mentioned_users(name,screen_name)),"
    "retweets!fk_retweets_tweet_id(retweeted_tweet_id)"
)
_LIKE_SELECT = "id,liked_tweet_id,liked_tweets(full_text)"
_FOLLOWER_SELECT = "id,follower_account_id"
_FOLLOWING_SELECT = "id,following_account_id"


class CommunityArchiveError(Exception):
    """The Community Archive API response could not be imported."""


def fetch_community_archive(
    username: str,
    *,
    session: requests.Session | None = None,
    api_url: str = COMMUNITY_ARCHIVE_API_URL,
    anon_key: str = COMMUNITY_ARCHIVE_ANON_KEY,
    page_size: int = COMMUNITY_ARCHIVE_PAGE_SIZE,
) -> dict[str, Any]:
    """Download one public account and normalize it to archive-shaped JSON."""
    if page_size < 1 or page_size > COMMUNITY_ARCHIVE_PAGE_SIZE:
        raise ValueError(
            f"page_size must be between 1 and {COMMUNITY_ARCHIVE_PAGE_SIZE}."
        )
    normalized_username = _normalize_username(username)
    owns_session = session is None
    if session is None:
        session = requests.Session()
    headers = {
        "apikey": anon_key,
        "Authorization": f"Bearer {anon_key}",
        "Accept": "application/json",
    }
    try:
        accounts = _get_rows(
            session,
            api_url,
            "all_account",
            headers=headers,
            params={
                "select": _ACCOUNT_SELECT,
                "username": f"ilike.{normalized_username}",
                "limit": "2",
            },
        )
        if not accounts:
            raise CommunityArchiveError(
                f"No Community Archive account found for username {normalized_username!r}."
            )
        if len(accounts) > 1:
            raise CommunityArchiveError(
                "Multiple Community Archive accounts match username "
                f"{normalized_username!r}."
            )
        account = accounts[0]
        if not isinstance(account, dict):
            raise CommunityArchiveError("Community Archive account response was not an object.")
        account_id = str(account.get("account_id") or "").strip()
        if not account_id:
            raise CommunityArchiveError("Community Archive account is missing an account id.")

        profiles = _get_rows(
            session,
            api_url,
            "all_profile",
            headers=headers,
            params={
                "select": _PROFILE_SELECT,
                "account_id": f"eq.{account_id}",
                "limit": "2",
            },
        )
        if len(profiles) > 1:
            raise CommunityArchiveError(
                f"Multiple Community Archive profiles match account {account_id!r}."
            )
        profile = profiles[0] if profiles else None
        if profile is not None and not isinstance(profile, dict):
            raise CommunityArchiveError("Community Archive profile response was not an object.")

        account_filter = {"account_id": f"eq.{account_id}"}
        tweets = _get_pages(
            session,
            api_url,
            "enriched_tweets",
            headers=headers,
            select=_TWEET_SELECT,
            filters=account_filter,
            order="tweet_id.asc",
            cursor_column="tweet_id",
            page_size=page_size,
        )
        likes = _get_pages(
            session,
            api_url,
            "likes",
            headers=headers,
            select=_LIKE_SELECT,
            filters=account_filter,
            order="id.asc",
            cursor_column="id",
            page_size=page_size,
        )
        followers = _get_pages(
            session,
            api_url,
            "followers",
            headers=headers,
            select=_FOLLOWER_SELECT,
            filters=account_filter,
            order="id.asc",
            cursor_column="id",
            page_size=page_size,
        )
        following = _get_pages(
            session,
            api_url,
            "following",
            headers=headers,
            select=_FOLLOWING_SELECT,
            filters=account_filter,
            order="id.asc",
            cursor_column="id",
            page_size=page_size,
        )
    finally:
        if owns_session:
            session.close()

    return archive_from_community_rows(
        account=account,
        profile=profile,
        tweets=tweets,
        likes=likes,
        followers=followers,
        following=following,
    )


def archive_from_community_rows(
    *,
    account: dict[str, Any],
    profile: dict[str, Any] | None,
    tweets: list[dict[str, Any]],
    likes: list[dict[str, Any]],
    followers: list[dict[str, Any]],
    following: list[dict[str, Any]],
) -> dict[str, Any]:
    """Convert PostgREST rows into the document shape archive import expects."""
    archive: dict[str, Any] = {
        "account": [
            {
                "account": {
                    "accountId": _required_text(account, "account_id", "account"),
                    "username": _optional_text(account.get("username")),
                    "accountDisplayName": _optional_text(account.get("account_display_name")),
                    "createdAt": _optional_text(account.get("created_at")),
                    "createdVia": _optional_text(account.get("created_via")),
                }
            }
        ],
        "tweets": [_tweet_to_archive(row) for row in tweets],
        "like": [_like_to_archive(row) for row in likes],
        "follower": [_follower_to_archive(row) for row in followers],
        "following": [_following_to_archive(row) for row in following],
    }
    if profile is not None:
        archive["profile"] = [
            {
                "profile": {
                    "description": {
                        "bio": _optional_text(profile.get("bio")),
                        "website": _optional_text(profile.get("website")),
                        "location": _optional_text(profile.get("location")),
                    },
                    "avatarMediaUrl": _optional_text(profile.get("avatar_media_url")),
                    "headerMediaUrl": _optional_text(profile.get("header_media_url")),
                }
            }
        ]
    return archive


def _normalize_username(username: str) -> str:
    candidate = username.strip()
    candidate = candidate.removeprefix("@")
    if not _USERNAME_RE.fullmatch(candidate):
        raise ValueError(
            "Community Archive username must be 1-15 letters, numbers, or underscores."
        )
    return candidate


def _get_pages(
    session: requests.Session,
    api_url: str,
    table: str,
    *,
    headers: dict[str, str],
    select: str,
    filters: dict[str, str],
    order: str,
    cursor_column: str,
    page_size: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor: Any = None
    while True:
        params = {
            "select": select,
            "order": order,
            "limit": str(page_size),
            **filters,
        }
        if cursor is not None:
            params[cursor_column] = f"gt.{cursor}"
        batch = _get_rows(session, api_url, table, headers=headers, params=params)
        rows.extend(batch)
        if len(batch) < page_size:
            return rows
        next_cursor = batch[-1].get(cursor_column)
        if next_cursor is None or next_cursor == cursor:
            raise CommunityArchiveError(
                f"Community Archive pagination for {table} stopped making progress."
            )
        cursor = next_cursor


def _get_rows(
    session: requests.Session,
    api_url: str,
    table: str,
    *,
    headers: dict[str, str],
    params: dict[str, str],
) -> list[dict[str, Any]]:
    response = session.get(
        f"{api_url.rstrip('/')}/rest/v1/{table}",
        params=params,
        headers=headers,
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    if not response.ok:
        raise CommunityArchiveError(
            f"Community Archive request failed ({response.status_code}) for {table}: "
            f"{_error_message(response)}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise CommunityArchiveError(
            f"Community Archive response for {table} was not valid JSON."
        ) from exc
    if not isinstance(payload, list):
        raise CommunityArchiveError(
            f"Community Archive response for {table} was not a list."
        )
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise CommunityArchiveError(
                f"Community Archive response for {table} contained a non-object row."
            )
        rows.append(item)
    return rows


def _error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    text = response.text.strip()
    if text:
        return text[:300]
    return response.reason or "unknown error"


def _tweet_to_archive(row: dict[str, Any]) -> dict[str, Any]:
    tweet_id = _required_text(row, "tweet_id", "tweet")
    tweet: dict[str, Any] = {
        "id": tweet_id,
        "id_str": tweet_id,
        "created_at": _optional_text(row.get("created_at")),
        "full_text": _optional_text(row.get("full_text")),
        "lang": "",
        "source": "",
        "retweeted": _is_retweet(row.get("retweets")),
        "favorited": False,
        "truncated": False,
        "favorite_count": row.get("favorite_count"),
        "retweet_count": row.get("retweet_count"),
        "entities": {
            "hashtags": [],
            "symbols": [],
            "user_mentions": _mentions(row.get("user_mentions"), tweet_id),
            "urls": _urls(row.get("tweet_urls"), tweet_id),
            "media": _media(row.get("tweet_media"), tweet_id),
        },
    }
    reply_to_tweet_id = row.get("reply_to_tweet_id")
    if reply_to_tweet_id is not None:
        reply_id = str(reply_to_tweet_id)
        tweet["in_reply_to_status_id"] = reply_id
        tweet["in_reply_to_status_id_str"] = reply_id
    reply_to_user_id = row.get("reply_to_user_id")
    if reply_to_user_id is not None:
        reply_user_id = str(reply_to_user_id)
        tweet["in_reply_to_user_id"] = reply_user_id
        tweet["in_reply_to_user_id_str"] = reply_user_id
    reply_to_username = row.get("reply_to_username")
    if reply_to_username is not None:
        tweet["in_reply_to_screen_name"] = str(reply_to_username)
    return {"tweet": tweet}


def _mentions(value: Any, tweet_id: str) -> list[dict[str, str]]:
    mentions: list[dict[str, str]] = []
    for item in _object_list(value, "user_mentions", tweet_id):
        user_id = _required_text(item, "mentioned_user_id", f"mention on tweet {tweet_id}")
        user = item.get("mentioned_users")
        if user is None:
            name = ""
            screen_name = ""
        elif isinstance(user, dict):
            name = _optional_text(user.get("name"))
            screen_name = _optional_text(user.get("screen_name"))
        else:
            raise CommunityArchiveError(
                f"Mention on tweet {tweet_id} had an unexpected user payload."
            )
        mentions.append(
            {
                "id": user_id,
                "id_str": user_id,
                "name": name,
                "screen_name": screen_name,
            }
        )
    return mentions


def _urls(value: Any, tweet_id: str) -> list[dict[str, str]]:
    urls: list[dict[str, str]] = []
    for item in _object_list(value, "tweet_urls", tweet_id):
        urls.append(
            {
                "url": _optional_text(item.get("url")),
                "expanded_url": _optional_text(item.get("expanded_url")),
                "display_url": _optional_text(item.get("display_url")),
            }
        )
    return urls


def _media(value: Any, tweet_id: str) -> list[dict[str, Any]]:
    media: list[dict[str, Any]] = []
    for item in _object_list(value, "tweet_media", tweet_id):
        media_id = item.get("media_id")
        if media_id is None or str(media_id).strip() == "":
            raise CommunityArchiveError(f"Media on tweet {tweet_id} is missing a media id.")
        media_id_str = str(media_id)
        entry: dict[str, Any] = {
            "id": media_id_str,
            "id_str": media_id_str,
            "type": _optional_text(item.get("media_type")),
            "url": "",
            "expanded_url": "",
            "display_url": "",
            "media_url": _optional_text(item.get("media_url")),
            "media_url_https": _optional_text(item.get("media_url")),
        }
        width = item.get("width")
        height = item.get("height")
        if width is not None or height is not None:
            entry["sizes"] = {"width": width, "height": height}
        media.append(entry)
    return media


def _is_retweet(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value.get("retweeted_tweet_id"))
    if isinstance(value, list):
        return any(isinstance(item, dict) and item.get("retweeted_tweet_id") for item in value)
    return False


def _like_to_archive(row: dict[str, Any]) -> dict[str, Any]:
    liked = row.get("liked_tweets")
    full_text: str | None
    if liked is None:
        full_text = None
    elif isinstance(liked, dict):
        text = liked.get("full_text")
        full_text = None if text is None else str(text)
    else:
        raise CommunityArchiveError("Community Archive like had an unexpected tweet payload.")
    return {
        "like": {
            "tweetId": _required_text(row, "liked_tweet_id", "like"),
            "fullText": full_text,
        }
    }


def _follower_to_archive(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "follower": {
            "accountId": _required_text(row, "follower_account_id", "follower"),
            "userLink": "",
        }
    }


def _following_to_archive(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "following": {
            "accountId": _required_text(row, "following_account_id", "following"),
            "userLink": "",
        }
    }


def _object_list(value: Any, label: str, tweet_id: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise CommunityArchiveError(f"{label} on tweet {tweet_id} was not a list.")
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise CommunityArchiveError(f"{label} on tweet {tweet_id} contained a non-object row.")
        rows.append(item)
    return rows


def _required_text(row: dict[str, Any], key: str, label: str) -> str:
    value = row.get(key)
    if value is None or str(value).strip() == "":
        raise CommunityArchiveError(f"Community Archive {label} is missing {key}.")
    return str(value)


def _optional_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
