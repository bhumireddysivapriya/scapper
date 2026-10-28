from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import pytest

from app.database import Base, initialize_database
from app.models import Product


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
    engine.dispose()
