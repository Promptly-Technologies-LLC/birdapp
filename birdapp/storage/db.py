from pathlib import Path

from platformdirs import user_data_dir
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine


def get_default_db_url() -> str:
    data_dir = Path(user_data_dir("birdapp"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{data_dir / 'birdapp.db'}"


def get_engine(db_url: str, *, echo: bool = False) -> Engine:
    return create_engine(db_url, echo=echo)


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)


def get_session(engine: Engine) -> Session:
    return Session(engine)
