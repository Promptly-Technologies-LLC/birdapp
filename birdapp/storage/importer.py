from __future__ import annotations

import json
import zipfile
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

import requests
from sqlmodel import Session, select

from .db import get_default_db_url, get_engine, get_session, init_db
from .models import (
    Account,
    Follower,
    Following,
    Like,
    NoteTweet,
    Profile,
    Tweet,
    TweetHashtag,
    TweetMedia,
    TweetSymbol,
    TweetUrl,
    TweetUserMention,
    UploadOptions,
)
from .search import ensure_tweet_fts, sync_tweet_fts

ModelType = TypeVar("ModelType")

ARCHIVE_URL_TEMPLATE = (
    "https://fabxmporizzqflnftavs.supabase.co/storage/v1/object/public/"
    "archives/{username}/archive.json"
)

_TWITTER_ZIP_MANIFEST_PATH = "data/manifest.js"


def build_archive_url(username: str) -> str:
    return ARCHIVE_URL_TEMPLATE.format(username=username)


def download_archive(url: str) -> dict[str, Any]:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.json()


def load_archive(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _parse_js_assigned_json_payload(contents: str) -> Any:
    """
    Parse Twitter ZIP `.js` files that wrap a JSON payload in a JavaScript assignment, e.g.
    `window.YTD.tweets.part0 = [ ... ]`.
    """
    idx = contents.find("=")
    if idx < 0:
        raise ValueError("Expected a JavaScript assignment containing a JSON payload.")
    payload = contents[idx + 1 :].strip()
    if payload.endswith(";"):
        payload = payload[:-1].strip()
    return json.loads(payload)


def _load_twitter_zip_manifest(archive: zipfile.ZipFile) -> dict[str, Any] | None:
    try:
        raw = archive.read(_TWITTER_ZIP_MANIFEST_PATH)
    except KeyError:
        return None
    contents = raw.decode("utf-8")
    parsed = _parse_js_assigned_json_payload(contents)
    if not isinstance(parsed, dict):
        raise ValueError("Twitter archive manifest did not parse to an object.")
    return parsed


def load_twitter_zip(path: str | Path) -> dict[str, Any]:
    """
    Load a Twitter 'Download your data' ZIP and normalize it into the same
    dict[str, Any] shape expected by `import_archive_data(...)`.
    """
    path = Path(path)
    if not zipfile.is_zipfile(path):
        raise ValueError("Invalid Twitter archive ZIP: could not read ZIP file.")

    # Twitter manifest keys (camelCase) -> our importer keys.
    dataset_key_map: dict[str, str] = {
        "account": "account",
        "profile": "profile",
        "tweets": "tweets",
        "communityTweet": "community-tweet",
        "noteTweet": "note-tweet",
        "like": "like",
        "follower": "follower",
        "following": "following",
    }

    fallback_files: dict[str, str] = {
        "account": "data/account.js",
        "profile": "data/profile.js",
        "tweets": "data/tweets.js",
        "communityTweet": "data/community-tweet.js",
        "noteTweet": "data/note-tweet.js",
        "like": "data/like.js",
        "follower": "data/follower.js",
        "following": "data/following.js",
    }

    normalized: dict[str, Any] = {value: [] for value in dataset_key_map.values()}

    with zipfile.ZipFile(path) as archive:
        manifest = _load_twitter_zip_manifest(archive)
        data_types = None
        if manifest is not None:
            data_types = manifest.get("dataTypes")
            if data_types is not None and not isinstance(data_types, dict):
                raise ValueError("Twitter archive manifest has invalid dataTypes.")

        for manifest_key, output_key in dataset_key_map.items():
            files: list[str] = []
            if isinstance(data_types, dict) and manifest_key in data_types:
                entry = data_types.get(manifest_key) or {}
                if isinstance(entry, dict):
                    file_entries = entry.get("files") or []
                    if isinstance(file_entries, list):
                        for file_entry in file_entries:
                            if not isinstance(file_entry, dict):
                                continue
                            file_name = str(file_entry.get("fileName", "")).strip()
                            if file_name:
                                files.append(file_name)
            if not files:
                files = [fallback_files[manifest_key]]

            for file_name in files:
                try:
                    raw = archive.read(file_name)
                except KeyError:
                    continue
                contents = raw.decode("utf-8")
                parsed = _parse_js_assigned_json_payload(contents)
                if not isinstance(parsed, list):
                    raise ValueError(
                        f"Twitter archive file {file_name!r} did not parse to a list."
                    )
                cast_list: list[Any] = parsed
                normalized[output_key].extend(cast_list)

    # Owner attribution requires account info; treat missing/empty as fatal.
    if not isinstance(normalized.get("account"), list) or not normalized["account"]:
        raise ValueError("Twitter archive missing 'data/account.js'; cannot determine owner.")

    return normalized


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _indices_to_bounds(indices: Iterable[Any]) -> tuple[int | None, int | None]:
    items = list(indices)
    if len(items) != 2:
        return None, None
    return _safe_int(items[0]), _safe_int(items[1])

def _exists(session: Session, model: type[ModelType], filters: Sequence[Any]) -> bool:
    statement = select(model).where(*filters).limit(1)
    return session.exec(statement).first() is not None


def _parse_archive_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            try:
                parsed = datetime.strptime(candidate, "%a %b %d %H:%M:%S %z %Y")
            except ValueError:
                return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return None


def _get_owner_account_id(data: dict[str, Any]) -> str | None:
    account_list = data.get("account") or []
    if not account_list:
        return None
    account = (account_list[0] or {}).get("account") or {}
    account_id = str(account.get("accountId", "")).strip()
    return account_id or None


def _has_owner_scoped_data(data: dict[str, Any]) -> bool:
    for key in (
        "upload-options",
        "profile",
        "tweets",
        "community-tweet",
        "note-tweet",
        "like",
        "follower",
        "following",
    ):
        value = data.get(key)
        if isinstance(value, list) and value:
            return True
        if isinstance(value, dict) and value:
            return True
    return False


def import_archive_data(
    data: dict[str, Any],
    session: Session,
    *,
    batch_size: int = 1000,
) -> dict[str, int]:
    counts = {
        "upload_options": 0,
        "account": 0,
        "profile": 0,
        "tweet": 0,
        "community_tweet": 0,
        "note_tweet": 0,
        "like": 0,
        "follower": 0,
        "following": 0,
        "tweet_hashtag": 0,
        "tweet_symbol": 0,
        "tweet_user_mention": 0,
        "tweet_url": 0,
        "tweet_media": 0,
    }

    owner_account_id = _get_owner_account_id(data)
    if owner_account_id is None and _has_owner_scoped_data(data):
        raise ValueError(
            "Archive owner account id is required to import owner-scoped data."
        )
    ensure_tweet_fts(session)

    def commit_if_needed(counter: int) -> None:
        if counter % batch_size == 0:
            session.commit()

    upload_options = data.get("upload-options")
    if isinstance(upload_options, dict) and owner_account_id is not None:
        existing = session.exec(
            select(UploadOptions)
            .where(UploadOptions.account_id == owner_account_id)
            .limit(1)
        ).first()
        if existing is None:
            session.add(
                UploadOptions(
                    account_id=owner_account_id,
                    keep_private=bool(upload_options.get("keepPrivate")),
                    upload_likes=bool(upload_options.get("uploadLikes")),
                    start_date=str(upload_options.get("startDate", "")),
                    end_date=str(upload_options.get("endDate", "")),
                )
            )
            counts["upload_options"] += 1
        else:
            existing.keep_private = bool(upload_options.get("keepPrivate"))
            existing.upload_likes = bool(upload_options.get("uploadLikes"))
            existing.start_date = str(upload_options.get("startDate", ""))
            existing.end_date = str(upload_options.get("endDate", ""))

    account_list = data.get("account") or []
    for item in account_list:
        account = item.get("account") or {}
        account_id = str(account.get("accountId", ""))
        if not account_id:
            continue
        existing = session.get(Account, account_id)
        if existing is None:
            session.add(
                Account(
                    account_id=account_id,
                    username=str(account.get("username", "")),
                    account_display_name=str(account.get("accountDisplayName", "")),
                    created_at=str(account.get("createdAt", "")),
                    created_via=str(account.get("createdVia", "")),
                )
            )
            counts["account"] += 1
        else:
            existing.username = str(account.get("username", ""))
            existing.account_display_name = str(account.get("accountDisplayName", ""))
            existing.created_at = str(account.get("createdAt", ""))
            existing.created_via = str(account.get("createdVia", ""))

    profile_list = data.get("profile") or []
    for item in profile_list:
        profile = item.get("profile") or {}
        description = profile.get("description") or {}
        if owner_account_id is None:
            continue
        existing = session.get(Profile, owner_account_id)
        if existing is None:
            session.add(
                Profile(
                    account_id=owner_account_id,
                    bio=str(description.get("bio", "")),
                    website=str(description.get("website", "")),
                    location=str(description.get("location", "")),
                    avatar_media_url=str(profile.get("avatarMediaUrl", "")),
                    header_media_url=str(profile.get("headerMediaUrl", "")),
                )
            )
            counts["profile"] += 1
        else:
            existing.bio = str(description.get("bio", ""))
            existing.website = str(description.get("website", ""))
            existing.location = str(description.get("location", ""))
            existing.avatar_media_url = str(profile.get("avatarMediaUrl", ""))
            existing.header_media_url = str(profile.get("headerMediaUrl", ""))

    tweet_counter = 0
    for item in data.get("tweets") or []:
        tweet = item.get("tweet") or {}
        tweet_id = str(tweet.get("id", ""))
        if not tweet_id:
            continue
        if owner_account_id is None:
            continue
        display_text_range = tweet.get("display_text_range")
        existing = session.get(Tweet, tweet_id)
        if existing is not None and existing.account_id != owner_account_id:
            raise ValueError(
                "Tweet id collision across owners. "
                f"tweet_id={tweet_id!r}, "
                f"existing_owner_account_id={existing.account_id!r}, "
                f"new_owner_account_id={owner_account_id!r}."
            )
        if existing is None:
            session.add(
                Tweet(
                    tweet_id=tweet_id,
                    account_id=owner_account_id,
                    tweet_id_str=str(tweet.get("id_str", "")) or None,
                    tweet_kind="tweet",
                    created_at=_parse_archive_datetime(tweet.get("created_at")),
                    full_text=str(tweet.get("full_text", "")),
                    lang=str(tweet.get("lang", "")),
                    source=str(tweet.get("source", "")),
                    retweeted=bool(tweet.get("retweeted")),
                    favorited=bool(tweet.get("favorited")),
                    truncated=bool(tweet.get("truncated")),
                    favorite_count=_safe_int(tweet.get("favorite_count")),
                    retweet_count=_safe_int(tweet.get("retweet_count")),
                    display_text_range=(
                        [v for v in (_safe_int(x) for x in display_text_range or []) if v is not None]
                        if display_text_range is not None
                        else None
                    ),
                    in_reply_to_status_id=(
                        str(tweet.get("in_reply_to_status_id"))
                        if tweet.get("in_reply_to_status_id") is not None
                        else None
                    ),
                    in_reply_to_status_id_str=(
                        str(tweet.get("in_reply_to_status_id_str"))
                        if tweet.get("in_reply_to_status_id_str") is not None
                        else None
                    ),
                    in_reply_to_user_id=(
                        str(tweet.get("in_reply_to_user_id"))
                        if tweet.get("in_reply_to_user_id") is not None
                        else None
                    ),
                    in_reply_to_user_id_str=(
                        str(tweet.get("in_reply_to_user_id_str"))
                        if tweet.get("in_reply_to_user_id_str") is not None
                        else None
                    ),
                    in_reply_to_screen_name=(
                        str(tweet.get("in_reply_to_screen_name"))
                        if tweet.get("in_reply_to_screen_name") is not None
                        else None
                    ),
                    possibly_sensitive=(
                        bool(tweet.get("possibly_sensitive"))
                        if tweet.get("possibly_sensitive") is not None
                        else None
                    ),
                    edit_info=tweet.get("edit_info"),
                )
            )
            counts["tweet"] += 1
        else:
            existing.account_id = owner_account_id
            existing.tweet_id_str = str(tweet.get("id_str", "")) or None
            existing.tweet_kind = "tweet"
            existing.created_at = _parse_archive_datetime(tweet.get("created_at"))
            existing.full_text = str(tweet.get("full_text", ""))
            existing.lang = str(tweet.get("lang", ""))
            existing.source = str(tweet.get("source", ""))
            existing.retweeted = bool(tweet.get("retweeted"))
            existing.favorited = bool(tweet.get("favorited"))
            existing.truncated = bool(tweet.get("truncated"))
            existing.favorite_count = _safe_int(tweet.get("favorite_count"))
            existing.retweet_count = _safe_int(tweet.get("retweet_count"))
            existing.display_text_range = (
                [v for v in (_safe_int(x) for x in display_text_range or []) if v is not None]
                if display_text_range is not None
                else None
            )
            existing.in_reply_to_status_id = (
                str(tweet.get("in_reply_to_status_id"))
                if tweet.get("in_reply_to_status_id") is not None
                else None
            )
            existing.in_reply_to_status_id_str = (
                str(tweet.get("in_reply_to_status_id_str"))
                if tweet.get("in_reply_to_status_id_str") is not None
                else None
            )
            existing.in_reply_to_user_id = (
                str(tweet.get("in_reply_to_user_id"))
                if tweet.get("in_reply_to_user_id") is not None
                else None
            )
            existing.in_reply_to_user_id_str = (
                str(tweet.get("in_reply_to_user_id_str"))
                if tweet.get("in_reply_to_user_id_str") is not None
                else None
            )
            existing.in_reply_to_screen_name = (
                str(tweet.get("in_reply_to_screen_name"))
                if tweet.get("in_reply_to_screen_name") is not None
                else None
            )
            existing.possibly_sensitive = (
                bool(tweet.get("possibly_sensitive"))
                if tweet.get("possibly_sensitive") is not None
                else None
            )
            existing.edit_info = tweet.get("edit_info")

        sync_tweet_fts(
            session,
            tweet_id=tweet_id,
            account_id=owner_account_id,
            full_text=str(tweet.get("full_text", "")),
        )

        entities = tweet.get("entities") or {}
        for hashtag in entities.get("hashtags") or []:
            start_index, end_index = _indices_to_bounds(hashtag.get("indices") or [])
            if not _exists(
                session,
                TweetHashtag,
                [
                    TweetHashtag.tweet_id == tweet_id,
                    TweetHashtag.text == str(hashtag.get("text", "")),
                    TweetHashtag.start_index == start_index,
                    TweetHashtag.end_index == end_index,
                ],
            ):
                session.add(
                    TweetHashtag(
                        tweet_id=tweet_id,
                        text=str(hashtag.get("text", "")),
                        start_index=start_index,
                        end_index=end_index,
                    )
                )
                counts["tweet_hashtag"] += 1

        for symbol in entities.get("symbols") or []:
            start_index, end_index = _indices_to_bounds(symbol.get("indices") or [])
            if not _exists(
                session,
                TweetSymbol,
                [
                    TweetSymbol.tweet_id == tweet_id,
                    TweetSymbol.text == str(symbol.get("text", "")),
                    TweetSymbol.start_index == start_index,
                    TweetSymbol.end_index == end_index,
                ],
            ):
                session.add(
                    TweetSymbol(
                        tweet_id=tweet_id,
                        text=str(symbol.get("text", "")),
                        start_index=start_index,
                        end_index=end_index,
                    )
                )
                counts["tweet_symbol"] += 1

        for mention in entities.get("user_mentions") or []:
            start_index, end_index = _indices_to_bounds(mention.get("indices") or [])
            if not _exists(
                session,
                TweetUserMention,
                [
                    TweetUserMention.tweet_id == tweet_id,
                    TweetUserMention.user_id == (str(mention.get("id", "")) or None),
                    TweetUserMention.user_id_str == (str(mention.get("id_str", "")) or None),
                    TweetUserMention.name == str(mention.get("name", "")),
                    TweetUserMention.screen_name == str(mention.get("screen_name", "")),
                    TweetUserMention.start_index == start_index,
                    TweetUserMention.end_index == end_index,
                ],
            ):
                session.add(
                    TweetUserMention(
                        tweet_id=tweet_id,
                        user_id=str(mention.get("id", "")) or None,
                        user_id_str=str(mention.get("id_str", "")) or None,
                        name=str(mention.get("name", "")),
                        screen_name=str(mention.get("screen_name", "")),
                        start_index=start_index,
                        end_index=end_index,
                    )
                )
                counts["tweet_user_mention"] += 1

        for url in entities.get("urls") or []:
            start_index, end_index = _indices_to_bounds(url.get("indices") or [])
            if not _exists(
                session,
                TweetUrl,
                [
                    TweetUrl.tweet_id == tweet_id,
                    TweetUrl.url == str(url.get("url", "")),
                    TweetUrl.expanded_url == str(url.get("expanded_url", "")),
                    TweetUrl.display_url == str(url.get("display_url", "")),
                    TweetUrl.start_index == start_index,
                    TweetUrl.end_index == end_index,
                ],
            ):
                session.add(
                    TweetUrl(
                        tweet_id=tweet_id,
                        url=str(url.get("url", "")),
                        expanded_url=str(url.get("expanded_url", "")),
                        display_url=str(url.get("display_url", "")),
                        start_index=start_index,
                        end_index=end_index,
                    )
                )
                counts["tweet_url"] += 1

        for media in entities.get("media") or []:
            start_index, end_index = _indices_to_bounds(media.get("indices") or [])
            if not _exists(
                session,
                TweetMedia,
                [
                    TweetMedia.tweet_id == tweet_id,
                    TweetMedia.entity_type == "entities",
                    TweetMedia.media_id == (str(media.get("id", "")) or None),
                    TweetMedia.media_id_str == (str(media.get("id_str", "")) or None),
                    TweetMedia.url == str(media.get("url", "")),
                    TweetMedia.media_url == str(media.get("media_url", "")),
                ],
            ):
                session.add(
                    TweetMedia(
                        tweet_id=tweet_id,
                        entity_type="entities",
                        media_id=str(media.get("id", "")) or None,
                        media_id_str=str(media.get("id_str", "")) or None,
                        media_type=str(media.get("type", "")),
                        url=str(media.get("url", "")),
                        expanded_url=str(media.get("expanded_url", "")),
                        display_url=str(media.get("display_url", "")),
                        media_url=str(media.get("media_url", "")),
                        media_url_https=str(media.get("media_url_https", "")),
                        sizes=media.get("sizes"),
                        source_status_id=(
                            str(media.get("source_status_id"))
                            if media.get("source_status_id") is not None
                            else None
                        ),
                        source_status_id_str=(
                            str(media.get("source_status_id_str"))
                            if media.get("source_status_id_str") is not None
                            else None
                        ),
                        source_user_id=(
                            str(media.get("source_user_id"))
                            if media.get("source_user_id") is not None
                            else None
                        ),
                        source_user_id_str=(
                            str(media.get("source_user_id_str"))
                            if media.get("source_user_id_str") is not None
                            else None
                        ),
                    )
                )
                counts["tweet_media"] += 1

        extended = tweet.get("extended_entities") or {}
        for media in extended.get("media") or []:
            start_index, end_index = _indices_to_bounds(media.get("indices") or [])
            if not _exists(
                session,
                TweetMedia,
                [
                    TweetMedia.tweet_id == tweet_id,
                    TweetMedia.entity_type == "extended",
                    TweetMedia.media_id == (str(media.get("id", "")) or None),
                    TweetMedia.media_id_str == (str(media.get("id_str", "")) or None),
                    TweetMedia.url == str(media.get("url", "")),
                    TweetMedia.media_url == str(media.get("media_url", "")),
                ],
            ):
                session.add(
                    TweetMedia(
                        tweet_id=tweet_id,
                        entity_type="extended",
                        media_id=str(media.get("id", "")) or None,
                        media_id_str=str(media.get("id_str", "")) or None,
                        media_type=str(media.get("type", "")),
                        url=str(media.get("url", "")),
                        expanded_url=str(media.get("expanded_url", "")),
                        display_url=str(media.get("display_url", "")),
                        media_url=str(media.get("media_url", "")),
                        media_url_https=str(media.get("media_url_https", "")),
                        sizes=media.get("sizes"),
                        video_info=media.get("video_info"),
                        additional_media_info=media.get("additional_media_info"),
                        source_status_id=(
                            str(media.get("source_status_id"))
                            if media.get("source_status_id") is not None
                            else None
                        ),
                        source_status_id_str=(
                            str(media.get("source_status_id_str"))
                            if media.get("source_status_id_str") is not None
                            else None
                        ),
                        source_user_id=(
                            str(media.get("source_user_id"))
                            if media.get("source_user_id") is not None
                            else None
                        ),
                        source_user_id_str=(
                            str(media.get("source_user_id_str"))
                            if media.get("source_user_id_str") is not None
                            else None
                        ),
                    )
                )
                counts["tweet_media"] += 1

        tweet_counter += 1
        commit_if_needed(tweet_counter)

    community_counter = 0
    for item in data.get("community-tweet") or []:
        tweet = item.get("tweet") or {}
        tweet_id = str(tweet.get("id", ""))
        if not tweet_id:
            continue
        if owner_account_id is None:
            continue
        display_text_range = tweet.get("display_text_range")
        existing = session.get(Tweet, tweet_id)
        if existing is not None and existing.account_id != owner_account_id:
            raise ValueError(
                "Tweet id collision across owners. "
                f"tweet_id={tweet_id!r}, "
                f"existing_owner_account_id={existing.account_id!r}, "
                f"new_owner_account_id={owner_account_id!r}."
            )
        if existing is None:
            session.add(
                Tweet(
                    tweet_id=tweet_id,
                    account_id=owner_account_id,
                    tweet_id_str=str(tweet.get("id_str", "")) or None,
                    tweet_kind="community",
                    created_at=_parse_archive_datetime(tweet.get("created_at")),
                    full_text=str(tweet.get("full_text", "")),
                    lang=str(tweet.get("lang", "")),
                    source=str(tweet.get("source", "")),
                    retweeted=bool(tweet.get("retweeted")),
                    favorited=bool(tweet.get("favorited")),
                    truncated=bool(tweet.get("truncated")),
                    favorite_count=_safe_int(tweet.get("favorite_count")),
                    retweet_count=_safe_int(tweet.get("retweet_count")),
                    display_text_range=(
                        [v for v in (_safe_int(x) for x in display_text_range or []) if v is not None]
                        if display_text_range is not None
                        else None
                    ),
                    in_reply_to_status_id=(
                        str(tweet.get("in_reply_to_status_id"))
                        if tweet.get("in_reply_to_status_id") is not None
                        else None
                    ),
                    in_reply_to_status_id_str=(
                        str(tweet.get("in_reply_to_status_id_str"))
                        if tweet.get("in_reply_to_status_id_str") is not None
                        else None
                    ),
                    in_reply_to_user_id=(
                        str(tweet.get("in_reply_to_user_id"))
                        if tweet.get("in_reply_to_user_id") is not None
                        else None
                    ),
                    in_reply_to_user_id_str=(
                        str(tweet.get("in_reply_to_user_id_str"))
                        if tweet.get("in_reply_to_user_id_str") is not None
                        else None
                    ),
                    in_reply_to_screen_name=(
                        str(tweet.get("in_reply_to_screen_name"))
                        if tweet.get("in_reply_to_screen_name") is not None
                        else None
                    ),
                    possibly_sensitive=(
                        bool(tweet.get("possibly_sensitive"))
                        if tweet.get("possibly_sensitive") is not None
                        else None
                    ),
                    edit_info=tweet.get("edit_info"),
                    community_id=str(tweet.get("community_id", "")) or None,
                    community_id_str=str(tweet.get("community_id_str", "")) or None,
                    scopes=tweet.get("scopes"),
                )
            )
            counts["community_tweet"] += 1
        else:
            existing.account_id = owner_account_id
            existing.tweet_id_str = str(tweet.get("id_str", "")) or None
            existing.tweet_kind = "community"
            existing.created_at = _parse_archive_datetime(tweet.get("created_at"))
            existing.full_text = str(tweet.get("full_text", ""))
            existing.lang = str(tweet.get("lang", ""))
            existing.source = str(tweet.get("source", ""))
            existing.retweeted = bool(tweet.get("retweeted"))
            existing.favorited = bool(tweet.get("favorited"))
            existing.truncated = bool(tweet.get("truncated"))
            existing.favorite_count = _safe_int(tweet.get("favorite_count"))
            existing.retweet_count = _safe_int(tweet.get("retweet_count"))
            existing.display_text_range = (
                [v for v in (_safe_int(x) for x in display_text_range or []) if v is not None]
                if display_text_range is not None
                else None
            )
            existing.in_reply_to_status_id = (
                str(tweet.get("in_reply_to_status_id"))
                if tweet.get("in_reply_to_status_id") is not None
                else None
            )
            existing.in_reply_to_status_id_str = (
                str(tweet.get("in_reply_to_status_id_str"))
                if tweet.get("in_reply_to_status_id_str") is not None
                else None
            )
            existing.in_reply_to_user_id = (
                str(tweet.get("in_reply_to_user_id"))
                if tweet.get("in_reply_to_user_id") is not None
                else None
            )
            existing.in_reply_to_user_id_str = (
                str(tweet.get("in_reply_to_user_id_str"))
                if tweet.get("in_reply_to_user_id_str") is not None
                else None
            )
            existing.in_reply_to_screen_name = (
                str(tweet.get("in_reply_to_screen_name"))
                if tweet.get("in_reply_to_screen_name") is not None
                else None
            )
            existing.possibly_sensitive = (
                bool(tweet.get("possibly_sensitive"))
                if tweet.get("possibly_sensitive") is not None
                else None
            )
            existing.edit_info = tweet.get("edit_info")
            existing.community_id = str(tweet.get("community_id", "")) or None
            existing.community_id_str = str(tweet.get("community_id_str", "")) or None
            existing.scopes = tweet.get("scopes")

        sync_tweet_fts(
            session,
            tweet_id=tweet_id,
            account_id=owner_account_id,
            full_text=str(tweet.get("full_text", "")),
        )

        entities = tweet.get("entities") or {}
        for hashtag in entities.get("hashtags") or []:
            start_index, end_index = _indices_to_bounds(hashtag.get("indices") or [])
            if not _exists(
                session,
                TweetHashtag,
                [
                    TweetHashtag.tweet_id == tweet_id,
                    TweetHashtag.text == str(hashtag.get("text", "")),
                    TweetHashtag.start_index == start_index,
                    TweetHashtag.end_index == end_index,
                ],
            ):
                session.add(
                    TweetHashtag(
                        tweet_id=tweet_id,
                        text=str(hashtag.get("text", "")),
                        start_index=start_index,
                        end_index=end_index,
                    )
                )
                counts["tweet_hashtag"] += 1

        for symbol in entities.get("symbols") or []:
            start_index, end_index = _indices_to_bounds(symbol.get("indices") or [])
            if not _exists(
                session,
                TweetSymbol,
                [
                    TweetSymbol.tweet_id == tweet_id,
                    TweetSymbol.text == str(symbol.get("text", "")),
                    TweetSymbol.start_index == start_index,
                    TweetSymbol.end_index == end_index,
                ],
            ):
                session.add(
                    TweetSymbol(
                        tweet_id=tweet_id,
                        text=str(symbol.get("text", "")),
                        start_index=start_index,
                        end_index=end_index,
                    )
                )
                counts["tweet_symbol"] += 1

        for mention in entities.get("user_mentions") or []:
            start_index, end_index = _indices_to_bounds(mention.get("indices") or [])
            if not _exists(
                session,
                TweetUserMention,
                [
                    TweetUserMention.tweet_id == tweet_id,
                    TweetUserMention.user_id == (str(mention.get("id", "")) or None),
                    TweetUserMention.user_id_str == (str(mention.get("id_str", "")) or None),
                    TweetUserMention.name == str(mention.get("name", "")),
                    TweetUserMention.screen_name == str(mention.get("screen_name", "")),
                    TweetUserMention.start_index == start_index,
                    TweetUserMention.end_index == end_index,
                ],
            ):
                session.add(
                    TweetUserMention(
                        tweet_id=tweet_id,
                        user_id=str(mention.get("id", "")) or None,
                        user_id_str=str(mention.get("id_str", "")) or None,
                        name=str(mention.get("name", "")),
                        screen_name=str(mention.get("screen_name", "")),
                        start_index=start_index,
                        end_index=end_index,
                    )
                )
                counts["tweet_user_mention"] += 1

        for url in entities.get("urls") or []:
            start_index, end_index = _indices_to_bounds(url.get("indices") or [])
            if not _exists(
                session,
                TweetUrl,
                [
                    TweetUrl.tweet_id == tweet_id,
                    TweetUrl.url == str(url.get("url", "")),
                    TweetUrl.expanded_url == str(url.get("expanded_url", "")),
                    TweetUrl.display_url == str(url.get("display_url", "")),
                    TweetUrl.start_index == start_index,
                    TweetUrl.end_index == end_index,
                ],
            ):
                session.add(
                    TweetUrl(
                        tweet_id=tweet_id,
                        url=str(url.get("url", "")),
                        expanded_url=str(url.get("expanded_url", "")),
                        display_url=str(url.get("display_url", "")),
                        start_index=start_index,
                        end_index=end_index,
                    )
                )
                counts["tweet_url"] += 1

        community_counter += 1
        commit_if_needed(community_counter)

    note_counter = 0
    for item in data.get("note-tweet") or []:
        note = item.get("noteTweet") or {}
        note_id = str(note.get("noteTweetId", ""))
        if not note_id:
            continue
        if owner_account_id is None:
            continue
        existing = session.get(NoteTweet, note_id)
        if existing is None:
            session.add(
                NoteTweet(
                    note_tweet_id=note_id,
                    account_id=owner_account_id,
                    created_at=str(note.get("createdAt", "")),
                    updated_at=str(note.get("updatedAt", "")),
                    lifecycle=note.get("lifecycle") or {},
                    core=note.get("core") or {},
                )
            )
            counts["note_tweet"] += 1
        else:
            existing.account_id = owner_account_id
            existing.created_at = str(note.get("createdAt", ""))
            existing.updated_at = str(note.get("updatedAt", ""))
            existing.lifecycle = note.get("lifecycle") or {}
            existing.core = note.get("core") or {}
        note_counter += 1
        commit_if_needed(note_counter)

    like_counter = 0
    for item in data.get("like") or []:
        like = item.get("like") or {}
        tweet_id = str(like.get("tweetId", ""))
        if not tweet_id:
            continue
        if owner_account_id is None:
            continue
        existing = session.exec(
            select(Like)
            .where(
                Like.account_id == owner_account_id,
                Like.tweet_id == tweet_id,
            )
            .limit(1)
        ).first()
        if existing is None:
            session.add(
                Like(
                    account_id=owner_account_id,
                    tweet_id=tweet_id,
                    full_text=like.get("fullText"),
                    expanded_url=like.get("expandedUrl"),
                )
            )
            counts["like"] += 1
        else:
            existing.account_id = owner_account_id
            existing.full_text = like.get("fullText")
            existing.expanded_url = like.get("expandedUrl")
        like_counter += 1
        commit_if_needed(like_counter)

    follower_counter = 0
    for item in data.get("follower") or []:
        follower = item.get("follower") or {}
        follower_account_id = str(follower.get("accountId", ""))
        if not follower_account_id:
            continue
        if owner_account_id is None:
            continue
        user_link = str(follower.get("userLink", ""))
        existing = session.exec(
            select(Follower)
            .where(
                Follower.account_id == owner_account_id,
                Follower.follower_account_id == follower_account_id,
            )
            .limit(1)
        ).first()
        if existing is None:
            session.add(
                Follower(
                    account_id=owner_account_id,
                    follower_account_id=follower_account_id,
                    user_link=user_link,
                )
            )
            counts["follower"] += 1
        else:
            existing.user_link = user_link
        follower_counter += 1
        commit_if_needed(follower_counter)

    following_counter = 0
    for item in data.get("following") or []:
        following = item.get("following") or {}
        followed_account_id = str(following.get("accountId", ""))
        if not followed_account_id:
            continue
        if owner_account_id is None:
            continue
        user_link = str(following.get("userLink", ""))
        existing = session.exec(
            select(Following)
            .where(
                Following.account_id == owner_account_id,
                Following.followed_account_id == followed_account_id,
            )
            .limit(1)
        ).first()
        if existing is None:
            session.add(
                Following(
                    account_id=owner_account_id,
                    followed_account_id=followed_account_id,
                    user_link=user_link,
                )
            )
            counts["following"] += 1
        else:
            existing.user_link = user_link
        following_counter += 1
        commit_if_needed(following_counter)

    session.commit()
    return counts


def import_archive(
    db_url: str | None,
    *,
    username: str | None = None,
    url: str | None = None,
    path: str | Path | None = None,
    batch_size: int = 1000,
) -> dict[str, int]:
    if not db_url:
        db_url = get_default_db_url()

    if not url:
        if username:
            url = build_archive_url(username)
        elif path is None:
            raise ValueError("Provide username, url, or path.")

    if url:
        data = download_archive(url)
    else:
        if path is None:
            raise ValueError("Provide username, url, or path.")
        path_obj = Path(path)
        if zipfile.is_zipfile(path_obj):
            data = load_twitter_zip(path_obj)
        else:
            data = load_archive(path_obj)

    engine = get_engine(db_url)
    init_db(engine)
    with get_session(engine) as session:
        return import_archive_data(data, session, batch_size=batch_size)
