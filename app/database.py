from collections.abc import Generator
import os

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./books.db")

if not DATABASE_URL.startswith("sqlite"):
    raise ValueError("DATABASE_URL must be a SQLite URL")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def initialize_database(target_engine: Engine = engine) -> None:
    Base.metadata.create_all(bind=target_engine)

    inspector = inspect(target_engine)
    with target_engine.begin() as connection:
        if "image_url" not in {
            column["name"] for column in inspector.get_columns("products")
        }:
            connection.execute(
                text("ALTER TABLE products ADD COLUMN image_url VARCHAR(2048)")
            )
        if "books" in inspector.get_table_names():
            connection.execute(
                text(
                    """
                    INSERT OR IGNORE INTO products
                        (id, title, price, availability, rating, url)
                    SELECT id, title, price, availability, rating, url
                    FROM books
                    """
                )
            )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
