from sqlalchemy import Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    price: Mapped[float] = mapped_column(Float)
    availability: Mapped[str] = mapped_column(String(100))
    rating: Mapped[str] = mapped_column(String(20))
    url: Mapped[str] = mapped_column(String(2048), unique=True)
