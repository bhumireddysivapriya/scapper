from collections.abc import Callable
from contextlib import nullcontext
from datetime import datetime, timezone
import logging
import threading

import requests
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.dml import Insert

from app.database import SessionLocal
from app.models import PriceHistory, Product, ScrapeJob
from app.scraper import scrape_books

logger = logging.getLogger(__name__)
_sqlite_scrape_lock = threading.Lock()
_POSTGRES_ADVISORY_LOCK_ID = 421_029_2026
SCRAPE_SOURCE = "books.toscrape.com"


def create_scrape_job(db: Session) -> ScrapeJob:
    job = ScrapeJob(status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _acquire_scrape_lock(db: Session) -> tuple[bool, Callable[[], None]]:
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        connection = db.get_bind().connect()
        try:
            acquired = bool(
                connection.execute(
                    text("SELECT pg_try_advisory_lock(:lock_id)"),
                    {"lock_id": _POSTGRES_ADVISORY_LOCK_ID},
                ).scalar()
            )
        except Exception:
            connection.close()
            raise

        def release() -> None:
            try:
                if acquired:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_id)"),
                        {"lock_id": _POSTGRES_ADVISORY_LOCK_ID},
                    )
                    connection.commit()
            finally:
                connection.close()

        if not acquired:
            connection.close()
        return acquired, release
    if dialect == "sqlite":
        acquired = _sqlite_scrape_lock.acquire(blocking=False)
        return acquired, (
            _sqlite_scrape_lock.release if acquired else (lambda: None)
        )
    raise RuntimeError(f"Scrape locking is unsupported for {dialect}")


def _upsert_statement(dialect: str, records: list[dict[str, object]]) -> Insert:
    if dialect == "postgresql":
        statement = postgresql_insert(Product).values(records)
    elif dialect == "sqlite":
        statement = sqlite_insert(Product).values(records)
    else:
        raise RuntimeError(f"Product persistence is unsupported for {dialect}")
    return statement.on_conflict_do_update(
        index_elements=[Product.url],
        set_={
            "title": statement.excluded.title,
            "price": statement.excluded.price,
            "availability": statement.excluded.availability,
            "rating": statement.excluded.rating,
            "image_url": text("COALESCE(excluded.image_url, products.image_url)"),
            "category": text("COALESCE(excluded.category, products.category)"),
            "description": text(
                "COALESCE(excluded.description, products.description)"
            ),
            "last_scraped_at": statement.excluded.last_scraped_at,
            "updated_at": statement.excluded.updated_at,
        },
    )


def _finish_failed_job(
    db: Session,
    job: ScrapeJob,
    *,
    message: str,
    failed_books: int,
) -> None:
    job.status = "failed"
    job.completed_at = datetime.now(timezone.utc)
    job.failed_books = failed_books
    job.error_message = message
    db.commit()
    logger.warning("Scrape job failed id=%s error=%s", job.id, message)


def run_scrape_job(
    job_id: int,
    *,
    limit: int = 50,
    session_factory: sessionmaker[Session] = SessionLocal,
    scraper: Callable[..., list[dict[str, object]]] = scrape_books,
    db: Session | None = None,
) -> dict[str, int | str | None]:
    session_context = session_factory() if db is None else nullcontext(db)
    with session_context as db:
        job = db.get(ScrapeJob, job_id)
        if job is None:
            raise LookupError(f"Scrape job {job_id} does not exist")
        acquired, release_lock = _acquire_scrape_lock(db)
        if not acquired:
            _finish_failed_job(
                db,
                job,
                message="Another scrape job is already running",
                failed_books=0,
            )
            return _job_result(job)

        try:
            inserted_books = 0
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            job.error_message = None
            db.commit()

            try:
                books = scraper(limit=limit)
            except requests.RequestException as exc:
                _finish_failed_job(
                    db,
                    job,
                    message="Unable to retrieve books from the source website",
                    failed_books=1,
                )
                logger.warning("Source request failed for job %s: %s", job.id, exc)
                return _job_result(job)

            now = datetime.now(timezone.utc)
            detail_failures = sum(bool(book.get("detail_failed")) for book in books)
            scraped_records = [
                {
                    "title": str(book["title"]),
                    "price": float(book["price"]),
                    "availability": str(book["availability"]),
                    "rating": str(book["rating"]),
                    "url": str(book["url"]),
                    "image_url": (
                        str(book["image_url"]) if book.get("image_url") else None
                    ),
                    "category": (
                        str(book["category"]) if book.get("category") else None
                    ),
                    "description": (
                        str(book["description"]) if book.get("description") else None
                    ),
                    "source": SCRAPE_SOURCE,
                    "last_scraped_at": now,
                    "updated_at": now,
                }
                for book in books
            ]
            records_by_url = {str(record["url"]): record for record in scraped_records}
            records = list(records_by_url.values())

            try:
                old_products = {}
                if records:
                    old_products = {
                        product.url: (product.price, product.availability)
                        for product in db.scalars(
                            select(Product).where(
                                Product.url.in_([record["url"] for record in records])
                            )
                        ).all()
                    }
                    inserted_books = len(set(records_by_url) - set(old_products))
                    db.execute(
                        _upsert_statement(db.get_bind().dialect.name, records)
                    )
                    db.expire_all()
                    current_products = {
                        product.url: product
                        for product in db.scalars(
                            select(Product).where(
                                Product.url.in_([record["url"] for record in records])
                            )
                        ).all()
                    }
                    for record in records:
                        product = current_products[str(record["url"])]
                        previous = old_products.get(product.url)
                        if (
                            previous is None
                            or previous[0] != product.price
                            or previous[1] != product.availability
                        ):
                            db.add(
                                PriceHistory(
                                    book_id=product.id,
                                    price=product.price,
                                    availability=product.availability,
                                    recorded_at=now,
                                )
                            )
                db.flush()
                job.total_books = len(scraped_records)
                job.successful_books = len(scraped_records) - detail_failures
                job.failed_books = detail_failures
                job.status = "partial" if detail_failures else "completed"
                job.completed_at = now
                db.commit()
            except SQLAlchemyError:
                db.rollback()
                failed_job = db.get(ScrapeJob, job_id)
                if failed_job is not None:
                    _finish_failed_job(
                        db,
                        failed_job,
                        message="Scraped books could not be saved",
                        failed_books=len(records),
                    )
                logger.exception("Could not save products for scrape job %s", job_id)
                return _job_result(failed_job) if failed_job else {
                    "id": job_id,
                    "status": "failed",
                    "total_books": 0,
                    "successful_books": 0,
                    "failed_books": len(records),
                }

            logger.info(
                "Scrape job completed id=%s status=%s total=%d successful=%d failed=%d",
                job.id,
                job.status,
                job.total_books,
                job.successful_books,
                job.failed_books,
            )
            return _job_result(job, inserted_books=inserted_books)
        finally:
            release_lock()


def _job_result(
    job: ScrapeJob,
    *,
    inserted_books: int = 0,
) -> dict[str, int | str | None]:
    return {
        "id": job.id,
        "status": job.status,
        "total_books": job.total_books,
        "successful_books": job.successful_books,
        "failed_books": job.failed_books,
        "error_message": job.error_message,
        "inserted_books": inserted_books,
    }


def run_scheduled_scrape() -> dict[str, int | str | None]:
    with SessionLocal() as db:
        job = create_scrape_job(db)
        job_id = job.id
    logger.info("Starting scheduled scrape job id=%s", job_id)
    return run_scrape_job(job_id)
