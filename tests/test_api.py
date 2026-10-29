import csv
from io import StringIO
import time

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy import func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Product


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = test_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("app.main.SCRAPE_COOLDOWN_SECONDS", 0)
    monkeypatch.setattr("app.main._last_scrape_at", None)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


def product(title="A Light in the Attic", price=51.77, availability="In stock"):
    return {
        "title": title,
        "price": price,
        "availability": availability,
        "rating": "Three",
        "url": f"https://books.toscrape.com/catalogue/{title.lower().replace(' ', '-')}_1/index.html",
        "image_url": None,
    }


def test_home_and_health(client):
    home = client.get("/")
    assert home.status_code == 200
    assert 'href="#books"' not in home.text
    assert "Main navigation" not in home.text
    assert ">Books</a>" not in home.text
    assert ">Analytics</a>" not in home.text
    assert ">Settings</a>" not in home.text
    assert "brand-caption" not in home.text
    assert 'href="/docs"' not in home.text
    assert 'id="books"' not in home.text
    assert "Scraped books" not in home.text
    assert 'id="scraping-history"' not in home.text
    assert "Recent scraping activity" not in home.text
    assert 'id="refresh-button"' in home.text
    assert 'id="scrape-button"' in home.text
    assert 'id="scrape-status"' in home.text
    assert 'id="average-rating"' in home.text
    assert 'class="highlight-table"' in home.text
    assert '<h1 class="dashboard-title">Book Analytics</h1>' in home.text
    assert 'id="scrape-all-button"' not in home.text
    assert 'id="scrape-contemporary-button"' not in home.text
    assert 'id="category-chart"' not in home.text
    assert 'id="rating-chart"' in home.text
    assert 'id="price-chart"' in home.text
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


def test_scrape_reports_collected_inserted_and_skipped(client, monkeypatch):
    rows = [product(), product()]
    monkeypatch.setattr("app.main.scrape_books", lambda limit: rows)

    first = client.post("/scrape?limit=2")
    second = client.post("/scrape?limit=2")

    assert first.status_code == 200
    assert first.json()["products_collected"] == 2
    assert first.json()["products_inserted"] == 1
    assert first.json()["products_skipped"] == 1
    assert second.json()["products_inserted"] == 0
    assert second.json()["products_skipped"] == 2


def test_scrape_refreshes_cover_for_existing_product_without_counting_insert(client, monkeypatch):
    row = {**product(), "image_url": "https://books.toscrape.com/media/cache/cover.jpg"}
    monkeypatch.setattr("app.main.scrape_books", lambda limit: [{**row, "image_url": None}])

    response = client.post("/scrape?limit=1")

    assert response.status_code == 200
    assert response.json()["products_inserted"] == 1
    monkeypatch.setattr("app.main.scrape_books", lambda limit: [row])
    duplicate = client.post("/scrape?limit=1")
    assert duplicate.json()["products_inserted"] == 0
    assert duplicate.json()["products_skipped"] == 1
    assert client.get("/products").json()["products"][0]["image_url"] == row["image_url"]


def test_scrape_network_error_returns_gateway_error(client, monkeypatch):
    def fail_scrape(limit):
        raise requests.Timeout("test timeout")

    monkeypatch.setattr("app.main.scrape_books", fail_scrape)
    response = client.post("/scrape")
    assert response.status_code == 502
    assert response.json()["detail"] == "Unable to retrieve books from the source website"


def test_products_search_filters_pagination_and_legacy_books(client):
    db = next(app.dependency_overrides[get_db]())
    try:
        db.add_all(
            [
                Product(**product()),
                Product(**product("Light and Shadow", 25, "In stock")),
                Product(**product("A Quiet Book", 12, "Out of stock")),
            ]
        )
        db.commit()
        expected_id = db.scalar(
            select(Product.id).where(Product.title == "A Light in the Attic")
        )
    finally:
        db.close()

    response = client.get(
        "/products?search=light&min_price=10&max_price=60&availability=In%20stock&limit=1"
    )
    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert len(response.json()["products"]) == 1
    assert response.json()["products"][0]["title"] == "A Light in the Attic"
    assert response.json()["products"][0]["image_url"] is None
    assert response.json()["limit"] == 1

    next_page = client.get("/products?search=light&offset=1&limit=1")
    assert next_page.json()["products"][0]["title"] == "Light and Shadow"
    assert len(client.get("/books?search=light").json()) == 2
    assert len(client.get("/products?availability=Out%20of%20stock").json()["products"]) == 1

    single = client.get(f"/products/{expected_id}")
    assert single.status_code == 200
    assert single.json()["title"] == "A Light in the Attic"


def test_products_returns_404_for_missing_id(client):
    response = client.get("/products/999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Product not found"


def test_csv_export_includes_all_matching_products_and_safe_values(client):
    db = next(app.dependency_overrides[get_db]())
    try:
        db.add_all(
            [
                Product(
                    **{
                        **product("=SUM(1,1)", 25, "In stock"),
                        "image_url": "https://books.toscrape.com/media/cache/cover.jpg",
                    }
                ),
                Product(**product("A Light in the Attic", 51.77, "In stock")),
                Product(**product("Out of range", 5, "Out of stock")),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = client.get(
        "/products/export.csv?min_price=10&max_price=30&availability=In%20stock"
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="books.csv"' == response.headers["content-disposition"]
    reader = csv.DictReader(StringIO(response.content.decode("utf-8-sig")))
    rows = list(reader)
    assert reader.fieldnames == [
        "title",
        "category",
        "price",
        "availability",
        "rating",
        "product_url",
        "image_url",
    ]
    assert len(rows) == 1
    assert rows[0]["title"] == "'=SUM(1,1)"
    assert rows[0]["category"] == ""
    assert rows[0]["price"] == "25.00"
    assert rows[0]["image_url"] == "https://books.toscrape.com/media/cache/cover.jpg"


def test_dashboard_stats_summarize_books_ratings_prices_and_availability(client):
    db = next(app.dependency_overrides[get_db]())
    try:
        db.add_all(
            [
                Product(**{**product("Top-rated One", 10, "In stock"), "rating": "Five"}),
                Product(**{**product("Top-rated Two", 20, "In stock"), "rating": "Five"}),
                Product(**{**product("Out Book", 30, "Out of stock"), "rating": "Four"}),
                Product(**{**product("Unknown Stock", 40, "Unknown"), "rating": "Unknown"}),
            ]
        )
        db.commit()
    finally:
        db.close()

    stats = client.get("/dashboard/stats")
    assert stats.status_code == 200
    assert stats.json() == {
        "total_books": 4,
        "in_stock": 2,
        "out_of_stock": 1,
        "availability_unknown": 1,
        "average_rating": 4.666666666666667,
        "average_price": 25.0,
        "min_price": 10.0,
        "max_price": 40.0,
        "top_rating": "Five",
        "top_rated_count": 2,
        "top_rated_titles": ["Top-rated One", "Top-rated Two"],
    }


@pytest.mark.parametrize(
    "query",
    [
        "?limit=0",
        "?limit=101",
        "?offset=-1",
        "?min_price=-1",
        "?min_price=20&max_price=10",
        "?search=" + ("x" * 101),
    ],
)
def test_invalid_product_parameters_return_422(client, query):
    response = client.get(f"/products{query}")
    assert response.status_code == 422


def test_scrape_limit_validation(client):
    response = client.post("/scrape?limit=0")
    assert response.status_code == 422


def test_scrape_cooldown_returns_retry_after(client, monkeypatch):
    monkeypatch.setattr("app.main.SCRAPE_COOLDOWN_SECONDS", 60)
    monkeypatch.setattr("app.main._last_scrape_at", time.monotonic())
    response = client.post("/scrape")
    assert response.status_code == 429
    assert response.headers["Retry-After"]


def test_scrape_tracks_updates_price_history_and_job_status(client, monkeypatch):
    monkeypatch.setattr("app.main.scrape_books", lambda limit: [product(price=10)])
    first = client.post("/scrape?limit=1")
    assert first.status_code == 200
    assert first.json()["products_inserted"] == 1

    monkeypatch.setattr(
        "app.main.scrape_books",
        lambda limit: [product(price=14.5, availability="Out of stock")],
    )
    second = client.post("/scrape?limit=1")
    assert second.status_code == 200
    assert second.json()["products_inserted"] == 0

    book = client.get("/api/books?sort_by=price&sort_order=desc").json()["products"][0]
    assert book["price"] == 14.5
    assert book["availability"] == "Out of stock"
    history = client.get(f"/api/books/{book['id']}/price-history").json()
    assert [entry["price"] for entry in history] == [14.5, 10.0]
    assert [entry["availability"] for entry in history] == [
        "Out of stock",
        "In stock",
    ]

    analytics = client.get("/api/analytics/prices").json()
    price = analytics["books"][0]
    assert price["current_price"] == 14.5
    assert price["previous_observed_price"] == 10.0
    assert price["price_change"] == 4.5
    assert price["percentage_change"] == 45.0
    assert price["lowest_historical_price"] == 10.0
    assert price["highest_historical_price"] == 14.5
    assert price["average_historical_price"] == 12.25
    assert price["history_observation_count"] == 2

    jobs = client.get("/api/scrape/history").json()
    assert [job["status"] for job in jobs] == ["completed", "completed"]
    assert client.get(f"/api/scrape/status/{jobs[0]['id']}").json()["total_books"] == 1
    assert client.get("/api/dashboard/stats").json()["total_books"] == 1
    assert client.get("/api/analytics/availability").json()["total_books"] == 1
    assert client.get("/api/analytics/ratings").json()["total_rated_books"] == 1


def test_queued_scrape_api_and_unknown_job_response(client, monkeypatch):
    monkeypatch.setattr("app.main.scrape_books", lambda limit: [product()])
    response = client.post("/api/scrape?limit=1")
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert client.get(f"/api/scrape/status/{job_id}").json()["status"] == "completed"
    assert client.get("/api/scrape/status/999").status_code == 404


def test_api_books_filter_and_csv_alias(client):
    db = next(app.dependency_overrides[get_db]())
    try:
        db.add_all(
            [
                Product(**{**product("Travel Book", 20), "category": "Travel"}),
                Product(**{**product("History Book", 10), "category": "History"}),
            ]
        )
        db.commit()
    finally:
        db.close()

    filtered = client.get("/api/books?category=travel&sort_by=price&sort_order=desc")
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["products"][0]["title"] == "Travel Book"
    assert client.get("/api/export/csv").headers["content-type"].startswith("text/csv")


def test_category_analytics_and_sorted_category_books(client):
    db = next(app.dependency_overrides[get_db]())
    try:
        db.add_all(
            [
                Product(**{**product("Affordable Travel", 8), "category": "Travel", "rating": "Five"}),
                Product(**{**product("Top Travel", 20), "category": "Travel", "rating": "Five"}),
                Product(**{**product("History", 15), "category": "History", "rating": "Four"}),
            ]
        )
        db.commit()
    finally:
        db.close()

    overview = client.get("/api/analytics/overview")
    assert overview.status_code == 200
    payload = overview.json()
    assert payload["categories"] == [
        {"category": "Travel", "count": 2},
        {"category": "History", "count": 1},
    ]
    assert payload["ratings"] == [
        {"rating": "1 star", "count": 0},
        {"rating": "2 stars", "count": 0},
        {"rating": "3 stars", "count": 0},
        {"rating": "4 stars", "count": 1},
        {"rating": "5 stars", "count": 2},
    ]
    assert payload["top_rated_books"][0]["title"] == "Affordable Travel"
    assert payload["lowest_priced_books"][0]["title"] == "Affordable Travel"

    filtered = client.get("/products?category=Travel&sort_by=rating&sort_order=desc")
    assert filtered.json()["total"] == 2
    assert [book["title"] for book in filtered.json()["products"]] == [
        "Affordable Travel",
        "Top Travel",
    ]
    assert client.get("/products?rating=Five").json()["total"] == 2
    assert client.get("/products?min_price=50").json()["total"] == 0
    assert payload["highest_priced_books"][0]["title"] == "Top Travel"


def test_full_catalogue_scrape_limit_is_supported(client, monkeypatch):
    received_limits = []
    monkeypatch.setattr(
        "app.main.scrape_books",
        lambda limit: received_limits.append(limit) or [],
    )
    response = client.post("/api/scrape?limit=1000")
    assert response.status_code == 202
    assert received_limits == [1000]
    assert client.post("/api/scrape?limit=1001").status_code == 422


def test_contemporary_category_scrape_queues_the_category_url(client, monkeypatch):
    source_url = (
        "https://books.toscrape.com/catalogue/category/books/"
        "contemporary_38/index.html"
    )
    scrape_arguments = []

    def fake_scrape(limit, *, start_url):
        scrape_arguments.append((limit, start_url))
        return [
            {
                **product("Contemporary Novel"),
                "category": "Contemporary",
                "description": "A novel.",
            }
        ]

    monkeypatch.setattr("app.main.scrape_books", fake_scrape)
    response = client.post("/api/scrape/contemporary")

    assert response.status_code == 202
    assert scrape_arguments == [(1000, source_url)]
    job = client.get(f"/api/scrape/status/{response.json()['job_id']}")
    assert job.status_code == 200
    assert job.json()["status"] == "completed"
    assert job.json()["total_books"] == 1
    saved = client.get("/products?category=Contemporary").json()
    assert saved["total"] == 1
    assert saved["products"][0]["title"] == "Contemporary Novel"
