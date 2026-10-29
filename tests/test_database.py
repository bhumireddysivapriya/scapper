from sqlalchemy import URL, create_engine, func, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import pytest

from app.database import (
    Base,
    initialize_database,
    normalize_database_url,
    resolve_database_url,
)
from app.models import Product
from app.main import _product_upsert_statement


def test_initialization_migrates_existing_books_without_deleting_them():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE books (
                id INTEGER PRIMARY KEY,
                title VARCHAR(300) NOT NULL,
                price FLOAT NOT NULL,
                availability VARCHAR(100) NOT NULL,
                rating VARCHAR(20) NOT NULL,
                url VARCHAR(2048) NOT NULL UNIQUE
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO books (id, title, price, availability, rating, url)
            VALUES (1, 'Legacy Book', 10.5, 'In stock', 'Four',
                    'https://books.toscrape.com/catalogue/legacy_1/index.html')
            """
        )

    initialize_database(engine)
    with Session(engine) as session:
        migrated = session.scalar(select(Product).where(Product.id == 1))
        assert migrated is not None
        assert migrated.title == "Legacy Book"
        assert session.scalar(select(func.count()).select_from(Product)) == 1

    assert "books" in inspect(engine).get_table_names()
    engine.dispose()


def test_product_url_is_unique():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    record = {
        "title": "Unique URL",
        "price": 10.0,
        "availability": "In stock",
        "rating": "One",
        "url": "https://books.toscrape.com/catalogue/unique_1/index.html",
    }
    with Session(engine) as session:
        session.add(Product(**record))
        session.add(Product(**record))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.add(Product(**record))
        session.commit()
        assert session.scalar(select(func.count()).select_from(Product)) == 1
    engine.dispose()


def test_initialization_adds_cover_column_to_existing_products_table():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                title VARCHAR(300) NOT NULL,
                price FLOAT NOT NULL,
                availability VARCHAR(100) NOT NULL,
                rating VARCHAR(20) NOT NULL,
                url VARCHAR(2048) NOT NULL UNIQUE
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO products (id, title, price, availability, rating, url)
            VALUES (1, 'Existing Product', 10, 'In stock', 'Four',
                    'https://books.toscrape.com/catalogue/existing_1/index.html')
            """
        )

    initialize_database(engine)

    with Session(engine) as session:
        existing = session.get(Product, 1)
        assert existing is not None
        assert existing.title == "Existing Product"
        assert existing.image_url is None

    assert "image_url" in {column["name"] for column in inspect(engine).get_columns("products")}
    columns = {column["name"] for column in inspect(engine).get_columns("products")}
    assert {"category", "description", "source", "created_at", "updated_at", "last_scraped_at"} <= columns
    assert {"scrape_jobs", "price_history"} <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_normalize_database_url_supports_sqlite_and_render_postgres_urls():
    assert normalize_database_url("sqlite:///./books.db") == "sqlite:///./books.db"
    assert (
        normalize_database_url("postgres://user:pass@host/books")
        == "postgresql+psycopg://user:pass@host/books"
    )
    assert (
        normalize_database_url("postgresql://user:pass@host/books")
        == "postgresql+psycopg://user:pass@host/books"
    )


def test_normalize_database_url_rejects_unsupported_databases():
    with pytest.raises(ValueError, match="SQLite or PostgreSQL"):
        normalize_database_url("mysql://user:pass@host/books")


def test_database_url_defaults_locally_but_is_required_on_render():
    assert resolve_database_url(None, is_render=False) == "sqlite:///./books.db"
    with pytest.raises(ValueError, match="must be configured on Render"):
        resolve_database_url(None, is_render=True)


def test_postgresql_upsert_compiles_for_unique_product_urls():
    statement = _product_upsert_statement(
        "postgresql",
        [
            {
                "title": "Postgres Book",
                "price": 12.5,
                "availability": "In stock",
                "rating": "Four",
                "url": "https://books.toscrape.com/catalogue/postgres_1/index.html",
                "image_url": None,
            }
        ],
    )

    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (url) DO UPDATE" in sql
    assert "image_url" in sql


def test_sqlite_file_data_is_available_after_engine_reconnect(tmp_path):
    database_path = tmp_path / "persistent.db"
    database_url = URL.create("sqlite", database=str(database_path))
    engine = create_engine(database_url)
    initialize_database(engine)

    with Session(engine) as session:
        session.add(
            Product(
                title="Persisted Book",
                price=15.0,
                availability="In stock",
                rating="Five",
                url="https://books.toscrape.com/catalogue/persisted_1/index.html",
            )
        )
        session.commit()
    engine.dispose()

    reopened_engine = create_engine(database_url)
    with Session(reopened_engine) as session:
        persisted = session.scalar(
            select(Product).where(Product.title == "Persisted Book")
        )
        assert persisted is not None
        assert persisted.price == 15.0
    reopened_engine.dispose()
