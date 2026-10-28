from collections.abc import Generator
import logging
import os

from sqlalchemy import Engine, MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith(("sqlite://", "postgresql+psycopg://")):
        return database_url
    raise ValueError("DATABASE_URL must be a SQLite or PostgreSQL URL")


def resolve_database_url(database_url: str | None, *, is_render: bool) -> str:
    if is_render and not database_url:
        raise ValueError(
            "DATABASE_URL must be configured on Render to use persistent storage"
        )
    return normalize_database_url(database_url or "sqlite:///./books.db")


DATABASE_URL = resolve_database_url(
    os.getenv("DATABASE_URL"),
    is_render=os.getenv("RENDER") == "true",
)
engine_options: dict[str, object] = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def initialize_database(target_engine: Engine = engine) -> None:
    from app.models import Product

    Base.metadata.create_all(bind=target_engine)

    with target_engine.begin() as connection:
        inspector = inspect(connection)
        if "image_url" not in {
            column["name"] for column in inspector.get_columns("products")
        }:
            connection.execute(
                text("ALTER TABLE products ADD COLUMN image_url VARCHAR(2048)")
            )
        if "books" in inspector.get_table_names():
            legacy_books = Table("books", MetaData(), autoload_with=connection)
            if target_engine.dialect.name == "sqlite":
                columns = ["id", "title", "price", "availability", "rating", "url"]
            elif target_engine.dialect.name == "postgresql":
                columns = ["title", "price", "availability", "rating", "url"]
            else:
                raise RuntimeError(
                    f"Legacy books migration is unsupported for {target_engine.dialect.name}"
                )
            values = select(*(legacy_books.c[column] for column in columns)).where(
                text("true")
            )
            if target_engine.dialect.name == "sqlite":
                statement = sqlite_insert(Product).from_select(columns, values)
            else:
                statement = postgresql_insert(Product).from_select(columns, values)
            connection.execute(statement.on_conflict_do_nothing())
    logger.info(
        "Database schema initialized dialect=%s",
        target_engine.dialect.name,
    )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
