"""Add book metadata, scraping jobs, and price observations.

Revision ID: 20261029_01
Revises:
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

from app.models import Base

revision = "20261029_01"
down_revision = None
branch_labels = None
depends_on = None

PRODUCT_COLUMNS = {
    "image_url": sa.Column("image_url", sa.String(2048), nullable=True),
    "category": sa.Column("category", sa.String(200), nullable=True),
    "description": sa.Column("description", sa.Text(), nullable=True),
    "source": sa.Column(
        "source",
        sa.String(100),
        nullable=False,
        server_default="books.toscrape.com",
    ),
    "created_at": sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    "updated_at": sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    "last_scraped_at": sa.Column(
        "last_scraped_at", sa.DateTime(timezone=True), nullable=True
    ),
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "products" in inspector.get_table_names():
        existing = {column["name"] for column in inspector.get_columns("products")}
        for name, column in PRODUCT_COLUMNS.items():
            if name not in existing:
                op.add_column("products", column)
        if "source" not in existing:
            op.execute(
                text(
                    "UPDATE products SET source = 'books.toscrape.com' "
                    "WHERE source IS NULL"
                )
            )
        if "created_at" not in existing:
            op.execute(text("UPDATE products SET created_at = CURRENT_TIMESTAMP"))
        if "updated_at" not in existing:
            op.execute(text("UPDATE products SET updated_at = CURRENT_TIMESTAMP"))

    Base.metadata.create_all(bind=bind)
    inspector = inspect(bind)
    unique_names = {
        constraint.get("name")
        for constraint in inspector.get_unique_constraints("products")
    }
    index_names = {index.get("name") for index in inspector.get_indexes("products")}
    if "uq_products_source_url" not in unique_names | index_names:
        op.create_index(
            "uq_products_source_url",
            "products",
            ["source", "url"],
            unique=True,
        )


def downgrade() -> None:
    raise RuntimeError(
        "This migration is intentionally non-reversible to avoid deleting book data."
    )
