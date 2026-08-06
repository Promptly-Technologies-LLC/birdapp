from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import text
from sqlmodel import Session, select

from .dates import coerce_datetime, format_timestamp
from .db import get_default_db_url, get_engine, get_session, init_db
from .models import Account

_TWEET_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS tweet_fts USING fts5(
  tweet_id UNINDEXED,
  account_id UNINDEXED,
  full_text,
  tokenize = 'unicode61'
);
"""


@dataclass(frozen=True)
class SearchOwner:
    account_id: str
    username: str
    account_display_name: str


@dataclass(frozen=True)
class SearchResult:
    tweet_id: str
    created_at: datetime | None
    full_text: str
    tweet_kind: str
    owner: SearchOwner
    rank: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "tweet_id": self.tweet_id,
            "created_at": format_timestamp(self.created_at),
            "full_text": self.full_text,
            "tweet_kind": self.tweet_kind,
            "owner": {
                "account_id": self.owner.account_id,
                "username": self.owner.username,
                "account_display_name": self.owner.account_display_name,
            },
        }


def ensure_tweet_fts(session: Session) -> None:
    session.exec(text(_TWEET_FTS_DDL))


def sync_tweet_fts(
    session: Session,
    *,
    tweet_id: str,
    account_id: str,
    full_text: str,
) -> None:
    delete_stmt = text("DELETE FROM tweet_fts WHERE tweet_id = :tweet_id").bindparams(
        tweet_id=tweet_id
    )
    insert_stmt = text(
        "INSERT INTO tweet_fts(tweet_id, account_id, full_text) "
        "VALUES(:tweet_id, :account_id, :full_text)"
    ).bindparams(
        tweet_id=tweet_id,
        account_id=account_id,
        full_text=full_text,
    )
    session.exec(delete_stmt)
    session.exec(insert_stmt)


def search_tweets(
    session: Session,
    *,
    query: str,
    author: str | None = None,
    since: date | None = None,
    until: date | None = None,
    limit: int = 20,
) -> list[SearchResult]:
    if not query.strip():
        return []
    ensure_tweet_fts(session)

    account_id = _resolve_author_account_id(session, author)
    if author and account_id is None:
        return []

    since_dt = _date_to_utc_datetime(since, end=False)
    until_dt = _date_to_utc_datetime(until, end=True)

    statement = text(
        """
        SELECT
          t.tweet_id,
          a.account_id,
          a.username,
          a.account_display_name,
          t.created_at,
          t.full_text,
          t.tweet_kind,
          bm25(tweet_fts) AS rank
        FROM tweet_fts
        JOIN tweet t ON t.tweet_id = tweet_fts.tweet_id
        JOIN account a ON a.account_id = t.account_id
        WHERE tweet_fts MATCH :query
          AND (:account_id IS NULL OR t.account_id = :account_id)
          AND (:since IS NULL OR t.created_at >= :since)
          AND (:until IS NULL OR t.created_at <= :until)
        ORDER BY rank ASC, t.created_at IS NULL, t.created_at DESC
        LIMIT :limit;
        """
    )
    statement = statement.bindparams(
        query=query,
        account_id=account_id,
        since=since_dt,
        until=until_dt,
        limit=limit,
    )
    rows = session.exec(statement).mappings().all()

    results: list[SearchResult] = []
    for row in rows:
        created_at = coerce_datetime(row["created_at"])
        results.append(
            SearchResult(
                tweet_id=row["tweet_id"],
                created_at=created_at,
                full_text=row["full_text"],
                tweet_kind=row["tweet_kind"],
                owner=SearchOwner(
                    account_id=row["account_id"],
                    username=row["username"],
                    account_display_name=row["account_display_name"],
                ),
                rank=float(row["rank"]),
            )
        )
    return results


def search_tweets_in_db(
    db_url: str | None,
    *,
    query: str,
    author: str | None = None,
    since: date | None = None,
    until: date | None = None,
    limit: int = 20,
) -> list[SearchResult]:
    if not db_url:
        db_url = get_default_db_url()
    engine = get_engine(db_url)
    init_db(engine)
    with get_session(engine) as session:
        return search_tweets(
            session,
            query=query,
            author=author,
            since=since,
            until=until,
            limit=limit,
        )


def search_results_payload(results: list[SearchResult]) -> dict[str, Any]:
    return {"count": len(results), "results": [result.to_dict() for result in results]}


def _normalize_author(author: str) -> str:
    author = author.strip()
    if author.startswith("@"):
        return author[1:]
    return author


def _resolve_author_account_id(session: Session, author: str | None) -> str | None:
    if not author:
        return None
    normalized = _normalize_author(author)
    statement = select(Account).where(Account.username == normalized).limit(1)
    account = session.exec(statement).first()
    if account is None:
        return None
    return account.account_id


def _date_to_utc_datetime(value: date | None, *, end: bool) -> datetime | None:
    if value is None:
        return None
    bound = time.max if end else time.min
    return datetime.combine(value, bound, tzinfo=UTC)
