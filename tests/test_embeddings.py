from __future__ import annotations

import unittest
from unittest import mock

from sqlmodel import Session

from birdapp.storage.db import get_engine, init_db
from birdapp.storage.embeddings import (
    EmbeddingsUnavailable,
    resolve_embedding_config,
    semantic_search_tweets,
)


class TestEmbeddings(unittest.TestCase):
    def test_embedding_config_requires_api_key(self) -> None:
        with (
            mock.patch("birdapp.storage.embeddings.os.getenv", return_value=None),
            mock.patch(
                "birdapp.storage.embeddings.get_embedding_credential",
                return_value=None,
            ),
            mock.patch("birdapp.storage.embeddings.get_credential", return_value=None),
            self.assertRaises(RuntimeError),
        ):
            resolve_embedding_config(model_override=None)

    def test_semantic_search_requires_embeddings(self) -> None:
        engine = get_engine("sqlite:///:memory:")
        init_db(engine)
        with (
            Session(engine) as session,
            self.assertRaises(EmbeddingsUnavailable) as exc,
        ):
            semantic_search_tweets(session, query="hello", limit=5)

        self.assertIn("No embeddings found", str(exc.exception))
