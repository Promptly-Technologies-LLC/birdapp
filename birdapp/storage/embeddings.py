from __future__ import annotations

import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from birdapp.config import get_credential, get_embedding_credential
from birdapp.storage.dates import coerce_datetime, format_timestamp
from birdapp.storage.db import get_default_db_url, get_engine, get_session, init_db
from birdapp.storage.models import Account, Tweet

_DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


class EmbeddingsUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class EmbeddingConfig:
    api_key: str
    model: str


@dataclass(frozen=True)
class SemanticSearchResult:
    tweet_id: str
    created_at: datetime | None
    full_text: str
    tweet_kind: str
    owner_account_id: str
    owner_username: str
    owner_display_name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "tweet_id": self.tweet_id,
            "created_at": format_timestamp(self.created_at),
            "full_text": self.full_text,
            "tweet_kind": self.tweet_kind,
            "owner": {
                "account_id": self.owner_account_id,
                "username": self.owner_username,
                "account_display_name": self.owner_display_name,
            },
        }


def resolve_embedding_config(model_override: str | None) -> EmbeddingConfig:
    api_key = (
        os.getenv("OPENAI_API_KEY")
        or get_embedding_credential("OPENAI_API_KEY")
        or get_credential("OPENAI_API_KEY")
    )
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for embeddings.")
    model = (
        model_override
        or os.getenv("BIRDAPP_EMBEDDING_MODEL")
        or get_embedding_credential("BIRDAPP_EMBEDDING_MODEL")
        or get_credential("BIRDAPP_EMBEDDING_MODEL")
        or _DEFAULT_EMBEDDING_MODEL
    )
    return EmbeddingConfig(api_key=api_key, model=model)


def embed_tweets_in_db(
    db_url: str | None,
    *,
    model_override: str | None = None,
    batch_size: int = 100,
) -> int:
    if not db_url:
        db_url = get_default_db_url()
    engine = get_vec_engine(db_url)
    init_db(engine)
    with get_session(engine) as session:
        return embed_tweets(session, model_override=model_override, batch_size=batch_size)


def embed_tweets(
    session: Session,
    *,
    model_override: str | None = None,
    batch_size: int = 100,
) -> int:
    config = resolve_embedding_config(model_override)
    rows = session.exec(
        select(Tweet.tweet_id, Tweet.account_id, Tweet.full_text).where(
            Tweet.full_text != ""
        )
    ).all()
    if not rows:
        return 0

    client = _get_openai_client(config.api_key)
    inserted = 0
    first_batch = True
    for batch in _chunked(rows, batch_size):
        texts = [row.full_text for row in batch]
        response = client.embeddings.create(model=config.model, input=texts)
        embeddings = [item.embedding for item in response.data]
        if not embeddings:
            continue
        if first_batch:
            dimensions = len(embeddings[0])
            ensure_vec_table(session, dimensions=dimensions)
            clear_vec_table(session)
            first_batch = False
        for row, embedding in zip(batch, embeddings, strict=True):
            session.exec(
                text(
                    "INSERT INTO tweet_embedding(account_id, embedding, tweet_id) "
                    "VALUES(:account_id, :embedding, :tweet_id)"
                ).bindparams(
                    account_id=row.account_id,
                    embedding=json.dumps(embedding),
                    tweet_id=row.tweet_id,
                )
            )
            inserted += 1
        session.commit()
    return inserted


def semantic_search_tweets_in_db(
    db_url: str | None,
    *,
    query: str,
    author: str | None = None,
    since: date | None = None,
    until: date | None = None,
    limit: int = 20,
    model_override: str | None = None,
) -> list[SemanticSearchResult]:
    if not db_url:
        db_url = get_default_db_url()
    engine = get_vec_engine(db_url)
    init_db(engine)
    with get_session(engine) as session:
        return semantic_search_tweets(
            session,
            query=query,
            author=author,
            since=since,
            until=until,
            limit=limit,
            model_override=model_override,
        )


def semantic_search_tweets(
    session: Session,
    *,
    query: str,
    author: str | None = None,
    since: date | None = None,
    until: date | None = None,
    limit: int = 20,
    model_override: str | None = None,
) -> list[SemanticSearchResult]:
    if not query.strip():
        return []
    if not embeddings_available(session):
        raise EmbeddingsUnavailable('No embeddings found. Run "birdapp embed" first.')

    config = resolve_embedding_config(model_override)
    account_id = _resolve_author_account_id(session, author)
    if author and account_id is None:
        return []

    client = _get_openai_client(config.api_key)
    query_embedding = client.embeddings.create(
        model=config.model, input=[query]
    ).data[0].embedding
    embedding_json = json.dumps(query_embedding)

    since_dt = _date_to_utc_datetime(since, end=False)
    until_dt = _date_to_utc_datetime(until, end=True)

    statement = text(
        """
        WITH candidates AS (
          SELECT te.tweet_id
          FROM tweet_embedding te
          WHERE te.embedding MATCH :query_embedding
            AND k = :k
            AND (:account_id IS NULL OR te.account_id = :account_id)
        )
        SELECT
          t.tweet_id,
          t.created_at,
          t.full_text,
          t.tweet_kind,
          a.account_id AS owner_account_id,
          a.username AS owner_username,
          a.account_display_name AS owner_display_name
        FROM candidates
        JOIN tweet t ON t.tweet_id = candidates.tweet_id
        JOIN account a ON a.account_id = t.account_id
        WHERE (:since IS NULL OR t.created_at >= :since)
          AND (:until IS NULL OR t.created_at <= :until)
        ORDER BY t.created_at IS NULL, t.created_at DESC
        LIMIT :limit;
        """
    ).bindparams(
        query_embedding=embedding_json,
        k=limit,
        account_id=account_id,
        since=since_dt,
        until=until_dt,
        limit=limit,
    )
    rows = session.exec(statement).mappings().all()
    results: list[SemanticSearchResult] = []
    for row in rows:
        created_at = coerce_datetime(row["created_at"])
        results.append(
            SemanticSearchResult(
                tweet_id=row["tweet_id"],
                created_at=created_at,
                full_text=row["full_text"],
                tweet_kind=row["tweet_kind"],
                owner_account_id=row["owner_account_id"],
                owner_username=row["owner_username"],
                owner_display_name=row["owner_display_name"],
            )
        )
    return results


def embeddings_available(session: Session) -> bool:
    try:
        count = session.exec(
            text("SELECT COUNT(*) AS count FROM tweet_embedding")
        ).one()
    except Exception:
        return False
    return bool(count and count[0] > 0)


def semantic_results_payload(results: list[SemanticSearchResult]) -> dict[str, Any]:
    return {"count": len(results), "results": [result.to_dict() for result in results]}


def ensure_vec_table(session: Session, *, dimensions: int) -> None:
    statement = text(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS tweet_embedding USING vec0(
          account_id TEXT partition key,
          embedding float[{dimensions}],
          tweet_id TEXT
        );
        """
    )
    session.exec(statement)


def clear_vec_table(session: Session) -> None:
    session.exec(text("DELETE FROM tweet_embedding"))


def get_vec_engine(db_url: str) -> Engine:
    engine = get_engine(db_url)
    _register_sqlite_vec_loader(engine)
    return engine


def _register_sqlite_vec_loader(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _load_sqlite_vec(dbapi_connection: Any, _record: Any) -> None:
        try:
            dbapi_connection.enable_load_extension(True)
        except Exception as exc:
            raise RuntimeError(
                "Failed to enable SQLite extension loading for sqlite-vec."
            ) from exc
        try:
            import sqlite_vec
        except Exception as exc:
            raise RuntimeError(
                "sqlite-vec is required. Install it to enable embeddings."
            ) from exc
        try:
            sqlite_vec.load(dbapi_connection)
        except Exception as exc:
            raise RuntimeError(
                "sqlite-vec extension could not be loaded."
            ) from exc
        finally:
            try:
                dbapi_connection.enable_load_extension(False)
            except Exception:
                pass


def _get_openai_client(api_key: str) -> Any:
    from openai import OpenAI

    return OpenAI(api_key=api_key)


def _resolve_author_account_id(session: Session, author: str | None) -> str | None:
    if not author:
        return None
    normalized = author.strip().lstrip("@")
    statement = select(Account.account_id).where(Account.username == normalized).limit(1)
    account_id = session.exec(statement).first()
    return account_id


def _date_to_utc_datetime(value: date | None, *, end: bool) -> datetime | None:
    if value is None:
        return None
    bound = time.max if end else time.min
    return datetime.combine(value, bound, tzinfo=UTC)


def _chunked(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]
