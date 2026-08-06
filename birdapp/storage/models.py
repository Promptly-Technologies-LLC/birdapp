from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import JSON, Column, DateTime, Index, UniqueConstraint
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, Relationship, SQLModel


class UTCDateTime(TypeDecorator[datetime]):
    """
    Store datetimes as UTC in SQLite and re-attach UTC tzinfo on reads.

    SQLite does not preserve timezone information for DATETIME columns. This type
    normalizes bound values to UTC and returns timezone-aware UTC datetimes.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            # Treat naive values as UTC.
            return value
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(
        self, value: datetime | None, dialect: Any
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.astimezone(UTC)
        return value.replace(tzinfo=UTC)


class UploadOptions(SQLModel, table=True):
    __tablename__ = "upload_options"
    __table_args__ = (UniqueConstraint("account_id", name="uq_upload_options_account_id"),)

    id: int | None = Field(default=None, primary_key=True)
    account_id: str = Field(foreign_key="account.account_id", index=True)
    keep_private: bool
    upload_likes: bool
    start_date: str
    end_date: str


class Account(SQLModel, table=True):
    __tablename__ = "account"

    account_id: str = Field(primary_key=True, index=True)
    username: str
    account_display_name: str
    created_at: str
    created_via: str

    profile: Optional["Profile"] = Relationship(back_populates="account")


class Profile(SQLModel, table=True):
    __tablename__ = "profile"

    account_id: str = Field(primary_key=True, foreign_key="account.account_id")
    bio: str
    website: str
    location: str
    avatar_media_url: str
    header_media_url: str

    account: Account | None = Relationship(back_populates="profile")


class Tweet(SQLModel, table=True):
    __tablename__ = "tweet"
    __table_args__ = (
        Index("ix_tweet_account_id_created_at", "account_id", "created_at"),
    )

    tweet_id: str = Field(primary_key=True, index=True)
    account_id: str = Field(foreign_key="account.account_id", index=True)
    tweet_id_str: str | None = Field(default=None, index=True)
    tweet_kind: str = Field(default="tweet", index=True)
    created_at: datetime | None = Field(
        default=None, sa_column=Column(UTCDateTime(), nullable=True)
    )
    full_text: str
    lang: str
    source: str
    retweeted: bool
    favorited: bool
    truncated: bool
    favorite_count: int | None = None
    retweet_count: int | None = None
    display_text_range: list[int] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    in_reply_to_status_id: str | None = None
    in_reply_to_status_id_str: str | None = None
    in_reply_to_user_id: str | None = None
    in_reply_to_user_id_str: str | None = None
    in_reply_to_screen_name: str | None = None
    possibly_sensitive: bool | None = None
    edit_info: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    community_id: str | None = None
    community_id_str: str | None = None
    scopes: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    hashtags: list["TweetHashtag"] = Relationship(back_populates="tweet")
    symbols: list["TweetSymbol"] = Relationship(back_populates="tweet")
    user_mentions: list["TweetUserMention"] = Relationship(back_populates="tweet")
    urls: list["TweetUrl"] = Relationship(back_populates="tweet")
    media: list["TweetMedia"] = Relationship(back_populates="tweet")


class TweetHashtag(SQLModel, table=True):
    __tablename__ = "tweet_hashtag"

    id: int | None = Field(default=None, primary_key=True)
    tweet_id: str = Field(foreign_key="tweet.tweet_id", index=True)
    text: str
    start_index: int | None = None
    end_index: int | None = None

    tweet: Tweet | None = Relationship(back_populates="hashtags")


class TweetSymbol(SQLModel, table=True):
    __tablename__ = "tweet_symbol"

    id: int | None = Field(default=None, primary_key=True)
    tweet_id: str = Field(foreign_key="tweet.tweet_id", index=True)
    text: str
    start_index: int | None = None
    end_index: int | None = None

    tweet: Tweet | None = Relationship(back_populates="symbols")


class TweetUserMention(SQLModel, table=True):
    __tablename__ = "tweet_user_mention"

    id: int | None = Field(default=None, primary_key=True)
    tweet_id: str = Field(foreign_key="tweet.tweet_id", index=True)
    user_id: str | None = Field(default=None, index=True)
    user_id_str: str | None = Field(default=None, index=True)
    name: str
    screen_name: str
    start_index: int | None = None
    end_index: int | None = None

    tweet: Tweet | None = Relationship(back_populates="user_mentions")


class TweetUrl(SQLModel, table=True):
    __tablename__ = "tweet_url"

    id: int | None = Field(default=None, primary_key=True)
    tweet_id: str = Field(foreign_key="tweet.tweet_id", index=True)
    url: str
    expanded_url: str
    display_url: str
    start_index: int | None = None
    end_index: int | None = None

    tweet: Tweet | None = Relationship(back_populates="urls")


class TweetMedia(SQLModel, table=True):
    __tablename__ = "tweet_media"

    id: int | None = Field(default=None, primary_key=True)
    tweet_id: str = Field(foreign_key="tweet.tweet_id", index=True)
    entity_type: str = Field(default="entities", index=True)
    media_id: str | None = Field(default=None, index=True)
    media_id_str: str | None = Field(default=None, index=True)
    media_type: str
    url: str
    expanded_url: str
    display_url: str
    media_url: str
    media_url_https: str
    sizes: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    video_info: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    additional_media_info: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    source_status_id: str | None = None
    source_status_id_str: str | None = None
    source_user_id: str | None = None
    source_user_id_str: str | None = None

    tweet: Tweet | None = Relationship(back_populates="media")


class NoteTweet(SQLModel, table=True):
    __tablename__ = "note_tweet"

    note_tweet_id: str = Field(primary_key=True, index=True)
    account_id: str = Field(foreign_key="account.account_id", index=True)
    created_at: str
    updated_at: str
    lifecycle: dict[str, Any] = Field(sa_column=Column(JSON))
    core: dict[str, Any] = Field(sa_column=Column(JSON))


class Like(SQLModel, table=True):
    __tablename__ = "like"
    __table_args__ = (
        UniqueConstraint("account_id", "tweet_id", name="uq_like_account_id_tweet_id"),
        Index("ix_like_account_id_tweet_id", "account_id", "tweet_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    account_id: str = Field(foreign_key="account.account_id", index=True)
    tweet_id: str = Field(index=True)
    full_text: str | None = None
    expanded_url: str | None = None


class Follower(SQLModel, table=True):
    __tablename__ = "follower"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "follower_account_id",
            name="uq_follower_account_id_follower_account_id",
        ),
        Index(
            "ix_follower_account_id_follower_account_id",
            "account_id",
            "follower_account_id",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    account_id: str = Field(foreign_key="account.account_id", index=True)
    follower_account_id: str = Field(index=True)
    user_link: str


class Following(SQLModel, table=True):
    __tablename__ = "following"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "followed_account_id",
            name="uq_following_account_id_followed_account_id",
        ),
        Index(
            "ix_following_account_id_followed_account_id",
            "account_id",
            "followed_account_id",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    account_id: str = Field(foreign_key="account.account_id", index=True)
    followed_account_id: str = Field(index=True)
    user_link: str
