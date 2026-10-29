from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    price: float
    availability: str
    rating: str
    url: str
    image_url: str | None = None
    category: str | None = None
    description: str | None = None
    source: str = "books.toscrape.com"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_scraped_at: datetime | None = None


class ProductPage(BaseModel):
    total: int
    limit: int
    offset: int
    products: list[ProductResponse]


class DashboardStats(BaseModel):
    total_books: int
    in_stock: int
    out_of_stock: int
    availability_unknown: int
    average_rating: float | None
    average_price: float | None
    min_price: float | None
    max_price: float | None
    top_rating: str | None
    top_rated_count: int
    top_rated_titles: list[str]


class ScrapeJobResponse(BaseModel):
    id: int
    status: str
    started_at: datetime
    completed_at: datetime | None
    total_books: int
    successful_books: int
    failed_books: int
    error_message: str | None


class PriceHistoryResponse(BaseModel):
    id: int
    book_id: int
    price: float
    availability: str | None
    recorded_at: datetime
