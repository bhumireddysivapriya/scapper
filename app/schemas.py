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
    average_price: float | None
    min_price: float | None
    max_price: float | None
    top_rating: str | None
    top_rated_count: int
    top_rated_titles: list[str]
